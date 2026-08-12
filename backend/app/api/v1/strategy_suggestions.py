"""🎯 Strategy Suggestions API! (v132 신 팀!)

사장님 요구 = 매일 자동 제안 → 수동/자동 실행!
기본 = 수동!

Endpoints:
  GET    /strategy-suggestions          = PENDING 리스트!
  DELETE /strategy-suggestions/{id}     = 삭제!
  POST   /strategy-suggestions/{id}/execute = 실행 (수동!)
  GET    /strategy-suggestions/settings = 자동 실행 세팅!
  PUT    /strategy-suggestions/settings = 세팅 저장!
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.models.strategy_suggestion import StrategySuggestion
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/strategy-suggestions", tags=["strategy-suggestions"])


# =====================================================================
# 스키마
# =====================================================================
class SuggestionResponse(BaseModel):
    id: int
    symbol: str
    side: str
    suggestion_type: str
    strategy_config: dict
    confidence_score: Decimal | None
    reason: str | None
    status: str
    execution_mode: str
    executed_at: datetime | None
    executed_strategy_id: int | None
    created_at: datetime  # ⭐ 만들어진 시간!


class SettingsResponse(BaseModel):
    auto_execute_enabled: bool = False
    confidence_threshold: str = "0.85"
    daily_auto_limit: str = "3"
    auto_dismiss_hours: str = "24"


class SettingsUpdate(BaseModel):
    auto_execute_enabled: bool = Field(default=False)
    confidence_threshold: str = Field(default="0.85")
    daily_auto_limit: str = Field(default="3")
    auto_dismiss_hours: str = Field(default="24")


class DismissRequest(BaseModel):
    reason: str | None = None


# =====================================================================
# API endpoints
# =====================================================================
@router.get("", response_model=list[SuggestionResponse])
def list_suggestions(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[SuggestionResponse]:
    """PENDING 제안 리스트 (최근 순!)"""
    _rows = db.execute(
        select(StrategySuggestion)
        .where(StrategySuggestion.status == "PENDING")
        .order_by(StrategySuggestion.created_at.desc())
        .limit(50)
    ).scalars().all()
    return [SuggestionResponse.model_validate(r, from_attributes=True) for r in _rows]


# 🚨 v132 CRITICAL fix (사장님 404 사고!):
# /settings = /{suggestion_id} 앞에 정의!
# FastAPI = 순서대로 매칭 = "settings" → "{suggestion_id}" (int 파싱 실패!) = 404!
# = specific routes must come BEFORE parametric routes!
@router.get("/settings", response_model=SettingsResponse)
def get_settings(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> SettingsResponse:
    """자동 실행 세팅 조회!"""
    _e = db.get(SystemSetting, "suggestion_auto_execute_enabled")
    _c = db.get(SystemSetting, "suggestion_confidence_threshold")
    _l = db.get(SystemSetting, "suggestion_daily_auto_limit")
    _d = db.get(SystemSetting, "suggestion_auto_dismiss_hours")
    return SettingsResponse(
        auto_execute_enabled=(_e.value.lower() == "true") if _e else False,
        confidence_threshold=_c.value if _c else "0.85",
        daily_auto_limit=_l.value if _l else "3",
        auto_dismiss_hours=_d.value if _d else "24",
    )


@router.put("/settings", response_model=SettingsResponse)
def update_settings(
    payload: SettingsUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> SettingsResponse:
    """자동 실행 세팅 저장!"""
    def _upsert(key: str, value: str, desc: str):
        row = db.get(SystemSetting, key)
        if row:
            row.value = value
        else:
            row = SystemSetting(key=key, value=value, description=desc)
            db.add(row)

    _upsert("suggestion_auto_execute_enabled",
            "true" if payload.auto_execute_enabled else "false",
            "전략 제안 자동 실행 (기본 OFF - 사장님 사상!)")
    _upsert("suggestion_confidence_threshold",
            str(payload.confidence_threshold),
            "자동 실행 최소 신뢰도")
    _upsert("suggestion_daily_auto_limit",
            str(payload.daily_auto_limit),
            "일일 자동 실행 한도")
    _upsert("suggestion_auto_dismiss_hours",
            str(payload.auto_dismiss_hours),
            "미실행 자동 삭제 시간")
    db.commit()
    return get_settings(db, user_id)


# 🌟 v132: 사장님 즉시 실행! (specific routes = /{id} 앞에!)
@router.post("/trigger-now")
def trigger_learning_now(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🎯 지금 즉시 학습 실행!"""
    try:
        from app.core.crypto import decrypt_text
        from app.agents.strategy_suggestion_team.team_lead import (
            StrategySuggestionTeamLead,
        )
        team_lead = StrategySuggestionTeamLead()
        result = team_lead.run_daily_prediction(db, decrypt_text)
        return {
            "triggered": True,
            "result": result,
            "note": "학습 완료! 대시보드 카드 새로고침!",
        }
    except Exception as e:
        logger.error("[trigger-now] 실패: %s", e)
        raise HTTPException(status_code=500, detail=f"학습 실행 실패: {e}")


