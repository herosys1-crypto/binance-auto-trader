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

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.models.strategy_suggestion import StrategySuggestion
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

# 🚨 Fix 192 (2026-08-28): 이 api 프로세스가 제공하는 기능 목록.
#   화면이 「내가 기대하는 기능이 응답에 없다 = api 가 옛 코드다」를 스스로 판단하게 한다.
#   새 UI 기능을 추가할 때 여기에 이름을 더할 것.
API_FEATURES = (
    "bbsplit",              # Fix 181: 볼밴 분할 전략 설정
    "bbsplit_tristate",     # Fix 192: 모르면 None (fail-OFF 금지)
    "concurrent_limit_v2",  # Fix 188/191: 실효 동시 상한 반환
)

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
    # 🎯 v219 → Fix 112 로 의미 변경: 「하루 건수」가 아니라 「동시 보유 상한」.
    # 🚨 Fix 188: 여기서 원시 키를 직접 읽지 않는다 — _effective_concurrent_limit 참조.

    return {
        "default_capital": float(default_cap_row.value) if default_cap_row and default_cap_row.value else 300.0,
        "capital_mode": (mode_row.value if mode_row and mode_row.value else "fixed"),
        "entry_pct": float(pct_row.value) if pct_row and pct_row.value else 0.01,
        "daily_limit": int(daily_limit_row.value) if daily_limit_row and daily_limit_row.value else 1,
        # 🎯 Fix 145 (2026-08-26 사장님 스크린샷): 사다리 3칸인데 여기가 2 라서 600 이 잘렸다.
        #   원시 설정값이 아니라 「실제 적용되는 값」을 돌려준다 (헌법 85).
        #   get_max_stage 는 사다리 길이를 상한으로 clamp 한다.
        "max_stage": _effective_max_stage(db),
        # 🚨 Fix 188 (2026-08-28 사장님 "30개에서 10개로 자동 변경"):
        #   원시 키가 아니라 **워커가 실제로 쓰는 값**을 돌려준다 (헌법 85).
        #   옛 코드는 sajangnim_top_short_daily_limit 만 읽어서,
        #   더 우선순위 높은 키가 있으면 화면과 실제가 영구히 어긋났다.
        "top_short_daily_limit": _effective_concurrent_limit(db),
        # 🎯 Fix 144 (2026-08-26 사장님): 자본 사다리 (UI 에서 직접 수정 가능하게)
        #   실제 적용값을 그대로 돌려준다 = 화면과 워커가 같은 진실을 본다 (헌법 85)
        "capital_ladder": _current_ladder_str(db),
        # 🎯 Fix 176 (2026-08-27 사장님): 피라미딩 1회 금액 = 사다리와 독립된 고정값
        #   "초기 1단계 상관없이 300으로 고정하고 300도 차후에 선택옵션으로"
        #   워커와 같은 함수를 써서 화면과 실제가 어긋나지 않게 한다 (헌법 85)
        "pyramid_capital": _current_pyramid_capital(db),
        # 📊 Fix 181 (2026-08-27 사장님): 볼밴 분할 전략 설정
        #   "볼밴 전략시스템은 어디서 세팅을 하고 볼수 있나요?"
        #   → 설정 키만 있고 화면이 없어 DB 명령으로만 바꿀 수 있었다 (Fix 115 교훈).
        #   워커와 **같은 로더**를 써서 화면과 실제가 어긋나지 않게 한다 (헌법 85).
        # 🚨 Fix 192: 「git pull 은 했는데 재시작을 안 했다」가 화면에서 즉시 드러나게.
        #   이 프로젝트의 상습 실패모드다 (Fix 185 도 같은 이유로 하루를 잃었다).
        #   화면은 여기에 자기가 기대하는 기능이 없으면 「api 가 옛 코드」라고 말할 수 있다.
        "api_features": list(API_FEATURES),
        **_current_bbsplit(db),
    }


