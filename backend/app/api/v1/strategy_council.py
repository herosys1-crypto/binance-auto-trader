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
