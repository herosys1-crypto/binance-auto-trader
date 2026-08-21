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
    min_confidence: float = 0.75,   # 🌟 v172 사장님: 0.85 → 0.75 완화!
    exclude_active: bool = True,    # 🌟 v155 사장님: 활성 포지션 심볼 = 완전 숨기기!
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[SuggestionResponse]:
    """PENDING 제안 리스트 (75%+ + 활성 심볼 제외!)

    v155 사장님 지시 (2026-08-16):
    - 옛「85% 이상만 노출」 → v172 완화!
    - 「포지션에 진입해서 전략 인스턴스에 있으면 = 확실히 구분!」
      → exclude_active=True = 활성 포지션 심볼 = 완전 숨기기!

    🎯 v172 사장님 (2026-08-17):
    - 「신뢰도 85% 없을 수 없다!」 지적!
    - 원인: predictor 실제 conf 범위 = 0.65~0.95 (사장님 시장 20~30% 급등락 = 0.75~0.85!)
    - v135 confidence 조정 (0.5 배율!) = 신 심볼 자동 페널티 = 대부분 필터 탈락!
    - 신 로직: (v172 strategy_suggestion_generator.py)
      * 학습 <5건 = 원본 conf 그대로!
      * 학습 5건+ = 완화된 조정 (0.75 배율!)
    - 필터: 0.85 → 0.75 (사장님 볼 수 있게! 자동 진입은 여전히 사장님 승인!)

    신뢰도 = 성공 확률! 높을수록 = 확실한 예측!
    """
    q = (
        select(StrategySuggestion)
        .where(StrategySuggestion.status == "PENDING")
        .where(StrategySuggestion.confidence_score >= min_confidence)
    )

    # 🌟 v155 사장님: 활성 포지션 심볼 = 완전 제외!
    if exclude_active:
        from app.models.strategy_instance import StrategyInstance
        open_statuses = [
            "STAGE_1_OPEN", "STAGE_2_OPEN", "STAGE_3_OPEN",
            "STAGE_4_OPEN", "STAGE_5_OPEN", "STAGE_6_OPEN",
            "STAGE_7_OPEN", "STAGE_8_OPEN", "STAGE_9_OPEN",
            "STAGE_10_OPEN",
        ]
        active_symbols = db.execute(
            select(StrategyInstance.symbol)
            .where(StrategyInstance.status.in_(open_statuses))
            .where(StrategyInstance.current_position_qty != 0)
        ).scalars().all()
        active_set = set(active_symbols)
        if active_set:
            q = q.where(~StrategySuggestion.symbol.in_(active_set))

    _rows = db.execute(
        q.order_by(
            StrategySuggestion.confidence_score.desc(),
            StrategySuggestion.created_at.desc(),
        ).limit(50)
    ).scalars().all()
    return [SuggestionResponse.model_validate(r, from_attributes=True) for r in _rows]


def _auto_bb_reset_at(db: Session) -> datetime:
    """리셋 시각 = 사용자 리셋 (v163!) or 오늘 00:00 KST!

    🌟 v205 사장님 지적 (2026-08-21):
    "지금 진입중이고 성패가 나왔는데 여기는 0으로!"
    원인: UTC 자정 기준 = KST 아침 9시 = 사장님 관점 어제!
    Fix: KST 00:00 = UTC 15:00 (전날!) 기준!
    """
    row = db.get(SystemSetting, "auto_bb_break_reset_at")
    if row and row.value:
        try:
            return datetime.fromisoformat(row.value)
        except Exception:
            pass
    # 🌟 v205: KST 자정 기준!
    from datetime import timedelta as _td
    now_utc = datetime.now(timezone.utc)
    now_kst = now_utc + _td(hours=9)
    kst_today_naive = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    # KST 자정 → UTC 변환!
    return (kst_today_naive - _td(hours=9)).replace(tzinfo=timezone.utc)


def _count_auto_bb_used(db: Session) -> dict:
    """🎯 v163 사장님: 자동 진입 카운트!
    - 포함: 활성 + 손절!
    - 제외: 익절! (성공 = 재도전 가능!)
    """
    from app.models.strategy_instance import StrategyInstance
    reset_at = _auto_bb_reset_at(db)
    suggestions = db.execute(
        select(StrategySuggestion)
        .where(StrategySuggestion.execution_mode == "AUTO")
        .where(StrategySuggestion.executed_at >= reset_at)
    ).scalars().all()

    active = 0
    stopped_loss = 0     # 손절 = 카운트!
    stopped_profit = 0   # 익절 = 카운트 X!
    for s in suggestions:
        if not s.executed_strategy_id:
            continue
        strategy = db.get(StrategyInstance, s.executed_strategy_id)
        if not strategy:
            continue
        # 활성 상태!
        open_statuses = [
            "STAGE_1_OPEN", "STAGE_2_OPEN", "STAGE_3_OPEN",
            "STAGE_4_OPEN", "STAGE_5_OPEN", "STAGE_6_OPEN",
            "STAGE_7_OPEN", "STAGE_8_OPEN", "STAGE_9_OPEN",
            "STAGE_10_OPEN",
        ]
        if strategy.status in open_statuses:
            active += 1
            continue
        # 종료 = realized_pnl 기준으로 판정!
        # 익절 = realized_pnl > 0 = 카운트 X!
        # 손절 = realized_pnl <= 0 = 카운트!
        realized = float(strategy.realized_pnl or 0)
        if realized > 0:
            stopped_profit += 1  # 스킵!
        else:
            stopped_loss += 1    # 카운트!

    daily_used = active + stopped_loss
    return {
        "daily_used": daily_used,
        "active": active,
        "stopped_loss": stopped_loss,
        "stopped_profit": stopped_profit,  # 정보용 (카운트 X!)
        "reset_at": reset_at.isoformat(),
    }


