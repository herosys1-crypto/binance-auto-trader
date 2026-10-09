"""🗓 Fix 424 — EMA 추세 눌림 「진입 준비」·「진입 신호」 보드 (화면 카드용, 읽기 전용).

  GET /ema-pullback/board → {"at", "interval", "near_pct", "items": [{kind: ready|signal, symbol, side, price, ema20, stop, ...}]}
  값은 emapb_watch 워커(15분)가 Redis 에 쓴다. 비었거나 없으면 items = [].
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ema-pullback", tags=["ema-pullback"])
BOARD_KEY = "emapb:board"


@router.get("/board")
def ema_pullback_board(user_id: int = Depends(get_current_user_id)) -> dict:
    try:
        from app.core.redis_client import get_redis_client
        raw = get_redis_client().get(BOARD_KEY)
        if not raw:
            return {"items": []}
        data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        return data if isinstance(data, dict) else {"items": []}
    except Exception as e:  # noqa: BLE001 — 화면이 죽지 않게
        logger.warning("[Fix424] 보드 조회 실패: %s", e)
        return {"items": [], "error": "조회 실패"}
