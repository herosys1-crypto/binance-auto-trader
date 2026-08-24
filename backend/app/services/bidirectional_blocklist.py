"""Fix 66 P1: 양방향 실패 심볼 blocklist (7일!)

사장님 사상:
- 최근 7일 = LONG 실패 + SHORT 실패 = 양방향 예측 불가!
- = 심볼 전체 blocklist!
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.strategy_status import TERMINAL_STATUSES
from app.models.strategy_instance import StrategyInstance

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 7  # 7일!
_CACHE = {"symbols": set(), "computed_at": None}
CACHE_TTL_SEC = 300  # 5분!


def _compute_bidirectional_blocklist(db: Session) -> set:
    """최근 7일 양방향 실패 심볼 조회!"""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
        rows = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.status.in_(TERMINAL_STATUSES))
            .where(StrategyInstance.stopped_at >= cutoff)
        ).scalars().all()

        # 심볼별 SHORT/LONG 실패 카운트
        stats = {}
        for r in rows:
            if not r.realized_pnl or float(r.realized_pnl) >= 0:
                continue
            key = r.symbol
            if key not in stats:
                stats[key] = {"SHORT": 0, "LONG": 0}
            if r.side in ("SHORT", "LONG"):
                stats[key][r.side] += 1

        # 양방향 = SHORT + LONG 모두 실패!
        bidirectional = set()
        for symbol, counts in stats.items():
            if counts["SHORT"] >= 1 and counts["LONG"] >= 1:
                bidirectional.add(symbol)

        return bidirectional
    except Exception as e:
        logger.warning("[Fix66/blocklist] compute error: %s", e)
        return set()


def is_bidirectional_blocked(db: Session, symbol: str) -> tuple:
    """양방향 실패 심볼 확인!
    Returns: (blocked, reason)
    """
    try:
        now = datetime.now(timezone.utc)

        # 캐시 확인
        if _CACHE["computed_at"] is None or (now - _CACHE["computed_at"]).total_seconds() > CACHE_TTL_SEC:
            _CACHE["symbols"] = _compute_bidirectional_blocklist(db)
            _CACHE["computed_at"] = now

        if symbol in _CACHE["symbols"]:
            reason = f"양방향 실패 blocklist: {symbol} (7일 내 LONG+SHORT 모두 실패!)"
            logger.info("[Fix66/blocklist] %s", reason)
            return (True, reason)
        return (False, "not_blocked")
    except Exception as e:
        logger.warning("[Fix66/blocklist] check error: %s", e)
        return (False, "error_pass")  # fail-open
