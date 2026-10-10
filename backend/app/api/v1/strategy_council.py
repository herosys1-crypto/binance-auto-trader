"""🧑‍⚖️ Fix 430 — 전략 운영팀 성적표 조회 (화면 카드용, 읽기 전용).

  GET /strategy-council/latest → strategy_council.build_report 결과 + at (워커가 하루 1회 Redis council:latest 에 쓴다)
  비었거나 없으면 {"empty": true}.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/strategy-council", tags=["strategy-council"])
LATEST_KEY = "council:latest"


@router.get("/latest")
def strategy_council_latest(user_id: int = Depends(get_current_user_id)) -> dict:
    try:
        from app.core.redis_client import get_redis_client
        raw = get_redis_client().get(LATEST_KEY)
        if not raw:
            return {"empty": True}
        data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        return data if isinstance(data, dict) else {"empty": True}
    except Exception as e:  # noqa: BLE001 — 화면이 죽지 않게
        logger.warning("[Fix430] 성적표 조회 실패: %s", e)
        return {"empty": True, "error": "조회 실패"}


LIVE_KEY = "council:live_families"
LIVE_TTL = 300          # 5분 캐시 — 화면 폴링이 DB 를 두드리지 않게 (Fix 386 교훈)


@router.get("/live-families")
def strategy_council_live(user_id: int = Depends(get_current_user_id)) -> dict:
    """🧑‍⚖️ Fix 436: 가족별 실거래(시스템 몫 · 사람 💉 추가 몫 · 7일 · 손실 차단기). 읽기 전용, 5분 캐시."""
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        raw = r.get(LIVE_KEY)
        if raw:
            return json.loads(raw.decode() if isinstance(raw, bytes) else raw)
    except Exception as e:  # noqa: BLE001
        logger.debug("[Fix436] 캐시 읽기 실패: %s", e)
        r = None
    from app.core.database import SessionLocal
    from app.services import live_family_board as LB
    db = SessionLocal()
    try:
        data = LB.build(db)
    except Exception as e:  # noqa: BLE001 — 화면이 죽지 않게
        logger.warning("[Fix436] 가족별 실거래 계산 실패: %s", e)
        return {"families": [], "error": "계산 실패"}
    finally:
        db.close()
    try:
        # 교차 감사: 차단기 조회가 실패한 결과는 캐시하지 않는다 — 막힌 가족의 ⛔ 가 5분 동안 「—」로 보이지 않게
        if r is not None and data.get("breaker_ok", True):
            r.setex(LIVE_KEY, LIVE_TTL, json.dumps(data, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001
        pass
    return data
