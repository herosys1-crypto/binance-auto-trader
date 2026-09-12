"""🎯 대기열 3A·3B·3D (2026-09-12 사장님 승인, docs/spec/PENDING_DEV_QUEUE_2026-09-12.md §3) — 가상매매가 채택한 진입 규칙의 「규칙 가족」.

가족 = (설정 {가족}_mode off|shadow|on · 템플릿 접두사 · strategy_type · 방향 · 가상 규칙 키 · 자리 필터 · 자본 · 손절 ROI · 전용 상한 · 쿨다운).
실행 = app/workers/rule_family_worker.py (60초). 이 모듈은 설정 · 자리/신선도 판정 · 손절 환산만 한다 (주문·Redis 없음).

## 신호 출처 = 가상매매 실시간 진입 행 (paper_trades, source=live) — 봉을 한 번 더 받지 않는다
  · 규칙 판정 · 감시 대상(당일 상승/하락 50 + 3·5일) · 자리 태그(UP24/DOWN24/UP35_DOWN24/LIVE_OK/MKT_*)가
    **측정한 바로 그 코드**(paper_trading.evaluate_rules · group_of)에서 나온다 → 측정과 실행이 갈라질 자리가 없다.
  · 가상매매가 15분마다 100~150 심볼 봉을 이미 받는다. 같은 봉을 또 받으면 요청 무게가 두 배다 (IP ban 418 전력).
  · 가상매매 모듈은 여전히 주문 경로를 import 하지 않는다 (이쪽이 DB 행을 읽을 뿐).
  · 한계: 가상매매가 멈추면 신호도 없다 → 사이클 기록·검사기 ⑧에 「마지막 가상 진입 시각」.
    같은 (심볼, 규칙) 가상 포지션이 열려 있는 동안에는 새 행이 안 생긴다 = 그동안 그 심볼 재신호 없음.

## 채택 근거 (가상 v2 · 2026-09-13 재측정 · 기준선 대비 Δ · 심볼 홀짝×시간 반쪽 CV 4조각)
  3A s2_hist_turn_down SHORT  UP24∪UP35_DOWN24  house Δ+0.54 4/4 (n=2051) · live Δ+1.38 4/4 (n=1247)
  3B bottom_331        LONG   LIVE_OK           house Δ+0.63 4/4 (n=2616) · live Δ+1.02 4/4 (n=1029)
       DOWN24 는 house +0.74 4/4 이지만 live −0.82 1/4, MKT_DOWN 은 house −1.09 0/4 → 두 엔진 모두 통과한 LIVE_OK 를 기본
  3D surge_start_346   LONG   DOWN24            house Δ+0.57 4/4 (n=895)  · live Δ+0.21 3/4 (n=425)
       UP24 는 house +0.04 2/4 · live −2.05 0/4 → 사양대로 제외
  실시간 발생률(9/10~9/12, 자리 통과): 3A ≈100/일 · 3B ≈100~140/일 · 3D ≈30~70/일 → 실제 진입 수는 전용 상한·쿨다운이 정한다.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)

FIX = "Q3"
MODES = ("off", "shadow", "on")
PLACE_TOKENS = ("ALL", "UP24", "DOWN24", "UP35_DOWN24", "MKT_UP", "MKT_DOWN", "LIVE_OK")   # = paper_trading.GROUP_KEYS
SWING_BARS = 8                  # 3A 대안 손절: 직전 완성봉 8개 고점 (사양 「8봉 고점」)
SWING_BUFFER_PCT = 1.0          # + 1% 가격 (사양 「+ 1% 가격」)


@dataclass(frozen=True)
class Family:
    key: str          # 설정 키 접두사
    rule: str         # 가상매매 규칙 키 (chart_learning.RULES)
    side: str
    prefix: str       # 템플릿 이름 접두사 (ilike 로 전용 슬롯을 센다)
    stype: str        # strategy_type
    label: str


FAMILIES: tuple[Family, ...] = (
    Family("rf_s2_short", "s2_hist_turn_down", "SHORT", "RF_S2SHORT", "rf_s2_hist_turn_down", "3A 반등 뒤 hist 꺾임 SHORT"),
    Family("rf_bottom_long", "bottom_331", "LONG", "RF_BOTTOM", "rf_bottom_331", "3B 저점 반전 LONG"),
    Family("rf_surge_long", "surge_start_346", "LONG", "RF_SURGESTART", "rf_surge_start_346", "3D 상승 초입 LONG (당일 하락50)"),
)
FAMILY_BY_KEY = {f.key: f for f in FAMILIES}
RF_STRATEGY_TYPES = frozenset(f.stype for f in FAMILIES)
RF_TEMPLATE_PREFIXES = tuple(f.prefix for f in FAMILIES)

# ───────── 설정 키 (key: (기본값, 설명, 출처)) ─────────
SETTINGS: dict[str, tuple[str, str, str]] = {
    "rf_s2_short_mode": ("shadow", "off | shadow(신호만 기록) | on(실주문)", "Claude가 정함 — 실자금은 사장님이 켠다"),
    "rf_s2_short_places": ("UP24,UP35_DOWN24", "자리 (가상매매 태그 그룹, 쉼표 = 또는)", "가상 v2 채택 자리 (Claude가 정함)"),
    "rf_s2_short_capital_usdt": ("10", "1회 진입 증거금", "사장님 1단계 10"),
    "rf_s2_short_sl_roi": ("25", "강제손절 ROI %", "실코드 새 전략 기본 −25 (Fix 362)"),
    "rf_s2_short_stop_mode": ("roi", "roi(위 ROI) | swing8(직전 8봉 고점 + 1% 가격, 켤 때 15m 봉 10개 조회)", "사양 후보 택1 (Claude가 정함)"),
    "rf_s2_short_max_concurrent": ("2", "전용 동시 보유 상한", "Claude가 정함"),
    "rf_s2_short_cooldown_hours": ("4", "심볼당 진입(그림자 기록 포함) 뒤 재신호 무시 시간", "Claude가 정함"),
    "rf_bottom_long_mode": ("shadow", "off | shadow | on", "Claude가 정함 — 실자금은 사장님이 켠다"),
    "rf_bottom_long_places": ("LIVE_OK", "자리", "가상 v2 두 엔진 모두 채택 (Claude가 정함)"),
    "rf_bottom_long_capital_usdt": ("10", "1회 진입 증거금", "사장님 1단계 10"),
    "rf_bottom_long_sl_roi": ("25", "강제손절 ROI %", "실코드 새 전략 기본 −25 (Fix 362)"),
    "rf_bottom_long_max_concurrent": ("2", "전용 동시 보유 상한", "Claude가 정함"),
    "rf_bottom_long_cooldown_hours": ("4", "심볼당 재신호 무시 시간", "Claude가 정함"),
    "rf_surge_long_mode": ("shadow", "off | shadow | on", "Claude가 정함 — 실자금은 사장님이 켠다"),
    "rf_surge_long_places": ("DOWN24", "자리", "사양 (DOWN24 만)"),
    "rf_surge_long_capital_usdt": ("10", "1회 진입 증거금", "사장님 1단계 10"),
    "rf_surge_long_sl_roi": ("25", "강제손절 ROI %", "실코드 새 전략 기본 −25 (Fix 362)"),
    "rf_surge_long_max_concurrent": ("2", "전용 동시 보유 상한", "Claude가 정함"),
    "rf_surge_long_cooldown_hours": ("4", "심볼당 재신호 무시 시간", "Claude가 정함"),
    "rf_allow_hedge": ("0", "같은 심볼 반대 방향에 살아 있는 전략(종류 무관)이 있으면 진입 안 함 · 1 = 허용",
                       "Claude가 정함 — managed_symbols allow_hedge=0 관례 (반박 검증 9/13)"),
    "rf_leverage": ("2", "레버리지", "사장님 기본 2x"),
    "rf_tp_percents": ("15,20,25,30", "TP1~4 ROI % (각 25% 청산)", "실코드 기본 TP1 15"),
    "rf_max_signal_age_min": ("20", "가상 진입 봉 마감 뒤 이보다 늦은 신호는 주문하지 않음(분)", "Claude가 정함"),
    "rf_max_drift_pct": ("1.0", "진입 봉 종가 대비 지금 가격 이동(가격 %) 상한 — 넘으면 주문하지 않음", "Claude가 정함"),
    "rf_stop_pct_min": ("0.3", "swing8 손절폭(가격 %) 하한 — 좁으면 ROI 손절로", "Claude가 정함"),
    "rf_stop_pct_max": ("15", "swing8 손절폭(가격 %) 상한 — 넓으면 ROI 손절로", "Claude가 정함"),
}


def setting(db: Any, key: str) -> str:
    """설정 실효값(문자열). 행 없음/실패 = 기본값."""
    default = SETTINGS[key][0]
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, key)
        if row is None or row.value is None or not str(row.value).strip():
            return default
        return str(row.value).strip()
    except Exception as e:  # noqa: BLE001
        logger.debug("[%s] %s 조회 실패 → 기본: %s", FIX, key, e)
        return default


def setting_float(db: Any, key: str) -> float:
    try:
        v = float(setting(db, key))
        return v if math.isfinite(v) else float(SETTINGS[key][0])
    except (TypeError, ValueError):
        return float(SETTINGS[key][0])


def mode_of(db: Any, fam_key: str) -> str:
    m = setting(db, f"{fam_key}_mode").lower()
    return m if m in MODES else SETTINGS[f"{fam_key}_mode"][0]


def _parse_places(raw: str) -> set[str]:
    return {x.strip().upper() for x in str(raw or "").replace("/", ",").split(",") if x.strip().upper() in PLACE_TOKENS}


def places_of(db: Any, fam_key: str) -> set[str]:
    key = f"{fam_key}_places"
    return _parse_places(setting(db, key)) or _parse_places(SETTINGS[key][0])


def tp_percents(db: Any) -> tuple[float, float, float, float]:
    default = tuple(float(x) for x in SETTINGS["rf_tp_percents"][0].split(","))
    try:
        v = tuple(float(x) for x in setting(db, "rf_tp_percents").split(","))
        if len(v) == 4 and all(0 < x <= 500 for x in v) and list(v) == sorted(v):
            return v  # type: ignore[return-value]
    except (TypeError, ValueError):
        pass
    return default  # type: ignore[return-value]


def signal_age_min(opened_at: datetime, now: datetime) -> float:
    if opened_at.tzinfo is None:
        opened_at = opened_at.replace(tzinfo=timezone.utc)
    return (now - opened_at).total_seconds() / 60.0


def price_move_pct(entry: float, price: float) -> float | None:
    """진입 봉 종가 대비 지금 가격 이동 크기(가격 %, 방향 무관). 값을 모르면 None."""
    try:
        e, p = float(entry), float(price)
    except (TypeError, ValueError):
        return None
    if e <= 0 or p <= 0:
        return None
    return abs(p / e - 1.0) * 100.0


def decide(db: Any, fam: Family, row: Mapping[str, Any], *, now: datetime) -> tuple[str, dict[str, Any]]:
    """주문·Redis 없이 판정되는 앞단. go | skip_side | skip_place | skip_stale."""
    from app.services.paper_trading import group_of
    groups = group_of(list(row.get("tags") or []))
    places = places_of(db, fam.key)
    det: dict[str, Any] = {"groups": groups, "places": sorted(places)}
    if str(row.get("side") or "").upper() != fam.side:
        return "skip_side", det
    if not (places & set(groups)):
        return "skip_place", det
    age = signal_age_min(row["opened_at"], now)
    det["age_min"] = round(age, 1)
    if age > setting_float(db, "rf_max_signal_age_min"):
        return "skip_stale", det
    return "go", det


def sl_price_pct(db: Any, fam: Family, leverage: float) -> float | None:
    """손절 ROI → 가격 % (create_surge_position 이 다시 × 레버리지로 ROI 를 넣는다)."""
    roi = setting_float(db, f"{fam.key}_sl_roi")
    if roi <= 0 or leverage <= 0:
        return None
    return roi / float(leverage)


def swing8_stop_pct(highs: Sequence[float], price: float, *, lo: float, hi: float) -> float | None:
    """3A 대안 손절 (SHORT): 직전 완성봉 8개 고점 × (1 + 1%) 까지의 가격 %. 봉 부족·범위 밖 = None (= ROI 손절로)."""
    if len(highs) < SWING_BARS or not price or price <= 0:
        return None
    stop = max(float(x) for x in highs[-SWING_BARS:]) * (1.0 + SWING_BUFFER_PCT / 100.0)
    pct = (stop / float(price) - 1.0) * 100.0
    return pct if lo <= pct <= hi else None
