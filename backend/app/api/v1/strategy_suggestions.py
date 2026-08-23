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
from sqlalchemy import func, select
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
        # 🚨 v218 CRITICAL fix (2026-08-22 사장님 지적!):
        # 실제 status = "STAGE1_OPEN" (언더스코어 X!) but 코드 = "STAGE_1_OPEN" (오타!)
        # = 활성 5건 (HOODUSDT/BTWUSDT/MUUSDT/WLDUSDT/SKHYUSDT) 인식 실패!
        # 사장님 UI = "활성 0" 오분류!
        # 신: ACTIVE_LIKE 재사용 = 단일 진실 (헌법 6!) = STAGE_PENDING/LIQUIDATED_WAITING_RETRY 포함!
        from app.core.strategy_status import ACTIVE_LIKE
        open_statuses = list(ACTIVE_LIKE)
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

    🎯 v219 통합 fix (2026-08-22 사장님!):
    사장님 요구: "일 진입수는 급등락 실시간과 같이 세팅"
    UI 카운트 = Worker _count_used_slots와 통일 (헌법 6 단일 진실!)
    suggestion_type 필터 = ["bb4h_auto_entry", "sajangnim_top_short"] 통합!
    """
    from app.models.strategy_instance import StrategyInstance
    reset_at = _auto_bb_reset_at(db)
    _auto_types = ["bb4h_auto_entry", "sajangnim_top_short"]
    suggestions = db.execute(
        select(StrategySuggestion)
        .where(StrategySuggestion.execution_mode == "AUTO")
        .where(StrategySuggestion.suggestion_type.in_(_auto_types))
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
        # 🚨 v218 CRITICAL fix (2026-08-22 사장님 지적!):
        # 실제 status = "STAGE1_OPEN" (언더스코어 X!) but 코드 = "STAGE_1_OPEN" (오타!)
        # = 활성 5건 (HOODUSDT/BTWUSDT/MUUSDT/WLDUSDT/SKHYUSDT) 인식 실패!
        # 사장님 UI = "활성 0" 오분류!
        # 신: ACTIVE_LIKE 재사용 = 단일 진실 (헌법 6!) = STAGE_PENDING/LIQUIDATED_WAITING_RETRY 포함!
        from app.core.strategy_status import ACTIVE_LIKE
        open_statuses = list(ACTIVE_LIKE)
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


@router.get("/sajangnim-settings")
def get_sajangnim_settings(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🎯 v219 (2026-08-22 사장님!): 사장님 실 성공 로직 세팅 조회!

    사장님 verbatim: "지금 300usdt로 변경해주고 운영하면서 초기값을 조정할수 있게 만들어줘"
    """
    default_cap_row = db.get(SystemSetting, "sajangnim_default_capital")
    mode_row = db.get(SystemSetting, "sajangnim_capital_mode")
    pct_row = db.get(SystemSetting, "sajangnim_entry_pct")
    daily_limit_row = db.get(SystemSetting, "sajangnim_daily_limit")
    # 🎯 v219+ (2026-08-23 사장님!): 마틴게일 최대 단계 상한!
    # 사장님 verbatim: "3단계까지 갈수 있다야 가능하면 가지않는 관리가 필요"
    # 1 = 재진입 X (1단계에서 종료) / 2 = 1→2단계까지 (사장님 추천!) / 3 = 1→2→3단계까지 (매우 신중!)
    max_stage_row = db.get(SystemSetting, "sajangnim_max_stage")
    # 🎯 v219 (2026-08-23 사장님!): 7중 정점 SHORT 일일 한도 (auto_short_at_top 워커!)
    # 0 = 자동 SHORT 비활성 / 30 = 최대 (auto_bb_break_daily_limit 와 공유 슬롯!)
    top_short_daily_limit_row = db.get(SystemSetting, "sajangnim_top_short_daily_limit")

    return {
        "default_capital": float(default_cap_row.value) if default_cap_row and default_cap_row.value else 300.0,
        "capital_mode": (mode_row.value if mode_row and mode_row.value else "fixed"),
        "entry_pct": float(pct_row.value) if pct_row and pct_row.value else 0.01,
        "daily_limit": int(daily_limit_row.value) if daily_limit_row and daily_limit_row.value else 1,
        "max_stage": int(max_stage_row.value) if max_stage_row and max_stage_row.value else 2,
        "top_short_daily_limit": int(top_short_daily_limit_row.value) if top_short_daily_limit_row and top_short_daily_limit_row.value else 0,
    }


