"""Fix 66 P1: 양방향 실패 심볼 blocklist (7일!)

사장님 사상 (원래):
- 최근 7일 = LONG 실패 + SHORT 실패 = 양방향 예측 불가!
- = 심볼 전체 blocklist!

🚨 Fix 71 (2026-08-25 사장님 verbatim!):
    "제한 심볼들 모두 해제해줘 제한 심볼을 만들지 않도록해"
    → 모든 심볼 이름 기반 blocklist = 완전 해제!
    → 함수는 유지 (호환성!) but 항상 (False, "disabled_by_sajangnim") 반환!
    → _compute_bidirectional_blocklist = 항상 빈 set 반환 (계산/저장 X!)
"""
from __future__ import annotations
import logging
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# 🚨 Fix 71: 사장님 지시 = 제한 심볼 완전 해제 + 앞으로도 만들지 않음!
# LOOKBACK_DAYS / _CACHE / CACHE_TTL_SEC = 사용 안 함 (호환성 위해 남겨둠)
LOOKBACK_DAYS = 7  # deprecated (Fix 71: 사용 안 함)
_CACHE = {"symbols": set(), "computed_at": None}  # deprecated (Fix 71: 항상 빈 set)
CACHE_TTL_SEC = 300  # deprecated


def _compute_bidirectional_blocklist(db: Session) -> set:
    """🚨 Fix 71 (2026-08-25 사장님 verbatim!):
    "제한 심볼들 모두 해제해줘 제한 심볼을 만들지 않도록해"
    → 심볼 blocklist = 만들지 않음! = 항상 빈 set!
    """
    # DB 조회 X, 계산 X, 저장 X = 완전 fail-open!
    return set()


def is_bidirectional_blocked(db: Session, symbol: str) -> tuple:
    """양방향 실패 심볼 확인!

    🚨 Fix 71 (2026-08-25 사장님 verbatim!):
    "제한 심볼들 모두 해제해줘 제한 심볼을 만들지 않도록해"
    → 모든 심볼 = 항상 pass! = (False, "disabled_by_sajangnim_2026-08-25")

    Returns: (blocked, reason)
    - blocked = 항상 False!
    - reason = "disabled_by_sajangnim_2026-08-25"
    """
    logger.debug("[Fix71] blocklist disabled by 사장님 verbatim: %s", symbol)
    return (False, "disabled_by_sajangnim_2026-08-25")
