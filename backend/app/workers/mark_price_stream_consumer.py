"""Binance markPrice WebSocket consumer.

활성 strategy 보유 중인 심볼들의 markPrice 를 1초마다 받아 mark_price_cache 갱신.

배경:
- 기존: reconcile_worker 2분 주기 → mark_price 최대 2분 stale.
- ACCOUNT_UPDATE 이벤트는 포지션 변동 시점에만 발생 → 그 사이 PNL 정지.
- 결과: UI 가 Binance 실시간과 5~13 USDT 차이 (UBUSDT 실측).

해결:
- public market stream <symbol>@markPrice@1s 다중 구독.
- 받은 mark price 를 Redis 캐시에 즉시 push (TTL 60s).
- 활성 심볼 변동 (새 strategy/종료) 시 30s 주기로 SUBSCRIBE/UNSUBSCRIBE.

운영:
- 별도 process — `python -m app.workers.mark_price_stream_consumer`.
- public stream 이라 API key 불필요. testnet 도 동일 URL 패턴 (fstream→testnet).
- 끊김 시 exponential backoff 재연결.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Iterable

import websocket
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.services.mark_price_cache import set_mark_price
from app.utils.backoff import exponential_backoff

logger = logging.getLogger(__name__)

# Binance fstream URL — mainnet / testnet
WS_BASE_MAINNET = "wss://fstream.binance.com"
WS_BASE_TESTNET = "wss://stream.binancefuture.com"

# 활성 심볼 재조사 주기 (초). 너무 짧으면 DB 부하, 너무 길면 새 strategy 의 mark 갱신 지연.
SYMBOL_REFRESH_INTERVAL = 30

# strategy 중 "보유 중" 으로 간주할 status — 종료/대기 상태는 mark price 안 받음
ACTIVE_STATUS_NOT_IN = frozenset(
    {"WAITING", "STOPPED", "STOPPED_BY_SL", "CLOSED_BY_SL", "COMPLETED", "REENTRY_READY"}
)


def _fetch_active_symbols() -> set[str]:
    """현재 보유 중인 strategy 의 심볼 집합 (대문자). 활성 거래소 계정만."""
    db = SessionLocal()
    try:
        rows = db.execute(
            select(StrategyInstance.symbol)
            .join(ExchangeAccount, StrategyInstance.exchange_account_id == ExchangeAccount.id)
            .where(~StrategyInstance.status.in_(ACTIVE_STATUS_NOT_IN))
            .where(StrategyInstance.is_archived.is_(False))
            .where(ExchangeAccount.is_active.is_(True))
        ).scalars().all()
        return {s.upper() for s in rows if s}
    finally:
        db.close()


class MarkPriceStreamConsumer:
    """Binance fstream markPrice 다중 구독 consumer.

    동작:
    1. /stream 엔드포인트 연결 (스트림 없이 시작)
    2. 첫 SUBSCRIBE 메시지로 모든 활성 심볼 구독
    3. 30초마다 활성 심볼 재조사 → SUBSCRIBE 차집합 / UNSUBSCRIBE 차집합
    4. 메시지 수신 시 markPrice 추출 → Redis 캐시 갱신
    5. 끊김 시 exponential backoff 후 재연결 (구독 처음부터 다시)
    """

    def __init__(self, *, is_testnet: bool, on_disconnect_sleep: int = 5) -> None:
        self.is_testnet = is_testnet
        self.ws_base = WS_BASE_TESTNET if is_testnet else WS_BASE_MAINNET
        self.on_disconnect_sleep = on_disconnect_sleep
        self.ws: websocket.WebSocketApp | None = None
        self._subscribed: set[str] = set()
        self._next_req_id = 1
        self._stop_refresh = threading.Event()

    # ---- 외부 진입점 ----

    def start(self) -> None:
        attempt = 0
        while True:
            try:
                self._connect_and_run()
                attempt = 0
            except Exception as e:
                attempt += 1
                delay = exponential_backoff(attempt, base=1.0, cap=60.0, jitter=True)
                logger.warning("markPrice stream crash (attempt %d): %s; retry in %.1fs", attempt, e, delay)
                time.sleep(delay)

    # ---- 연결·구독 ----

    def _connect_and_run(self) -> None:
        # 2026-06-05 Critical: Binance 2026-04-23 deadline 후 옛 /stream endpoint 차단됨
        # (binance_websocket_change_notice 페이지 update 자동 감지 → WebFetch 검증).
        # markPrice = "Market data" 분류 → /market/stream endpoint 사용 필수.
        # 옛 /stream 은 deadline 후에도 부분 작동 중이지만 언제든 차단 가능 → 사전 마이그레이션.
        # 매핑 참조: https://developers.binance.com/docs/derivatives/usds-margined-futures/
        #            websocket-market-streams/Important-WebSocket-Change-Notice
        ws_url = f"{self.ws_base}/market/stream"
        logger.info("markPrice consumer 연결 시도 %s (testnet=%s)", ws_url, self.is_testnet)
        self._subscribed = set()
        self.ws = websocket.WebSocketApp(
            ws_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        # 활성 심볼 재조사 백그라운드 thread (연결마다 시작)
        self._stop_refresh.clear()
        refresh_thread = threading.Thread(target=self._refresh_loop, daemon=True, name="markprice-refresh")
        refresh_thread.start()
        try:
            self.ws.run_forever(ping_interval=180, ping_timeout=10)
        finally:
            self._stop_refresh.set()

    def _on_open(self, ws) -> None:
        logger.info("markPrice stream 연결됨")
        # 초기 구독: 현재 활성 심볼 전체
        symbols = _fetch_active_symbols()
        if symbols:
            self._subscribe(symbols)
            self._subscribed = symbols
        else:
            logger.info("활성 심볼 없음 — 구독 보류, 30s 후 재조사")

    def _on_message(self, ws, message: str) -> None:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return
        # SUBSCRIBE 응답 등은 무시 (id+result 형태)
        if "stream" not in data or "data" not in data:
            return
        d = data["data"] or {}
        # markPrice 이벤트: {"e":"markPriceUpdate","s":"BTCUSDT","p":"...","r":"..."}
        if d.get("e") != "markPriceUpdate":
            return
        symbol = d.get("s")
        price = d.get("p")
        if symbol and price:
            set_mark_price(symbol, price)

    def _on_error(self, ws, error) -> None:
        logger.warning("markPrice WS error: %s", error)

    def _on_close(self, ws, close_status_code, close_msg) -> None:
        logger.warning("markPrice stream 종료 code=%s msg=%s", close_status_code, close_msg)
        self._stop_refresh.set()

    # ---- 동적 구독 관리 ----

    def _refresh_loop(self) -> None:
        """주기적으로 활성 심볼 변화 감지 → SUBSCRIBE/UNSUBSCRIBE."""
        while not self._stop_refresh.is_set():
            time.sleep(SYMBOL_REFRESH_INTERVAL)
            if self._stop_refresh.is_set():
                return
            try:
                current = _fetch_active_symbols()
            except Exception as e:
                logger.warning("활성 심볼 재조사 실패: %s", e)
                continue
            to_add = current - self._subscribed
            to_remove = self._subscribed - current
            if to_add:
                self._subscribe(to_add)
            if to_remove:
                self._unsubscribe(to_remove)
            self._subscribed = current

    def _subscribe(self, symbols: Iterable[str]) -> None:
        params = [f"{s.lower()}@markPrice@1s" for s in symbols]
        if not params:
            return
        self._send({"method": "SUBSCRIBE", "params": params, "id": self._req_id()})
        logger.info("markPrice SUBSCRIBE %d 심볼: %s", len(params), ", ".join(symbols))

    def _unsubscribe(self, symbols: Iterable[str]) -> None:
        params = [f"{s.lower()}@markPrice@1s" for s in symbols]
        if not params:
            return
        self._send({"method": "UNSUBSCRIBE", "params": params, "id": self._req_id()})
        logger.info("markPrice UNSUBSCRIBE %d 심볼", len(params))

    def _send(self, payload: dict) -> None:
        if self.ws and self.ws.sock and self.ws.sock.connected:
            try:
                self.ws.send(json.dumps(payload))
            except Exception as e:
                logger.warning("markPrice send 실패: %s", e)

    def _req_id(self) -> int:
        rid = self._next_req_id
        self._next_req_id += 1
        return rid


def main() -> None:
    """진입점 — exchange_accounts 테이블에서 testnet 여부 추정 후 단일 consumer 실행.

    여러 계정이 있어도 markPrice 는 public stream 이라 계정 무관 — 첫 활성 계정의
    testnet 플래그만 참고. mainnet+testnet 혼재 환경은 본 구현 범위 밖.
    """
    import app.core.logging  # noqa: F401 — logger 초기화
    db = SessionLocal()
    try:
        account = db.execute(
            select(ExchangeAccount)
            .where(ExchangeAccount.is_active.is_(True))
            .where(ExchangeAccount.exchange_name == "binance")
        ).scalars().first()
        is_testnet = bool(account.is_testnet) if account else False
    finally:
        db.close()
    logger.info("markPrice consumer 시작 (testnet=%s)", is_testnet)
    MarkPriceStreamConsumer(is_testnet=is_testnet).start()


if __name__ == "__main__":
    main()
