"""Mark price 실시간 캐시 — Redis 기반.

WebSocket markPrice 스트림 consumer 가 주기적으로 갱신 (sub-second),
API/worker 는 read-only 로 사용해 unrealized_pnl 계산에 활용한다.

기존 흐름의 문제:
- reconcile_worker 가 2분 주기로 Position.mark_price 갱신 → 최대 2분 stale
- ACCOUNT_UPDATE 이벤트는 포지션 변동 시점에만 강제 발생 → 그 사이 정지
- 결과: UI 의 PNL/마크가가 Binance 실시간과 5~13 USDT 차이 (UBUSDT 실측)

본 캐시:
- WebSocket <symbol>@markPrice@1s 가 1초마다 push
- Redis TTL 60s — 스트림 끊김 감지용 (만료 시 fallback to DB snapshot)
- mget 으로 N 심볼 한 번에 조회 → API N+1 회피
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Iterable

from app.core.redis_client import get_redis_client

logger = logging.getLogger(__name__)

# Redis key prefix — 심볼별 mark price
KEY_PREFIX = "mark_price:"

# TTL — 스트림 끊김 감지용. 60s 안에 갱신 안 되면 cache miss 처리됨.
# 너무 짧으면 정상 운영 중에도 miss, 너무 길면 stale data 사용 위험.
TTL_SECONDS = 60


def _key(symbol: str) -> str:
    return f"{KEY_PREFIX}{symbol.upper()}"


def set_mark_price(symbol: str, price: Decimal | float | str) -> None:
    """캐시 갱신 — WebSocket consumer 가 호출.

    Redis 실패는 silent. 스트림 자체가 멈추지 않는 게 중요하므로 예외 무시.
    """
    try:
        get_redis_client().setex(_key(symbol), TTL_SECONDS, str(price))
    except Exception as e:
        # 너무 자주 로그 남기면 noise — debug 레벨로만
        logger.debug("mark_price 캐시 set 실패 %s: %s", symbol, e)


def get_mark_price(symbol: str) -> Decimal | None:
    """단일 심볼 캐시 조회. miss → None (호출자가 fallback 처리)."""
    try:
        val = get_redis_client().get(_key(symbol))
        if not val:
            return None
        return Decimal(str(val))
    except (Exception, InvalidOperation):
        return None


def get_mark_prices_bulk(symbols: Iterable[str]) -> dict[str, Decimal]:
    """여러 심볼 한 번에 조회 — API 응답 N+1 방지.

    반환 dict 의 key 는 upper-case 심볼. 없는 심볼은 dict 에 포함 안 됨.
    """
    syms = list({s.upper() for s in symbols if s})
    if not syms:
        return {}
    try:
        client = get_redis_client()
        keys = [_key(s) for s in syms]
        values = client.mget(keys)
        result: dict[str, Decimal] = {}
        for s, v in zip(syms, values, strict=True):
            if v is None:
                continue
            try:
                result[s] = Decimal(str(v))
            except (Exception, InvalidOperation):
                continue
        return result
    except Exception as e:
        logger.debug("mark_price 캐시 mget 실패: %s", e)
        return {}


def calc_unrealized_pnl(
    side: str,
    qty: Decimal,
    entry_price: Decimal,
    mark_price: Decimal,
) -> Decimal:
    """unrealized PNL 재계산 — 라이브 마크 가격 기준.

    LONG:  qty × (mark - entry)
    SHORT: qty × (entry - mark)

    qty 는 양수로 가정 (방향은 side 로 판단). entry_price 0/None 이면 0 반환.
    """
    if not entry_price or entry_price <= 0 or not mark_price or mark_price <= 0:
        return Decimal("0")
    if (side or "").upper() == "SHORT":
        return qty * (entry_price - mark_price)
    return qty * (mark_price - entry_price)