@router.get("/auto-bb-limit")
def get_auto_bb_limit(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🌟 v162 사장님: BB 이탈 SUSTAINED 자동 진입 하루 개수 조회!
    v163: 사용 상태 (활성/손절/익절!)도 반환!
    """
    row = db.get(SystemSetting, "auto_bb_break_daily_limit")
    limit = int(row.value) if row and row.value else 0
    usage = _count_auto_bb_used(db)
    return {
        "limit": limit,
        **usage,
        "remaining": max(0, limit - usage["daily_used"]),
    }


@router.put("/auto-bb-limit")
def set_auto_bb_limit(
    payload: dict,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🌟 v162 사장님: BB 이탈 SUSTAINED 자동 진입 하루 개수 저장!
    0 = OFF (수동!), 1~10 = 하루 최대 개수!
    """
    limit = int(payload.get("limit", 0))
    # 🎯 v190 사장님: 「많이!」 = 최대 30!
    if limit < 0 or limit > 30:
        raise HTTPException(status_code=400, detail="0~30만 허용!")
    row = db.get(SystemSetting, "auto_bb_break_daily_limit")
    if row:
        row.value = str(limit)
    else:
        db.add(SystemSetting(
            key="auto_bb_break_daily_limit",
            value=str(limit),
            description="v162 사장님: BB 이탈 SUSTAINED 자동 진입 하루 최대 개수 (0=OFF)",
        ))
    db.commit()
    return {"limit": limit, "note": "0=수동, 1~10=하루 자동 개수!"}


@router.post("/auto-bb-reset")
def reset_auto_bb_counter(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🔄 v163 사장님: 자동 진입 카운터 리셋!
    - 지금 시각 = 신 reset_at!
    - 이후 진입 = 새로 카운트!
    - 이전 활성/손절 = 리셋 이전 = 카운트 X!
    """
    now = datetime.now(timezone.utc)
    row = db.get(SystemSetting, "auto_bb_break_reset_at")
    if row:
        row.value = now.isoformat()
    else:
        db.add(SystemSetting(
            key="auto_bb_break_reset_at",
            value=now.isoformat(),
            description="v163 사장님: 자동 진입 카운터 리셋 시각!",
        ))
    db.commit()
    return {
        "reset_at": now.isoformat(),
        "note": "카운터 리셋 완료! 지금 이후 자동 진입만 = 카운트!",
    }


@router.post("/dismiss-low-confidence")
def dismiss_low_confidence(
    threshold: float = 0.85,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🚨 v155 사장님 지시: 「초기화해서 다시 해줘」
    = 85% 미만 = 모두 DISMISSED 처리!
    """
    from sqlalchemy import update
    result = db.execute(
        update(StrategySuggestion)
        .where(StrategySuggestion.status == "PENDING")
        .where(StrategySuggestion.confidence_score < threshold)
        .values(
            status="DISMISSED",
            dismissed_at=datetime.now(timezone.utc),
            dismissed_reason=f"v155 사장님 지시 = 신뢰도 <{threshold*100:.0f}% 초기화!",
        )
    )
    db.commit()
    return {
        "dismissed": result.rowcount,
        "threshold": threshold,
        "note": f"신뢰도 <{threshold*100:.0f}% 제안 {result.rowcount}건 = DISMISSED!",
    }


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
    force: bool = False,  # 🌟 v132: 오늘 PENDING = 자동 dismiss 후 재생성!
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🎯 지금 즉시 학습 실행!

    Args:
        force: True = 오늘 이미 있는 PENDING 제안 = 자동 삭제 후 재생성!
               (LONG 예측 다시 하고 싶을 때!)
    """
    try:
        from app.core.crypto import decrypt_text
        from app.agents.strategy_suggestion_team.team_lead import (
            StrategySuggestionTeamLead,
        )
        team_lead = StrategySuggestionTeamLead()
        result = team_lead.run_daily_prediction(db, decrypt_text, force=force)
        return {
            "triggered": True,
            "force": force,
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