@router.put("/sajangnim-settings")
def set_sajangnim_settings(
    payload: dict,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🎯 v219: 사장님 실 성공 로직 세팅 저장!"""
    fields = {
        "sajangnim_default_capital": ("default_capital", lambda v: str(max(50.0, min(100000.0, float(v))))),
        "sajangnim_capital_mode": ("capital_mode", lambda v: str(v).lower() if str(v).lower() in ("fixed", "percent") else "fixed"),
        "sajangnim_entry_pct": ("entry_pct", lambda v: str(max(0.001, min(0.02, float(v))))),
        "sajangnim_daily_limit": ("daily_limit", lambda v: str(max(0, min(10, int(v))))),
        # 🎯 v219+ (2026-08-23 사장님!): 마틴게일 최대 단계 = 1~3 clamp!
        "sajangnim_max_stage": ("max_stage", lambda v: str(max(1, min(3, int(v))))),
        # 🎯 v219 (2026-08-23 사장님!): 7중 정점 SHORT 일일 한도 = 0~30 clamp!
        "sajangnim_top_short_daily_limit": ("top_short_daily_limit", lambda v: str(max(0, min(30, int(v))))),
    }
    updated = {}
    for key, (payload_key, sanitizer) in fields.items():
        if payload_key not in payload:
            continue
        try:
            new_val = sanitizer(payload[payload_key])
            row = db.get(SystemSetting, key)
            if row:
                row.value = new_val
            else:
                row = SystemSetting(key=key, value=new_val)
                db.add(row)
            updated[payload_key] = new_val
        except Exception as e:
            return {"error": f"{payload_key}: {e}"}
    db.commit()
    return {"updated": updated, "ok": True}


@router.get("/recent-auto")
def recent_auto_outcomes(
    hours: int = 24,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🎯 v218 사장님 (2026-08-22): 자동 제안 = 활성/손절/익절 표시!

    사장님 verbatim: "자동 제안도 활성 손절 익절을 알수 있게 해주고
                    지금 상태를 파악해줘 손실이 좀 있는것 같아"

    - 최근 N시간 자동 진입 (executed_at 기준!)
    - 각 항목 = ACTIVE / TAKE_PROFIT / STOP_LOSS / PENDING 분류!
    - 요약 = 활성 X + 손절 Y (총 -$Z) + 익절 W (총 +$V)
    - 손실 심볼 = 리스트 (사장님 즉시 파악!)
    """
    from datetime import timedelta as _td
    from app.models.strategy_instance import StrategyInstance
    from app.core.strategy_status import ACTIVE_LIKE

    since = datetime.now(timezone.utc) - _td(hours=hours)
    rows = db.execute(
        select(StrategySuggestion)
        .where(StrategySuggestion.execution_mode == "AUTO")
        .where(StrategySuggestion.executed_at >= since)
        .order_by(StrategySuggestion.executed_at.desc())
        .limit(50)
    ).scalars().all()

    items: list[dict] = []
    active_cnt = sl_cnt = tp_cnt = 0
    active_pnl_sum = sl_pnl_sum = tp_pnl_sum = 0.0
    losses: list[dict] = []

    for s in rows:
        strat = db.get(StrategyInstance, s.executed_strategy_id) if s.executed_strategy_id else None
        outcome = "PENDING"
        r_pnl = None
        u_pnl = None

        if strat:
            if strat.status in ACTIVE_LIKE:
                outcome = "ACTIVE"
                u_pnl = float(strat.unrealized_pnl or 0)
                active_cnt += 1
                active_pnl_sum += u_pnl
            else:
                r = float(strat.realized_pnl or 0)
                r_pnl = r
                if r > 0:
                    outcome = "TAKE_PROFIT"
                    tp_cnt += 1
                    tp_pnl_sum += r
                else:
                    outcome = "STOP_LOSS"
                    sl_cnt += 1
                    sl_pnl_sum += r
                    losses.append({
                        "symbol": s.symbol,
                        "side": s.side,
                        "pnl": r,
                        "executed_at": s.executed_at.isoformat() if s.executed_at else None,
                    })

        items.append({
            "id": s.id,
            "symbol": s.symbol,
            "side": s.side,
            "suggestion_type": s.suggestion_type,
            "confidence_score": float(s.confidence_score or 0),
            "executed_at": s.executed_at.isoformat() if s.executed_at else None,
            "outcome_status": outcome,
            "strategy_id": s.executed_strategy_id,
            "strategy_status": strat.status if strat else None,
            "realized_pnl": r_pnl,
            "unrealized_pnl": u_pnl,
        })

    return {
        "items": items,
        "summary": {
            "total": len(rows),
            "active": active_cnt,
            "stop_loss": sl_cnt,
            "take_profit": tp_cnt,
            "active_pnl_sum": round(active_pnl_sum, 2),
            "loss_sum": round(sl_pnl_sum, 2),
            "profit_sum": round(tp_pnl_sum, 2),
            "net_pnl": round(active_pnl_sum + sl_pnl_sum + tp_pnl_sum, 2),
        },
        "losses": losses,
        "hours": hours,
    }


@router.get("/unified-15m/monitoring")
def get_unified_15m_monitoring(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🌟 v224 (2026-08-23 사장님!): 15m 통합 워커 실시간 모니터링!

    Redis "unified_15m:monitoring" (TTL 60s, 워커가 매 30초 갱신!) 조회.
    - last_run_at / scanned / no_surge / surges / entered_today / skip_reasons
    - 사장님 대시보드 = 어떤 심볼이 지금 감지되는지 = 투명하게 표시!
    """
    try:
        import json as _json
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        raw = r.get("unified_15m:monitoring")
        if not raw:
            return {
                "empty": True,
                "note": "아직 실행 결과 없음! (30초 대기!)",
                "unified_entry_enabled": bool(int(
                    (db.get(SystemSetting, "unified_entry_enabled").value
                     if db.get(SystemSetting, "unified_entry_enabled") else "1")
                )),
            }
        data = _json.loads(raw)
        # 활성화 상태 병기!
        _en_row = db.get(SystemSetting, "unified_entry_enabled")
        data["unified_entry_enabled"] = (
            bool(int(_en_row.value)) if _en_row and _en_row.value else True
        )
        return data
    except Exception as e:
        logger.warning("[unified-15m/monitoring] 실패: %s", e)
        return {"error": str(e), "empty": True}


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


@router.get("/obv-settings")
def get_obv_settings(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🎯 사장님 (2026-08-22): OBV 자동 진입 세팅 조회! (전용!)"""
    def _get(key: str, default):
        row = db.get(SystemSetting, key)
        if not row or not row.value:
            return default
        try:
            if isinstance(default, int):
                return int(row.value)
            if isinstance(default, float):
                return float(row.value)
            return row.value
        except (ValueError, TypeError):
            return default
    return {
        "enabled": _get("auto_obv_enabled", 0),
        "daily_limit": _get("auto_obv_daily_limit", 3),
        "min_confidence": _get("auto_obv_min_confidence", 0.95),
        "capital_per_stage": _get("auto_obv_capital_per_stage", 400),  # 각 단계 자본!
        "leverage": _get("auto_obv_leverage", 2),
        "stage2_trigger_pct": _get("auto_obv_stage2_trigger", -5.0),   # -5%!
        "stage3_trigger_pct": _get("auto_obv_stage3_trigger", -10.0),  # -10%!
        "tp1_percent": _get("auto_obv_tp1", 10.0),
        "tp2_percent": _get("auto_obv_tp2", 15.0),
        "tp3_percent": _get("auto_obv_tp3", 20.0),
        "tp4_percent": _get("auto_obv_tp4", 25.0),
    }


@router.put("/obv-settings")
def set_obv_settings(
    payload: dict,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🎯 사장님 (2026-08-22): OBV 자동 진입 세팅 저장!"""
    fields = {
        "auto_obv_enabled": (int, payload.get("enabled", 0), 0, 1),
        "auto_obv_daily_limit": (int, payload.get("daily_limit", 3), 0, 20),
        "auto_obv_min_confidence": (float, payload.get("min_confidence", 0.95), 0.5, 1.0),
        "auto_obv_capital_per_stage": (int, payload.get("capital_per_stage", 400), 10, 100000),
        "auto_obv_leverage": (int, payload.get("leverage", 2), 1, 20),
        "auto_obv_stage2_trigger": (float, payload.get("stage2_trigger_pct", -5.0), -50.0, -0.5),
        "auto_obv_stage3_trigger": (float, payload.get("stage3_trigger_pct", -10.0), -80.0, -1.0),
        "auto_obv_tp1": (float, payload.get("tp1_percent", 10.0), 0.5, 100.0),
        "auto_obv_tp2": (float, payload.get("tp2_percent", 15.0), 0.5, 100.0),
        "auto_obv_tp3": (float, payload.get("tp3_percent", 20.0), 0.5, 100.0),
        "auto_obv_tp4": (float, payload.get("tp4_percent", 25.0), 0.5, 100.0),
    }
    result = {}
    for key, (dtype, raw, lo, hi) in fields.items():
        try:
            val = dtype(raw)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail=f"{key}: 잘못된 값!")
        if val < lo or val > hi:
            raise HTTPException(status_code=400, detail=f"{key}: {lo}~{hi} 허용!")
        row = db.get(SystemSetting, key)
        if row:
            row.value = str(val)
        else:
            db.add(SystemSetting(key=key, value=str(val), description=f"OBV 자동 진입: {key}"))
        # UI 키로 매핑!
        _ui_key = key.replace("auto_obv_", "")
        if _ui_key in ("enabled", "daily_limit", "leverage", "capital_per_stage"):
            result[_ui_key if _ui_key != "capital_per_stage" else "capital_per_stage"] = val
        elif _ui_key == "min_confidence":
            result["min_confidence"] = val
        elif _ui_key == "stage2_trigger":
            result["stage2_trigger_pct"] = val
        elif _ui_key == "stage3_trigger":
            result["stage3_trigger_pct"] = val
        elif _ui_key.startswith("tp"):
            result[f"{_ui_key}_percent"] = val
    db.commit()
    return result


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


@router.get("/v219-monitoring")
def get_v219_monitoring(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🌟 v219 (2026-08-23 사장님!): 7중 정점 SHORT 감시 데이터!

    반환:
      - pump_top_alerts: Redis pump_top:alert:* (7중 정점 감지 후보 = 진입 대상!)
      - monitoring_symbols: Redis pump_top:scanned:* (감시 중 = v219 통과 여부/스코어!)
      - reentry_watch: 최근 24h 내 청산된 SHORT 심볼 (재진입 후보!)
      - active_count: DB 활성 SHORT 개수 (사장님 요청 = 개수만!)
      - daily_used: v219 오늘 사용 개수!
      - daily_limit: SystemSetting sajangnim_top_short_daily_limit!
    """
    import json as _json
    from datetime import datetime as _dt, timedelta as _td

    # ─── 1) pump_top:alert:* 스캔 (감지 후보!) ───
    pump_top_alerts: list[dict] = []
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        for key in r.scan_iter(match="pump_top:alert:*", count=200):
            try:
                raw = r.get(key)
                if not raw:
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="ignore")
                data = _json.loads(raw)
                pump_top_alerts.append({
                    "symbol": data.get("symbol"),
                    "side": data.get("side"),
                    "confidence": data.get("confidence"),
                    "change_24h": data.get("change_24h"),
                })
            except Exception as _e:
                logger.debug("[v219-monitoring] alert parse skip %s: %s", key, _e)
                continue
    except Exception as e:
        logger.warning("[v219-monitoring] redis scan 실패: %s", e)
        r = None

    # ─── 1b) pump_top:scanned:* (감시 중 심볼!) ───
    monitoring_symbols: list[dict] = []
    try:
        if r is None:
            from app.core.redis_client import get_redis_client
            r = get_redis_client()
        for key in r.scan_iter(match="pump_top:scanned:*", count=500):
            try:
                raw = r.get(key)
                if not raw:
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="ignore")
                data = _json.loads(raw)
                monitoring_symbols.append({
                    "symbol": data.get("symbol"),
                    "change_24h": data.get("change_24h"),
                    "passed_v219": bool(data.get("passed_v219", False)),
                    "confidence": data.get("confidence"),
                    "scores": data.get("scores") or {
                        "score_15m": data.get("score_15m"),
                        "score_1h": data.get("score_1h"),
                        "score_4h": data.get("score_4h"),
                    },
                })
            except Exception as _e:
                logger.debug("[v219-monitoring] scanned parse skip %s: %s", key, _e)
                continue
        # 정렬 = 통과 > 24h 변동 내림차순 → 최대 20개!
        monitoring_symbols.sort(
            key=lambda x: (
                1 if x.get("passed_v219") else 0,
                float(x.get("change_24h") or 0),
            ),
            reverse=True,
        )
        monitoring_symbols = monitoring_symbols[:20]
    except Exception as e:
        logger.warning("[v219-monitoring] scanned scan 실패: %s", e)

    # ─── 1c) sajangnim:bottom_long:alert:* (LONG 저점 감지!) ───
    long_bottom_alerts: list[dict] = []
    try:
        if r is None:
            from app.core.redis_client import get_redis_client
            r = get_redis_client()
        for key in r.scan_iter(match="sajangnim:bottom_long:*", count=200):
            try:
                raw = r.get(key)
                if not raw:
                    continue
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="ignore")
                data = _json.loads(raw)
                long_bottom_alerts.append({
                    "symbol": data.get("symbol"),
                    "side": data.get("side") or "LONG",
                    "confidence": data.get("confidence"),
                    "change_24h": data.get("change_24h"),
                    "scores": data.get("scores"),
                    "passed_v219": bool(data.get("passed_v219", False)),
                })
            except Exception as _e:
                logger.debug("[v219-monitoring] bottom_long parse skip %s: %s", key, _e)
                continue
    except Exception as e:
        logger.warning("[v219-monitoring] bottom_long scan 실패: %s", e)

    # ─── 1d) LONG 저점 감시 심볼 (passed_v219 아닌 것 포함, 상위 20개!) ───
    monitoring_symbols_long: list[dict] = []
    try:
        # long_bottom_alerts 재활용: 24h 하락 심한 순으로 정렬
        _lst = list(long_bottom_alerts)
        _lst.sort(
            key=lambda x: (
                1 if x.get("passed_v219") else 0,
                -float(x.get("change_24h") or 0),  # 하락 클수록 앞!
            ),
            reverse=True,
        )
        monitoring_symbols_long = _lst[:20]
    except Exception as e:
        logger.warning("[v219-monitoring] monitoring_symbols_long 정렬 실패: %s", e)

    # ─── 2) 활성 SHORT (ACTIVE_LIKE) = 개수만! ───
    active_count = 0
    try:
        from app.models.strategy_instance import StrategyInstance
        from app.core.strategy_status import ACTIVE_LIKE, TERMINAL_STATUSES
        active_count = int(db.execute(
            select(func.count(StrategyInstance.id))
            .where(StrategyInstance.user_id == user_id)
            .where(StrategyInstance.side == "SHORT")
            .where(StrategyInstance.status.in_(tuple(ACTIVE_LIKE)))
        ).scalar() or 0)
    except Exception as e:
        logger.warning("[v219-monitoring] active SHORT count 실패: %s", e)

    # ─── 2a) 활성 LONG (sajangnim_bottom 전략) = 목록! ───
    active_longs: list[dict] = []
    try:
        from app.models.strategy_instance import StrategyInstance
        from app.core.strategy_status import ACTIVE_LIKE
        rows_long = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.user_id == user_id)
            .where(StrategyInstance.side == "LONG")
            .where(StrategyInstance.status.in_(tuple(ACTIVE_LIKE)))
            .where(StrategyInstance.strategy_type.ilike("%sajangnim_bottom%"))
            .order_by(StrategyInstance.created_at.desc())
            .limit(30)
        ).scalars().all()
        for si in rows_long:
            active_longs.append({
                "id": si.id,
                "symbol": si.symbol,
                "side": si.side,
                "status": si.status,
                "strategy_type": si.strategy_type,
                "created_at": si.created_at.isoformat() if si.created_at else None,
            })
    except Exception as e:
        logger.warning("[v219-monitoring] active_longs 조회 실패: %s", e)

    # ─── 2b) reentry_watch (최근 24h 청산 SHORT = 재진입 후보!) ───
    reentry_watch: list[dict] = []
    try:
        from app.models.strategy_instance import StrategyInstance
        from app.core.strategy_status import TERMINAL_STATUSES
        cutoff = _dt.now(timezone.utc) - _td(hours=24)
        rows = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.user_id == user_id)
            .where(StrategyInstance.side == "SHORT")
            .where(StrategyInstance.status.in_(tuple(TERMINAL_STATUSES)))
            .where(StrategyInstance.stopped_at.is_not(None))
            .where(StrategyInstance.stopped_at >= cutoff)
            .order_by(StrategyInstance.stopped_at.desc())
            .limit(15)
        ).scalars().all()
        for si in rows:
            reentry_watch.append({
                "symbol": si.symbol,
                "side": si.side,
                "closed_at": si.stopped_at.isoformat() if si.stopped_at else None,
                "realized_pnl": (
                    str(si.realized_pnl) if si.realized_pnl is not None else "0"
                ),
                "reason": si.status,
            })
    except Exception as e:
        logger.warning("[v219-monitoring] reentry_watch 조회 실패: %s", e)

    # ─── 2c) reentry_watch_long (최근 24h 청산 LONG sajangnim_bottom 재진입 후보!) ───
    reentry_watch_long: list[dict] = []
    try:
        from app.models.strategy_instance import StrategyInstance
        from app.core.strategy_status import TERMINAL_STATUSES
        cutoff_l = _dt.now(timezone.utc) - _td(hours=24)
        rows_l = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.user_id == user_id)
            .where(StrategyInstance.side == "LONG")
            .where(StrategyInstance.status.in_(tuple(TERMINAL_STATUSES)))
            .where(StrategyInstance.strategy_type.ilike("%sajangnim_bottom%"))
            .where(StrategyInstance.stopped_at.is_not(None))
            .where(StrategyInstance.stopped_at >= cutoff_l)
            .order_by(StrategyInstance.stopped_at.desc())
            .limit(15)
        ).scalars().all()
        for si in rows_l:
            reentry_watch_long.append({
                "symbol": si.symbol,
                "side": si.side,
                "closed_at": si.stopped_at.isoformat() if si.stopped_at else None,
                "realized_pnl": (
                    str(si.realized_pnl) if si.realized_pnl is not None else "0"
                ),
                "reason": si.status,
            })
    except Exception as e:
        logger.warning("[v219-monitoring] reentry_watch_long 조회 실패: %s", e)

    # ─── 3) daily_limit (SystemSetting) ───
    daily_limit = 0
    try:
        row = db.get(SystemSetting, "sajangnim_top_short_daily_limit")
        if row and row.value:
            daily_limit = int(row.value)
    except Exception as e:
        logger.warning("[v219-monitoring] daily_limit 조회 실패: %s", e)

    # ─── 4) daily_used (오늘 v219 실행 개수 = KST 기준!) ───
    #    suggestion_type = "sajangnim_top_short" + executed_at 오늘 (KST)!
    daily_used = 0
    try:
        from datetime import timedelta as _td
        now_utc = _dt.now(timezone.utc)
        # KST 자정 = UTC 15:00 (전일)
        kst_now = now_utc + _td(hours=9)
        kst_midnight_utc = (
            kst_now.replace(hour=0, minute=0, second=0, microsecond=0) - _td(hours=9)
        )
        cnt_row = db.execute(
            select(StrategySuggestion).where(
                StrategySuggestion.suggestion_type == "sajangnim_top_short",
                StrategySuggestion.executed_at.is_not(None),
                StrategySuggestion.executed_at >= kst_midnight_utc,
            )
        ).scalars().all()
        daily_used = len(cnt_row)
    except Exception as e:
        logger.warning("[v219-monitoring] daily_used 집계 실패: %s", e)

    return {
        # ─── SHORT (기존, 호환성 유지!) ───
        "pump_top_alerts": pump_top_alerts,
        "monitoring_symbols": monitoring_symbols,
        "reentry_watch": reentry_watch,
        "active_count": active_count,
        "daily_used": daily_used,
        "daily_limit": daily_limit,
        "remaining": max(0, daily_limit - daily_used),
        # ─── LONG (신규, 사장님 신 사상!) ───
        "long_bottom_alerts": long_bottom_alerts,
        "monitoring_symbols_long": monitoring_symbols_long,
        "active_longs": active_longs,
        "reentry_watch_long": reentry_watch_long,
    }


# 🚨 v132 fix: /trigger-now, /briefing-now, /settings routes = 위로 이동!
# (specific routes MUST come BEFORE parametric routes!)
