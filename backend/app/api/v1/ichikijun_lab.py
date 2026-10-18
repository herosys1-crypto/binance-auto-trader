"""🗾 Fix 465 — 일목 기준선 변형 실험실 순위표·챔피언 (화면 카드용, 읽기 전용).

  GET /ichikijun-lab/board → {"at", "since", "champion", "streak", "board": [{variant, side, n, days, win, avg_r, rand_r, edge, low95, score, ...}]}
  값은 ichikijun_board 잡(매일 KST 10:30)이 Redis 에 쓴다. 없으면 board = [].
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ichikijun-lab", tags=["ichikijun-lab"])
BOARD_KEY = "ichilab:board"


@router.get("/board")
def ichikijun_lab_board(user_id: int = Depends(get_current_user_id)) -> dict:
    try:
        from app.core.redis_client import get_redis_client
        raw = get_redis_client().get(BOARD_KEY)
        if not raw:
            return {"board": [], "champion": None}
        data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        return data if isinstance(data, dict) else {"board": [], "champion": None}
    except Exception as e:  # noqa: BLE001 — 화면이 죽지 않게
        logger.warning("[Fix465] 순위표 조회 실패: %s", e)
        return {"board": [], "champion": None, "error": "조회 실패"}
