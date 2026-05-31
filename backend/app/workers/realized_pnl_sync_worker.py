"""realized_pnl 자동 동기화 worker (2026-06-01 신설).

배경: user-stream ORDER_TRADE_UPDATE 미수신/지연 대비 우회 경로.
매 1분 Binance userTrades API → strategy.realized_pnl 자동 업데이트.

mainnet 첫날 사고 (2026-06-01): WebSocket /ws/ → /private/ws/ 마이그레이션
미인지로 ORDER 이벤트 수신 실패 → strategy.realized_pnl=0 머무름 → 통계 부정확.
근본 fix (WS endpoint) 후에도 안전망으로 작동.

매칭 규칙:
1. 각 active strategy 의 started_at (또는 created_at) 이후 trade 만 합산
2. realizedPnl - commission = net (DB 저장값)
3. STOPPED 또는 pos_qty=0 인 strategy 는 skip (안전망)
4. symbol 별로 묶어서 API 호출 최소화
"""
from __future__ import annotations
import hashlib
import hmac
import logging
import time
from decimal import Decimal

import requests
from sqlalchemy import select

from app.core.api_backoff import is_account_banned
from app.core.crypto import decrypt_text
from app.core.database import SessionLocal
from app.core.strategy_status import TERMINAL_STATUSES
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance

logger = logging.getLogger(__name__)

BASE_MAINNET = "https://fapi.binance.com"
BASE_TESTNET = "https://testnet.binancefuture.com"


def run_realized_pnl_sync_once() -> None:
    """매 1분 호출. 활성 strategy 의 realized_pnl 을 Binance userTrades 로 강제 동기화."""
    db = SessionLocal()
    try:
        accounts = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_active.is_(True))
        ).scalars().all()

        for account in accounts:
            if is_account_banned(account.id):
                continue

            strategies = db.execute(
                select(StrategyInstance)
                .where(StrategyInstance.exchange_account_id == account.id)
                .where(StrategyInstance.is_archived.is_(False))
                .where(StrategyInstance.status.notin_(TERMINAL_STATUSES))
            ).scalars().all()
            if not strategies:
                continue

            try:
                ak = decrypt_text(account.api_key_enc)
                sk = decrypt_text(account.api_secret_enc)
            except Exception as e:
                logger.warning("[realized-pnl-sync] decrypt fail acc=%s: %s", account.id, e)
                continue

            base = BASE_TESTNET if account.is_testnet else BASE_MAINNET

            # symbol 별로 묶음 (API 호출 최소화)
            by_symbol: dict[str, list[StrategyInstance]] = {}
            for s in strategies:
                by_symbol.setdefault(s.symbol, []).append(s)

            for symbol, syms_strategies in by_symbol.items():
                try:
                    ts = int(time.time() * 1000)
                    qs = f"symbol={symbol}&timestamp={ts}&recvWindow=5000&limit=100"
                    sig = hmac.new(sk.encode(), qs.encode(), hashlib.sha256).hexdigest()
                    r = requests.get(
                        f"{base}/fapi/v1/userTrades?{qs}&signature={sig}",
                        headers={"X-MBX-APIKEY": ak},
                        timeout=10,
                    )
                    if r.status_code != 200:
                        logger.warning(
                            "[realized-pnl-sync] %s status=%s body=%s",
                            symbol, r.status_code, r.text[:200],
                        )
                        continue
                    raw = r.json()
                    trades = raw if isinstance(raw, list) else []
                except Exception as e:
                    logger.warning("[realized-pnl-sync] api fail %s: %s", symbol, e)
                    continue

                for s in syms_strategies:
                    # pos_qty=0 인 strategy 는 skip (실 거래 없음 — #1 STOPPED 류 안전망)
                    if s.current_position_qty is None or abs(float(s.current_position_qty)) < 1e-12:
                        continue

                    # started_at 또는 created_at 기준으로 시간 필터 (같은 symbol 의 이전 strategy trade 제외)
                    cutoff_ts = s.started_at or s.created_at
                    if cutoff_ts:
                        cutoff_ms = int(cutoff_ts.timestamp() * 1000)
                    else:
                        cutoff_ms = 0

                    matching = [t for t in trades if t.get("time", 0) >= cutoff_ms]
                    if not matching:
                        continue

                    total_pnl = sum(Decimal(t.get("realizedPnl", "0")) for t in matching)
                    total_commission = sum(Decimal(t.get("commission", "0")) for t in matching)
                    net = total_pnl - total_commission

                    old = s.realized_pnl or Decimal("0")
                    if abs(old - net) > Decimal("0.00000001"):
                        s.realized_pnl = net
                        logger.info(
                            "[realized-pnl-sync] #%s %s realized: %s -> %s (fills=%d, commission=%s)",
                            s.id, s.symbol, old, net, len(matching), total_commission,
                        )

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    run_realized_pnl_sync_once()
    sys.exit(0)