def _current_bbsplit(db) -> dict:
    """볼밴 분할 전략의 「실제 적용값」 — 워커의 _load_config 를 그대로 사용.

    🚨 Fix 192 (2026-08-28 사장님 "켬으로 했는데 껌으로 변해 있었어"): **fail-OFF 금지.**

    옛 코드는 초기값이 `bbsplit_enabled: 0`(끔) 이고 예외를 통째로 삼켰다.
    그래서 DB 가 '1'(켬) 이어도 조회 중 무엇 하나만 실패하면
    **HTTP 200 으로 「끔」을 돌려주고**, 화면은 그것을 그대로 믿었다.
    「모름」을 표현할 수단이 없어서 **「모름」이 「꺼짐」으로 표시**된 것이다.
    돈을 쓰는 전략의 ON/OFF 에서 이 방향의 침묵은 특히 위험하다 (헌법 83 의 표시판 판).

    → 모르면 None. 0 은 **정말로 꺼져 있을 때만.** 실패 사유도 함께 돌려준다.
    → import 와 DB 조회를 **분리**해서, 한쪽이 죽어도 다른 쪽 값은 살린다.
    """
    out: dict = {
        "bbsplit_enabled": None,
        "bbsplit_max": None,
        "bbsplit_capitals": None,
        "bbsplit_error": None,
    }
    errs = []
    try:
        row = db.get(SystemSetting, "pump_split_enabled")
        out["bbsplit_enabled"] = 1 if (row and str(row.value).strip() == "1") else 0
    except Exception as e:
        errs.append(f"enabled: {e}")
        logger.warning("[bbsplit] enabled 조회 실패: %s", e)
    try:
        from app.workers.pump_split_entry_worker import _load_config
        caps, max_n, _src = _load_config(db)
        out["bbsplit_max"] = max_n
        out["bbsplit_capitals"] = ",".join(
            (format(c, "f").rstrip("0").rstrip(".") if "." in format(c, "f") else format(c, "f"))
            for c in caps
        )
    except Exception as e:
        errs.append(f"config: {e}")
        logger.warning("[bbsplit] config 조회 실패: %s", e)
    if errs:
        out["bbsplit_error"] = " / ".join(errs)
    return out


def _current_pyramid_capital(db) -> str:
    """실제 적용되는 피라미딩 1회 금액 (get_pyramid_capital 그대로)."""
    try:
        from app.services.sajangnim_capital import get_pyramid_capital
        v = get_pyramid_capital(db)
        s = format(v, "f")
        return s.rstrip("0").rstrip(".") if "." in s else s
    except Exception:
        return "300"


def _effective_concurrent_limit(db) -> int:
    """🚨 Fix 188 (2026-08-28 사장님): 실제 적용되는 「최대 동시 포지션」.

    사장님 증상: "최대 포지션 30개에서 10개로 자동으로 변경되었어"

    원인 = 화면이 읽는 키와 워커가 읽는 키가 달랐다 (헌법 85/101).
      워커 get_max_concurrent() 우선순위:
        ① sajangnim_max_concurrent_positions   ← 최우선인데 **쓰는 코드가 없다**
        ② sajangnim_top_short_daily_limit      ← UI 가 읽고 쓰던 유일한 키
        ③ auto_bb_break_daily_limit
      → ① 이 DB 에 한 번이라도 들어가 있으면 (과거 수동 DB 명령 등)
        UI 에서 아무리 바꿔도 워커는 계속 ① 을 본다.
        화면은 ② 를 보여주므로 **화면과 실제가 영구히 어긋난다.**

    → 워커와 **같은 함수**를 써서 「지금 실제로 적용되는 값」을 돌려준다.
    """
    try:
        from app.services.position_limit import get_max_concurrent
        limit, src = get_max_concurrent(db)
        if src not in ("sajangnim_top_short_daily_limit", "default"):
            logger.warning(
                "[Fix188] 동시 상한이 UI 키가 아닌 '%s' 에서 결정되고 있습니다 (값=%s). "
                "PUT 시 두 키를 함께 동기화합니다.", src, limit,
            )
        return int(limit)
    except Exception as e:
        # fail-safe 하지 않고 raw 값으로 떨어지면 화면이 또 거짓말을 한다.
        logger.warning("[Fix188] 동시 상한 조회 실패: %s", e)
        row = db.get(SystemSetting, "sajangnim_top_short_daily_limit")
        return int(row.value) if row and row.value else 0


