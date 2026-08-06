"""신 재진입 알람 API (v130!)

사장님 요청: 알람 지우거나 = 선택해서 = 신 전략 즉시 생성!

Endpoints:
  GET  /reentry-alerts       = 활성 알람 리스트
  DELETE /reentry-alerts/{id} = 알람 개별 삭제
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reentry-alerts", tags=["reentry-alerts"])

REDIS_KEY_ALERTS = "reentry_alerts:v1"


@router.get("")
def list_reentry_alerts(user_id: int = Depends(get_current_user_id)) -> list[dict]:
    """활성 재진입 알람 리스트 (최근 24h)."""
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        if not r:
            return []
        # Sorted set에서 최근 순 (score desc)
        alert_keys = r.zrevrange(REDIS_KEY_ALERTS, 0, 100)
        out: list[dict] = []
        for key in alert_keys:
            if isinstance(key, bytes):
                key = key.decode("utf-8")
            data = r.get(key)
            if not data:
                # 만료된 알람 = sorted set에서 제거
                r.zrem(REDIS_KEY_ALERTS, key)
                continue
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            try:
                alert = json.loads(data)
                alert["_key"] = key  # frontend가 삭제 시 필요
                out.append(alert)
            except Exception as e:
                logger.warning("[reentry_alerts] parse 실패: %s", e)
        return out
    except Exception as e:
        logger.warning("[reentry_alerts] list 실패: %s", e)
        return []


@router.delete("/{alert_key}")
def delete_reentry_alert(
    alert_key: str,
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """알람 개별 삭제 (사장님 무시!)."""
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        if not r:
            return {"deleted": False, "reason": "redis unavailable"}
        # key 검증 = "reentry_alert:" prefix만
        if not alert_key.startswith("reentry_alert:"):
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
        logger.warning("[reentry_alerts] delete 실패: %s", e)
        return {"deleted": False, "reason": str(e)}
