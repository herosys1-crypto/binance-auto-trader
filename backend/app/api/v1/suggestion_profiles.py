"""🎯 Suggestion Default Profiles API (v132 신!)

사장님 요구 (2026-08-11):
"기본 세팅값 필요! 몇가지 세팅값을 만들어 놓은면 좋겠지만
 이전에 진행한 기본값을 기준으로 새전략을 만들수 있게 해줘"

= 여러 프로필 지원!
= default 지정!
= 이전 전략 = 복사 가능!

저장:
- system_settings.key = 'suggestion_default_profiles'
- value = JSON string (프로필 리스트!)
- default = current_default profile name!
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.models.system_setting import SystemSetting
from app.models.strategy_instance import StrategyInstance

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/suggestion-profiles", tags=["suggestion-profiles"])

# system_settings key!
PROFILES_KEY = "suggestion_default_profiles"
DEFAULT_KEY = "suggestion_current_default_profile"


# 초기 프로필 (사장님 시작용!)
INITIAL_PROFILES = [
    {
        "name": "safe",
        "label": "🛡 안전 매매",
        "description": "레버리지 2x, 소액 진입!",
        "config": {
            "leverage": 2,
            "capitals": [500, 500, 500, 500],
            "trigger_percents": [None, 10, 20, 20],
            "tp1_percent": 10, "tp2_percent": 15, "tp3_percent": 20, "tp4_percent": 25,
            "tp1_qty_ratio": 10, "tp2_qty_ratio": 15, "tp3_qty_ratio": 20, "tp4_qty_ratio": 25,
            "tp1_pct_override": 25,
            "force_sl_enabled_override": True,
            "force_sl_roi_override": 5,
            "stop_loss_percent_of_capital": 90,
            "start_price": None,  # MARKET!
            "retry_after_liquidation_enabled": False,
            "retry_trigger_pct": 10,
        }
    },
    {
        "name": "aggressive",
        "label": "🔥 공격적 매매",
        "description": "레버리지 5x, 큰 자본!",
        "config": {
            "leverage": 5,
            "capitals": [1000, 1000, 1000, 1000],
            "trigger_percents": [None, 10, 15, 20],
            "tp1_percent": 8, "tp2_percent": 12, "tp3_percent": 18, "tp4_percent": 25,
            "tp1_qty_ratio": 15, "tp2_qty_ratio": 20, "tp3_qty_ratio": 25, "tp4_qty_ratio": 25,
            "tp1_pct_override": 20,
            "force_sl_enabled_override": True,
            "force_sl_roi_override": 10,
            "stop_loss_percent_of_capital": 90,
            "start_price": None,
            "retry_after_liquidation_enabled": False,
            "retry_trigger_pct": 10,
        }
    },
    {
        "name": "conservative",
        "label": "🕊 보수적 매매",
        "description": "레버리지 1x, 안전 자본!",
        "config": {
            "leverage": 1,
            "capitals": [300, 300, 300, 300],
            "trigger_percents": [None, 15, 20, 25],
            "tp1_percent": 15, "tp2_percent": 20, "tp3_percent": 30, "tp4_percent": 40,
            "tp1_qty_ratio": 10, "tp2_qty_ratio": 15, "tp3_qty_ratio": 25, "tp4_qty_ratio": 30,
            "tp1_pct_override": 30,
            "force_sl_enabled_override": True,
            "force_sl_roi_override": 30,
            "stop_loss_percent_of_capital": 90,
            "start_price": None,
            "retry_after_liquidation_enabled": False,
            "retry_trigger_pct": 10,
        }
    }
]


class ProfileConfig(BaseModel):
    leverage: int = 2
    capitals: list[float] = Field(default_factory=lambda: [500, 500, 500, 500])
    trigger_percents: list[float | None] = Field(
        default_factory=lambda: [None, 10, 20, 20],
    )
    tp1_percent: float = 10
    tp2_percent: float = 15
    tp3_percent: float = 20
    tp4_percent: float = 25
    tp1_qty_ratio: float = 10
    tp2_qty_ratio: float = 15
    tp3_qty_ratio: float = 20
    tp4_qty_ratio: float = 25
    tp1_pct_override: float = 25
    force_sl_enabled_override: bool = True
    force_sl_roi_override: float = 5   # v166 사장님: -15% → -5%!
    stop_loss_percent_of_capital: float = 90
    start_price: float | None = None
    retry_after_liquidation_enabled: bool = False
    retry_trigger_pct: float = 10


class ProfileEntry(BaseModel):
    name: str
    label: str = ""
    description: str = ""
    config: ProfileConfig


class ProfilesResponse(BaseModel):
    profiles: list[dict]
    default: str


def _load_profiles(db: Session) -> tuple[list[dict], str]:
    """프로필 로드!"""
    row = db.get(SystemSetting, PROFILES_KEY)
    if not row or not row.value:
        # 초기 = 기본 프로필 자동 생성!
        _save_profiles(db, INITIAL_PROFILES, "safe")
        return INITIAL_PROFILES, "safe"
    try:
        profiles = json.loads(row.value)
    except Exception:
        profiles = INITIAL_PROFILES
    default_row = db.get(SystemSetting, DEFAULT_KEY)
    default_name = default_row.value if default_row else "safe"
    return profiles, default_name


def _save_profiles(db: Session, profiles: list[dict], default_name: str) -> None:
    """프로필 저장!"""
    val = json.dumps(profiles, ensure_ascii=False)
    row = db.get(SystemSetting, PROFILES_KEY)
    if row:
        row.value = val
    else:
        db.add(SystemSetting(
            key=PROFILES_KEY, value=val,
            description="Strategy Suggestion 기본 프로필 리스트 (JSON!)",
        ))
    d_row = db.get(SystemSetting, DEFAULT_KEY)
    if d_row:
        d_row.value = default_name
    else:
        db.add(SystemSetting(
            key=DEFAULT_KEY, value=default_name,
            description="현재 default 프로필 이름!",
        ))
    db.commit()


@router.get("", response_model=ProfilesResponse)
def list_profiles(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> ProfilesResponse:
    """프로필 리스트 + 현재 default!"""
    profiles, default = _load_profiles(db)
    return ProfilesResponse(profiles=profiles, default=default)


@router.put("", response_model=ProfilesResponse)
def update_profiles(
    payload: dict,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> ProfilesResponse:
    """프로필 리스트 전체 저장! (사장님 편집!)"""
    profiles = payload.get("profiles", INITIAL_PROFILES)
    default_name = payload.get("default", "safe")
    _save_profiles(db, profiles, default_name)
    return ProfilesResponse(profiles=profiles, default=default_name)


# 🌟 v132 (2026-08-12 사장님!): 세팅 변경 = 오늘 PENDING 카드에도 즉시 적용!
@router.post("/apply-to-pending")
def apply_current_profile_to_pending(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """default 프로필 = 오늘 PENDING 제안 카드에 = 자동 적용!

    사장님 「⚙ 세팅」 = 저장 후 = 자동 호출!
    = 기존 카드의 strategy_config도 = 신 세팅 반영!
    """
    from datetime import datetime, timezone
    from app.models.strategy_suggestion import StrategySuggestion

    # default 프로필 로드!
    profiles, default_name = _load_profiles(db)
    default_profile = next(
        (p for p in profiles if p.get("name") == default_name),
        None,
    )
    if not default_profile:
        return {"updated": 0, "note": "default 프로필 없음"}

    default_cfg = default_profile.get("config") or {}

    # 오늘 PENDING 카드 조회!
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    pending = db.execute(
        select(StrategySuggestion)
        .where(StrategySuggestion.status == "PENDING")
        .where(StrategySuggestion.created_at >= today_start)
    ).scalars().all()

    updated = 0
    for s in pending:
        # 각 카드 = default_cfg로 갱신! (symbol/side 유지!)
        new_cfg = dict(default_cfg)
        new_cfg["symbol"] = s.symbol
        new_cfg["side"] = s.side
        s.strategy_config = new_cfg
        updated += 1

    db.commit()
    logger.info("[apply-to-pending] %d 카드 update!", updated)
    return {
        "updated": updated,
        "profile": default_name,
        "note": f"오늘 PENDING {updated}건 = 신 세팅 적용!",
    }


@router.get("/from-strategy/{strategy_id}")
def profile_from_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """이전 전략 → 프로필 config 자동 생성! (사장님 편의!)"""
    from app.models.strategy_template import StrategyTemplate
    strategy = db.get(StrategyInstance, strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="전략을 찾을 수 없음!")
    tpl = db.get(StrategyTemplate, strategy.strategy_template_id) if strategy.strategy_template_id else None
    if not tpl:
        raise HTTPException(status_code=404, detail="템플릿 없음!")

    sc = tpl.stages_config or {}
    return {
        "name": f"from_strategy_{strategy_id}",
        "label": f"⭐ 전략 #{strategy_id} 복사",
        "description": f"{strategy.symbol} {strategy.side} 세팅!",
        "config": {
            "leverage": int(strategy.leverage or tpl.leverage or 2),
            "capitals": sc.get("capitals") or [500, 500, 500, 500],
            "trigger_percents": sc.get("trigger_percents") or [None, 10, 20, 20],
            "tp1_percent": float(tpl.tp1_percent or 10),
            "tp2_percent": float(tpl.tp2_percent or 15),
            "tp3_percent": float(tpl.tp3_percent or 20),
            "tp4_percent": float(tpl.tp4_percent or 25),
            "tp1_qty_ratio": float(tpl.tp1_qty_ratio or 10),
            "tp2_qty_ratio": float(tpl.tp2_qty_ratio or 15),
            "tp3_qty_ratio": float(tpl.tp3_qty_ratio or 20),
            "tp4_qty_ratio": float(tpl.tp4_qty_ratio or 25),
            "tp1_pct_override": float(strategy.tp1_pct_override or 25),
            "force_sl_enabled_override": bool(strategy.force_sl_enabled_override),
            "force_sl_roi_override": float(strategy.force_sl_roi_override or 15),
            "stop_loss_percent_of_capital": float(tpl.stop_loss_percent_of_capital or 90),
            "start_price": None,
            "retry_after_liquidation_enabled": bool(
                getattr(strategy, "retry_after_liquidation_enabled", False)
            ),
            "retry_trigger_pct": float(
                getattr(strategy, "retry_trigger_pct", None) or 10
            ),
        }
    }