def _effective_max_stage(db) -> int:
    """실제 적용되는 마틴게일 최대 단계 (사다리 길이가 상한)."""
    try:
        from app.services.sajangnim_capital import get_max_stage
        return int(get_max_stage(db))
    except Exception as e:
        logger.warning("[Fix145] max_stage 조회 실패: %s", e)
        return 2


def _current_ladder_str(db) -> str:
    """지금 실제로 적용 중인 자본 사다리를 문자열로 (UI 표시/수정용)."""
    try:
        from app.services.sajangnim_capital import get_capital_ladder
        vals = get_capital_ladder(db)
        out = []
        for d in vals:
            t = format(d, "f")
            if "." in t:
                t = t.rstrip("0").rstrip(".")
            out.append(t or "0")
        return ",".join(out)
    except Exception as e:
        logger.warning("[Fix144] 사다리 조회 실패: %s", e)
        return ""


def _sanitize_bbsplit_capitals(raw) -> str:
    """📊 Fix 181: 볼밴 분할 자본 3칸 + **죽은 단계 검산** (헌법 130).

    자본 비중을 바꾸면 평단이 달라지고 → 손절가가 움직여서
    「손절이 다음 차수 트리거보다 먼저 오는」 상태가 될 수 있다.
    그러면 그 차수는 **영원히 진입되지 않고 로그에도 안 남는다.**
    → 저장 단계에서 막는다. 워커가 쓰는 것과 **같은 함수**로 검산한다 (헌법 85/101).
    """
    from app.workers.pump_split_entry_worker import (
        FORCE_SL_ROI, LEVERAGE, SPLIT_STEP_PCT, _parse_capitals, check_no_dead_stage,
    )
    caps = _parse_capitals(raw)   # 3칸 / 양수 / 상한 검증
    ok, why = check_no_dead_stage(caps, SPLIT_STEP_PCT, FORCE_SL_ROI, LEVERAGE)
    if not ok:
        raise ValueError(
            f"이 자본 조합은 사용할 수 없습니다 — {why}. "
            "그 단계는 진입 조건에 도달하기 전에 손절이 먼저 발동해 "
            "영원히 사용되지 않습니다."
        )
    return ",".join(
        (format(c, "f").rstrip("0").rstrip(".") if "." in format(c, "f") else format(c, "f"))
        for c in caps
    )


def _sanitize_pyramid_capital(raw) -> str:
    """🎯 Fix 176: 피라미딩 1회 금액 정규화 (1~100000).

    사장님이 「초기 1단계 상관없이 300으로 고정」 하라고 하신 값이다.
    사다리와 독립이므로 여기서만 검증한다.
    """
    from decimal import Decimal as _D
    try:
        v = _D(str(raw).strip())
    except Exception as e:
        raise ValueError(f"피라미딩 금액이 숫자가 아닙니다: {raw!r}") from e
    if v <= 0:
        raise ValueError(
            "피라미딩 금액은 0보다 커야 합니다. "
            "피라미딩을 끄시려면 sajangnim_pyramid_enabled 를 0 으로 두세요."
        )
    v = min(v, _D("100000"))
    s = format(v, "f")
    return s.rstrip("0").rstrip(".") if "." in s else s


def _sanitize_ladder(raw) -> str:
    """🎯 Fix 144: 자본 사다리 문자열 정규화 ("10, 300 ,600" → "10,300,600").

    손상값이 저장되면 사다리 조회가 기본값으로 떨어져 사장님 설정이 조용히 무시된다.
    여기서 걸러 「저장은 됐는데 반영 안 됨」 상태를 만들지 않는다.
    """
    vals = []
    for part in str(raw or "").replace(" ", "").split(","):
        if not part:
            continue
        d = Decimal(part)              # 숫자가 아니면 여기서 예외 = 상위에서 400
        if d <= 0:
            raise ValueError(f"자본은 0보다 커야 합니다: {part}")
        vals.append(d.quantize(Decimal("0.01")))
    if not vals:
        raise ValueError("자본 사다리가 비어 있습니다")
    if len(vals) > 3:
        raise ValueError(f"사다리는 최대 3칸입니다 (입력 {len(vals)}칸)")
    for d in vals:
        if d > Decimal("100000"):
            raise ValueError(f"단계 자본 상한 100000 초과: {d}")
    def _fmt(d: Decimal) -> str:
        # ⚠️ rstrip("0") 은 소수점이 있을 때만! 정수 "10" 에 쓰면 "1" 이 된다.
        t = format(d, "f")
        if "." in t:
            t = t.rstrip("0").rstrip(".")
        return t or "0"

    return ",".join(_fmt(d) for d in vals)