@router.post("/briefing-now")
def briefing_now(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🌅 지금 즉시 브리핑!"""
    try:
        from app.agents.strategy_suggestion_team.team_lead import (
            StrategySuggestionTeamLead,
        )
        team_lead = StrategySuggestionTeamLead()
        result = team_lead.run_daily_briefing(db)
        return {
            "briefing_sent": True,
            "result": result,
            "note": "Telegram 확인!",
        }
    except Exception as e:
        logger.error("[briefing-now] 실패: %s", e)
        raise HTTPException(status_code=500, detail=f"브리핑 실패: {e}")


@router.delete("/{suggestion_id}")
def dismiss_suggestion(
    suggestion_id: int,
    payload: DismissRequest | None = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """제안 삭제 (사장님 「❌」 클릭!)."""
    _suggestion = db.get(StrategySuggestion, suggestion_id)
    if not _suggestion:
        raise HTTPException(status_code=404, detail="제안을 찾을 수 없음!")
    if _suggestion.status != "PENDING":
        raise HTTPException(
            status_code=400,
            detail=f"이미 처리된 제안입니다 (status={_suggestion.status})",
        )
    _suggestion.status = "DISMISSED"
    _suggestion.dismissed_at = datetime.now(timezone.utc)
    if payload and payload.reason:
        _suggestion.dismissed_reason = payload.reason
    db.commit()
    logger.info("[suggestion] #%s 삭제 완료 (사장님!)", suggestion_id)
    return {"dismissed": True, "suggestion_id": suggestion_id}


@router.post("/{suggestion_id}/execute")
def execute_suggestion(
    suggestion_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """제안 = 신 전략 실행! (수동 = 사장님 「▶」!)."""
    _suggestion = db.get(StrategySuggestion, suggestion_id)
    if not _suggestion:
        raise HTTPException(status_code=404, detail="제안을 찾을 수 없음!")
    if _suggestion.status != "PENDING":
        raise HTTPException(
            status_code=400,
            detail=f"이미 처리된 제안입니다 (status={_suggestion.status})",
        )

    # TODO: 실제 전략 생성 (다음 세션 - StrategyService.create_strategy_instance 호출!)
    # 지금 = 로그만 (검증 안 된 자동 실행 위험!)
    logger.warning(
        "[suggestion] #%s 실행 요청 = %s %s (MVP 상태 = 실 로직 미완성!)",
        suggestion_id, _suggestion.symbol, _suggestion.side,
    )

    _suggestion.status = "EXECUTED"
    _suggestion.executed_at = datetime.now(timezone.utc)
    # _suggestion.executed_strategy_id = 신_strategy.id  # TODO 실 구현!
    db.commit()

    return {
        "executed": True,
        "suggestion_id": suggestion_id,
        "symbol": _suggestion.symbol,
        "side": _suggestion.side,
        "note": "MVP 상태 - 실 전략 생성 = 다음 세션 완성!",
    }


# 🚨 v132 fix: /trigger-now, /briefing-now, /settings routes = 위로 이동!
# (specific routes MUST come BEFORE parametric routes!)
