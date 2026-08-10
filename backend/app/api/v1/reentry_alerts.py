"""신 재진입 알람 API (v130 → v131!)

사장님 요청 (v130): 알람 지우거나 = 선택해서 = 신 전략 즉시 생성!
사장님 요청 (v131 2026-08-09):
  - 자동 실행 옵션 = 알람 감지 시 자동 신 전략 생성
  - 수동 관리자 승인 = 알람만 표시, 사장님 클릭!
  - 손절가 옵션 확장 (0~100)

Endpoints:
  GET  /reentry-alerts               = 활성 알람 리스트
  DELETE /reentry-alerts/{id}        = 알람 개별 삭제
  GET  /reentry-alerts/settings      = 자동 실행 세팅 조회 (v131!)
  PUT  /reentry-alerts/settings      = 자동 실행 세팅 저장 (v131!)
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.risk_constants import FORCE_SL_ALLOWED_ROI
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reentry-alerts", tags=["reentry-alerts"])

REDIS_KEY_ALERTS = "reentry_alerts:v1"

# 🌟 v131 자동 실행 설정 keys (system_settings 테이블!)
KEY_AUTO_EXECUTE_ENABLED = "reentry_auto_execute_enabled"
KEY_AUTO_EXECUTE_CAPITAL = "reentry_auto_execute_capital"
KEY_AUTO_EXECUTE_FORCE_SL_ROI = "reentry_auto_execute_force_sl_roi"
KEY_AUTO_EXECUTE_LEVERAGE = "reentry_auto_execute_leverage"

# 기본값 (사장님 신 default)
DEFAULT_AUTO_EXECUTE_ENABLED = False  # OFF = 수동 승인 (기존!)
DEFAULT_AUTO_EXECUTE_CAPITAL = "100"  # 100 USDT (소액!)
DEFAULT_AUTO_EXECUTE_FORCE_SL_ROI = "15"  # -15%
DEFAULT_AUTO_EXECUTE_LEVERAGE = "2"  # 2x


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


# =====================================================================
# 🌟 v131 자동 실행 세팅 API (사장님 요청 2026-08-09!)
# =====================================================================
class ReentrySettingsResponse(BaseModel):
    auto_execute_enabled: bool = False
    auto_execute_capital: str = "100"
    auto_execute_force_sl_roi: str = "15"
    auto_execute_leverage: str = "2"
    allowed_force_sl_roi: list[str] = []
    allowed_leverage: list[int] = []


class ReentrySettingsUpdate(BaseModel):
    auto_execute_enabled: bool = Field(default=False)
    auto_execute_capital: str = Field(default="100")
    auto_execute_force_sl_roi: str = Field(default="15")
    auto_execute_leverage: str = Field(default="2")


def _get_setting(db: Session, key: str, default: str) -> str:
    """SystemSetting에서 값 조회 (없으면 default)."""
    row = db.get(SystemSetting, key)
    return row.value if row and row.value is not None else default


def _set_setting(db: Session, key: str, value: str, user_id: int, description: str) -> None:
    """SystemSetting 저장 (upsert)."""
    row = db.get(SystemSetting, key)
    if row:
        row.value = value
        row.updated_by = user_id
        row.description = description
    else:
        row = SystemSetting(key=key, value=value, updated_by=user_id, description=description)
        db.add(row)


@router.get("/settings", response_model=ReentrySettingsResponse)
def get_reentry_settings(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> ReentrySettingsResponse:
    """자동 실행 세팅 조회 (v131 신!)."""
    enabled_str = _get_setting(db, KEY_AUTO_EXECUTE_ENABLED, "false")
    capital_str = _get_setting(db, KEY_AUTO_EXECUTE_CAPITAL, DEFAULT_AUTO_EXECUTE_CAPITAL)
    force_sl_str = _get_setting(db, KEY_AUTO_EXECUTE_FORCE_SL_ROI, DEFAULT_AUTO_EXECUTE_FORCE_SL_ROI)
    leverage_str = _get_setting(db, KEY_AUTO_EXECUTE_LEVERAGE, DEFAULT_AUTO_EXECUTE_LEVERAGE)
    return ReentrySettingsResponse(
        auto_execute_enabled=(enabled_str.lower() == "true"),
        auto_execute_capital=capital_str,
        auto_execute_force_sl_roi=force_sl_str,
        auto_execute_leverage=leverage_str,
        allowed_force_sl_roi=[str(x) for x in FORCE_SL_ALLOWED_ROI],
        allowed_leverage=[1, 2, 3, 5, 10, 20, 50, 75, 100, 125],
    )


@router.put("/settings", response_model=ReentrySettingsResponse)
def update_reentry_settings(
    payload: ReentrySettingsUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> ReentrySettingsResponse:
    """자동 실행 세팅 저장 (v131 신!)."""
    # 검증 = force_sl_roi 는 허용 리스트 값만!
    try:
        _sl_val = Decimal(str(payload.auto_execute_force_sl_roi))
        if _sl_val not in FORCE_SL_ALLOWED_ROI:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"강제 SL ROI는 다음 값만 허용: {[str(x) for x in FORCE_SL_ALLOWED_ROI]}"
            )
    except InvalidOperation:
        raise HTTPException(status_code=400, detail="강제 SL ROI = 숫자!")

    # 검증 = capital 은 양수
    try:
        _cap_val = Decimal(str(payload.auto_execute_capital))
        if _cap_val <= 0:
            raise HTTPException(status_code=400, detail="자본 = 양수!")
    except InvalidOperation:
        raise HTTPException(status_code=400, detail="자본 = 숫자!")

    # 검증 = leverage 는 1~125
    try:
        _lev = int(payload.auto_execute_leverage)
        if _lev < 1 or _lev > 125:
            raise HTTPException(status_code=400, detail="레버리지 = 1~125!")
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="레버리지 = 정수!")

    _set_setting(db, KEY_AUTO_EXECUTE_ENABLED,
                 "true" if payload.auto_execute_enabled else "false",
                 user_id, "재진입 알람 자동 실행 ON/OFF")
    _set_setting(db, KEY_AUTO_EXECUTE_CAPITAL,
                 str(payload.auto_execute_capital),
                 user_id, "자동 실행 자본 (USDT)")
    _set_setting(db, KEY_AUTO_EXECUTE_FORCE_SL_ROI,
                 str(payload.auto_execute_force_sl_roi),
                 user_id, "자동 실행 강제 SL ROI (%)")
    _set_setting(db, KEY_AUTO_EXECUTE_LEVERAGE,
                 str(payload.auto_execute_leverage),
                 user_id, "자동 실행 레버리지 (x)")
    db.commit()

    return get_reentry_settings(db, user_id)
