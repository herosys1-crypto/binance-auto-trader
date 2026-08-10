"""신 급등+BB중단 알람 API! (v131 사장님!)

사장님 요청: 급등 top 50 + 4H 최고점 = BB중단 ±5% = 알람!

Endpoints:
  GET  /pump-bb-alerts       = 활성 알람 리스트 (최근 6h!)
  DELETE /pump-bb-alerts/{id} = 개별 삭제
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pump-bb-alerts", tags=["pump-bb-alerts"])

REDIS_KEY_ALERTS = "pump_bb_alerts:v1"


@router.get("")
def list_pump_bb_alerts(user_id: int = Depends(get_current_user_id)) -> list[dict]:
    """활성 급등+BB중단 알람 리스트 (최근 6h)."""
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        if not r:
            return []
        alert_keys = r.zrevrange(REDIS_KEY_ALERTS, 0, 100)
        out: list[dict] = []
        for key in alert_keys:
            if isinstance(key, bytes):
                key = key.decode("utf-8")
            data = r.get(key)
            if not data:
                # 만료 = sorted set에서 제거
                r.zrem(REDIS_KEY_ALERTS, key)
                continue
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            try:
                alert = json.loads(data)
                alert["_key"] = key
                out.append(alert)
            except Exception as e:
                logger.warning("[pump_bb_alerts] parse 실패: %s", e)
        return out
    except Exception as e:
        logger.warning("[pump_bb_alerts] list 실패: %s", e)
        return []


@router.delete("/{alert_key}")
def delete_pump_bb_alert(
    alert_key: str,
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """알람 개별 삭제 (사장님 무시!)."""
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        if not r:
            return {"deleted": False, "reason": "redis unavailable"}
        if not alert_key.startswith("pump_bb_alert:"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="잘못된 alert_key"
            )
        r.delete(alert_key)
        r.zrem(REDIS_KEY_ALERTS, alert_key)
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("[pump_bb_alerts] delete 실패: %s", e)
        return {"deleted": False, "reason": str(e)}