@router.put("/sajangnim-settings")
def set_sajangnim_settings(
    payload: dict = Body(...),  # 🌟 Fix 86 (2026-08-25): Body(...) 명시 = FastAPI dict 파싱 정상! (사장님 422 오류 fix!)
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🎯 v219: 사장님 실 성공 로직 세팅 저장!

    🌟 Fix 86 (2026-08-25 사장님 422 오류!): payload: dict = Body(...)
       = 옛: payload: dict → FastAPI가 raw string으로 해석 → 422!
       = 신: Body(...) 명시 → JSON body 자동 dict 파싱!
    """
    fields = {
        "sajangnim_default_capital": ("default_capital", lambda v: str(max(50.0, min(100000.0, float(v))))),
        "sajangnim_capital_mode": ("capital_mode", lambda v: str(v).lower() if str(v).lower() in ("fixed", "percent") else "fixed"),
        "sajangnim_entry_pct": ("entry_pct", lambda v: str(max(0.001, min(0.02, float(v))))),
        "sajangnim_daily_limit": ("daily_limit", lambda v: str(max(0, min(10, int(v))))),
        # 🎯 v219+ (2026-08-23 사장님!): 마틴게일 최대 단계 = 1~3 clamp!
        "sajangnim_max_stage": ("max_stage", lambda v: str(max(1, min(3, int(v))))),
        # 🎯 v219 (2026-08-23 사장님!): 7중 정점 SHORT 일일 한도 = 0~30 clamp!
        # 🎯 Fix 112b: 의미가 「하루 건수」 → 「동시 보유 건수」 로 바뀜 (사장님 요구).
        #   상한 30 이면 활성이 33건인 지금 사장님이 상한을 올려서 풀 수가 없다!
        #   → 0~200 으로 확장 (0 = 완전 OFF 는 그대로 유지!)
        "sajangnim_top_short_daily_limit": ("top_short_daily_limit", lambda v: str(max(0, min(200, int(v))))),
        # 🎯 Fix 144 (2026-08-26 사장님): 자본 사다리 "10,300,600"
        #   각 칸 1~100000 clamp, 최대 3칸 (MAX_REENTRY_STAGE), 빈 값이면 미저장
        "sajangnim_capital_ladder": ("capital_ladder", lambda v: _sanitize_ladder(v)),
        # 🎯 Fix 176 (2026-08-27 사장님): 피라미딩 1회 금액 (사다리와 독립, 1~100000)
        #   0 을 넣으면 「끄기」가 아니라 잘못된 입력이다 — 피라미딩 ON/OFF 는
        #   sajangnim_pyramid_enabled 로 따로 있다 (Fix 138 / 헌법 102).
        "sajangnim_pyramid_capital": ("pyramid_capital", lambda v: _sanitize_pyramid_capital(v)),
        # 📊 Fix 181: 볼밴 분할 전략
        "pump_split_enabled": ("bbsplit_enabled", lambda v: "1" if str(v).strip() in ("1", "true", "True") else "0"),
        "pump_split_max_concurrent": ("bbsplit_max", lambda v: str(max(0, min(100, int(v))))),
        "pump_split_capitals": ("bbsplit_capitals", lambda v: _sanitize_bbsplit_capitals(v)),
    }
    updated = {}
    for key, (payload_key, sanitizer) in fields.items():
        if payload_key not in payload:
            continue
        try:
            new_val = sanitizer(payload[payload_key])
            row = db.get(SystemSetting, key)
            # 🚨 Fix 193 (2026-08-28): 설정 변경 감사 기록.
            #   사장님 "30개에서 10개로 자동으로 변경되었어" 를 코드로 되짚을 수 없었던
            #   근본 이유 = 이력 테이블도 없고, user_id 를 받아놓고 updated_by 를
            #   채우지도 않았다. 누가·무엇을·무엇에서 바꿨는지 남는 게 하나도 없었다.
            #   ※ 값이 바뀔 때만 대입한다 — 같은 값을 대입하면 SQLAlchemy 가 UPDATE 를
            #     내지 않아 updated_at 이 안 움직이는데, 굳이 건드려 오염시킬 이유가 없다.
            if row:
                if str(row.value).strip() != new_val:
                    logger.info(
                        "[settings] %s: %r → %r (user=%s)", key, row.value, new_val, user_id,
                    )
                    row.value = new_val
                    row.updated_by = user_id
            else:
                logger.info("[settings] %s 신규=%r (user=%s)", key, new_val, user_id)
                row = SystemSetting(key=key, value=new_val, updated_by=user_id)
                db.add(row)
            updated[payload_key] = new_val
            # 🎯 Fix 145: 사다리를 저장하면 최대 단계를 사다리 길이에 「자동 동기화」.
            #   사장님 스크린샷: 사다리 3칸인데 최대 단계가 2 라서 600 이 잘려 있었다.
            #   두 설정이 서로 모순될 수 있는 구조 자체가 함정이므로,
            #   「사다리 길이 = 단계 수」로 못 박는다.
            if key == "sajangnim_capital_ladder":
                _n = len([x for x in new_val.split(",") if x.strip()])
                _ms = db.get(SystemSetting, "sajangnim_max_stage")
                if _ms:
                    _ms.value = str(_n)
                else:
                    db.add(SystemSetting(key="sajangnim_max_stage", value=str(_n)))
                updated["max_stage"] = str(_n)
                logger.info("[Fix145] 사다리 %s 저장 → max_stage 자동 %d 동기화", new_val, _n)
            # 🚨 Fix 191 (2026-08-28): Fix 188 의 그림자 키 동기화를 **철회**한다.
            #   실측 결과 sajangnim_max_concurrent_positions 행은 **존재한 적이 없었고**
            #   (30→10 의 원인도 아니었다), 그런데 Fix 188 은 저장할 때마다 그 행을
            #   **새로 만들고** 있었다 = 원래 없던 1순위 키를 내 손으로 설치한 셈이다.
            #   그 뒤로 누가 top_short_daily_limit 만 DB 로 바꾸면 그때부터 조용히 무시된다
            #   — **막으려던 함정을 스스로 파는** 코드였다.
            #   해법은 동기화가 아니라 **키를 하나로 못 박는 것** (헌법 102).
            #   → position_limit.LIMIT_KEYS 에서 그 키를 퇴역시켰다.
        except Exception as e:
            # 🚨 Fix 181: 옛 코드는 `return {"error": ...}` = **HTTP 200** 이었다.
            #   프론트 api() 는 200 을 성공으로 통과시키고, saveV219Settings 는
            #   r.error 를 읽지 않은 채 「✅ 저장 완료」를 띄운다.
            #   → 검증 실패인데 사장님은 저장됐다고 믿고, db.commit() 은 건너뛰어
            #     **그 요청의 다른 필드까지 전부 소실**된다 (감사에서 확인된 결함).
            #   4xx 로 바꾸면 프론트의 catch 가 실제 사유를 화면에 띄운다.
            db.rollback()
            logger.warning("[sajangnim-settings] 저장 거부 %s: %s", payload_key, e)
            raise HTTPException(status_code=400, detail=f"{payload_key}: {e}")
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
    usage = _count_auto_bb_used(db)
    # 🎯 Fix 112 (2026-08-26 사장님 "일 20개로 하지말고 최대 20개"):
    #   대시보드 「오늘 자동 진입 145/0」 = 하루 누적 카운터라 계속 커짐!
    #   → 「동시 보유 N/20」 으로 교체 = 워커 게이트와 동일 진실 (헌법 85!)
    #
    # 🚨 Fix 112b: 단, `limit` 필드는 이 엔드포인트의 PUT 이 쓰는 키
    #   (auto_bb_break_daily_limit) 를 그대로 돌려줘야 한다!
    #   안 그러면 BB 드롭다운이 저장 직후 「남의 값」으로 되돌아간다 = 조작 불가!
    #   동시보유 상한은 concurrent_limit 로 분리해서 내보낸다.
    row = db.get(SystemSetting, "auto_bb_break_daily_limit")
    bb_limit = int(row.value) if row and row.value else 0

    # ⚠️ Fix 112c: get_max_concurrent 는 설정 손상 시 RuntimeError 를 올린다 (fail-SAFE).
    #   워커에서는 그게 맞지만 「화면 조회」가 500 으로 죽으면 대시보드 전체가 깨진다.
    #   → 표시 경로는 soft-fail (unknown 표기), 자본 게이트는 hard-fail = 의도된 비대칭.
    from app.services.position_limit import get_max_concurrent, count_active_positions
    try:
        concurrent_limit, _src = get_max_concurrent(db)
        concurrent = count_active_positions(db)
    except Exception as e:
        logger.warning("[auto-bb-limit+Fix112c] 동시보유 상한 조회 실패: %s", e)
        concurrent_limit, _src, concurrent = 0, f"error: {e}", 0
    return {
        "limit": bb_limit,                 # ← PUT 이 쓰는 키와 동일 (되돌림 방지!)
        **usage,
        "daily_used": concurrent,          # 대시보드 카드 표시 = 동시 보유 수!
        "today_entered": usage.get("daily_used", 0),   # 참고: 오늘 신규 건수
        "concurrent_limit": concurrent_limit,
        "concurrent_active": concurrent,
        "limit_mode": "concurrent",
        "limit_src": _src,
        "remaining": max(0, concurrent_limit - concurrent),
    }


@router.put("/auto-bb-limit")
def set_auto_bb_limit(
    payload: dict = Body(...),  # Fix 86: FastAPI dict 파싱
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
    payload: dict = Body(...),  # Fix 86: FastAPI dict 파싱
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

    # ─── 2) 활성 SHORT (ACTIVE_LIKE) = 목록 + 개수! ───
    # 🚨 Fix 64 (2026-08-25): UI가 r.active_shorts.length 읽는데 API는 int만
    #    반환 = badge 0/0 silent bug! 대칭 `active_longs` 목록 형태로 반환!
    active_count = 0
    active_shorts: list[dict] = []
    try:
        from app.models.strategy_instance import StrategyInstance
        from app.core.strategy_status import ACTIVE_LIKE, TERMINAL_STATUSES
        rows_short = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.user_id == user_id)
            .where(StrategyInstance.side == "SHORT")
            .where(StrategyInstance.status.in_(tuple(ACTIVE_LIKE)))
            .order_by(StrategyInstance.created_at.desc())
            .limit(30)
        ).scalars().all()
        for si in rows_short:
            active_shorts.append({
                "id": si.id,
                "symbol": si.symbol,
                "side": si.side,
                "status": si.status,
                "stage": int(getattr(si, "current_stage", 0) or 0),
                "avg_price": (
                    str(si.avg_entry_price) if si.avg_entry_price is not None else None
                ),
                "unrealized_pnl": (
                    str(si.unrealized_pnl) if si.unrealized_pnl is not None else "0"
                ),
                "strategy_type": si.strategy_type,
                "created_at": si.created_at.isoformat() if si.created_at else None,
            })
        active_count = len(active_shorts)
    except Exception as e:
        logger.warning("[v219-monitoring] active SHORT 목록 실패: %s", e)

    # ─── 2a) 활성 LONG (sajangnim_bottom 전략) = 목록! ───
    # 🚨 Fix 64: UI가 stage/avg_price/unrealized_pnl 요구 = 대칭 필드 추가!
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
                "stage": int(getattr(si, "current_stage", 0) or 0),
                "avg_price": (
                    str(si.avg_entry_price) if si.avg_entry_price is not None else None
                ),
                "unrealized_pnl": (
                    str(si.unrealized_pnl) if si.unrealized_pnl is not None else "0"
                ),
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
    # 🚨 Fix 110 (2026-08-26): UI ↔ 워커 한도 불일치 해소! (헌법 6 단일 진실!)
    #   옛: sajangnim_top_short_daily_limit 만 직접 조회
    #       → 키가 없으면 UI 는 0 (= OFF 처럼 보임)
    #       → 그런데 워커는 fallback 체인(auto_bb_break_daily_limit → DEFAULT 20)
    #       → 화면은 「0 = 정지」인데 실제로는 20건씩 진입! (사장님 137건 사고!)
    #   신: 워커의 _get_daily_limit 을 그대로 재사용 = 화면 == 실제!
    #
    # 🎯 Fix 112 (2026-08-26 사장님 verbatim "일 20개로 하지말고 최대 20개"):
    #   의미 자체가 바뀜! 「하루 신규 건수」 → 「동시 보유 건수」
    #   UI 도 워커와 같은 함수(check_position_slot)를 써야 함 = 헌법 85!
    daily_limit = 0
    daily_used = 0
    try:
        from app.services.position_limit import get_max_concurrent, count_active_positions
        daily_limit, _lim_src = get_max_concurrent(db)
        daily_used = count_active_positions(db)     # = 지금 열려 있는 포지션!
    except Exception as e:
        logger.warning("[v219-monitoring+Fix112] 동시보유 상한 조회 실패: %s", e)

    # ─── 4) daily_used (오늘 v219 실행 개수 = KST 기준!) ───
    #    suggestion_type = "sajangnim_top_short" + executed_at 오늘 (KST)!
    #   ⚠️ Fix 112: daily_used 는 위에서 「동시 보유 수」로 이미 채워짐!
    #      아래는 참고용 「오늘 신규 진입 건수」 = today_entered 로 분리 보관.
    today_entered = 0
    try:
        from datetime import timedelta as _td
        now_utc = _dt.now(timezone.utc)
        # 🚨 Fix 110 (2026-08-26 CRITICAL): UI ↔ 워커 카운터 불일치 해소! (헌법 6 단일 진실!)
        #
        # 사장님 실측: UI 「오늘 자동 진입 137/0」 인데
        #             워커는 슬롯 여유가 있다고 판단해 계속 진입 가능 상태!
        #             = 사장님이 화면을 봐도 실제 상태를 알 수 없었음!
        #
        # 옛 UI 쿼리 (아래 주석 = 폐기!):
        #   suggestion_type == "sajangnim_top_short" 만  → 다른 SHORT 소스 누락
        #   status / execution_mode / side 필터 없음      → 미실행 제안까지 카운트
        #   outcome_status 필터 없음                      → 익절 성공 건도 카운트!
        #   KST 자정 고정                                 → 사장님 수동 리셋 무시
        #
        # 신: 워커의 _count_v219_used_slots 를 그대로 재사용!
        #     = 화면 숫자 == 워커 판정 근거 (100% 동일 진실!)
        #     사장님 사상: "익절 = 카운트 X (성공 = 재도전 가능!)" 도 자동 반영!
        from app.workers.auto_short_at_top_worker import _count_v219_used_slots
        today_entered = _count_v219_used_slots(db)
    except Exception as e:
        logger.warning("[v219-monitoring+Fix110] today_entered 집계 실패: %s", e)

    return {
        # ─── SHORT (기존, 호환성 유지!) ───
        "pump_top_alerts": pump_top_alerts,
        "monitoring_symbols": monitoring_symbols,
        "reentry_watch": reentry_watch,
        "active_count": active_count,
        "active_shorts": active_shorts,  # Fix 64: UI 대칭 = badge/목록 표시!
        # 🎯 Fix 112: daily_used = 「지금 동시 보유 중」 (하루 누적 X!)
        "daily_used": daily_used,
        "daily_limit": daily_limit,
        "remaining": max(0, daily_limit - daily_used),
        "limit_mode": "concurrent",        # UI 라벨 분기용 (하루 X = 동시!)
        "today_entered": today_entered,    # 참고: 오늘 신규 진입 건수
        # ─── LONG (신규, 사장님 신 사상!) ───
        "long_bottom_alerts": long_bottom_alerts,
        "monitoring_symbols_long": monitoring_symbols_long,
        "active_longs": active_longs,
        "reentry_watch_long": reentry_watch_long,
    }


# 🚨 v132 fix: /trigger-now, /briefing-now, /settings routes = 위로 이동!
# (specific routes MUST come BEFORE parametric routes!)

# ─────────────────────────────────────────────────────────────
# Fix 63 (2026-08-24): v219-monitoring 중복 정의 삭제 = silent bug 방지!
# 이전 line 1039~ 2차 정의 = FastAPI 첫 등록만 사용해서 dead code였음!
# 헌법 63 (함수 재정의 금지) 준수!
# 유지되는 정의 = line 761 `get_v219_monitoring` (활성!)
# ─────────────────────────────────────────────────────────────
