"""🎯 대기열 3A·3B·3D (2026-09-12 사장님 승인, docs/spec/PENDING_DEV_QUEUE_2026-09-12.md §3) — 가상매매가 채택한 진입 규칙의 「규칙 가족」.
🗓 2026-09-15 사장님 「1 2 3 모두 분석해서 적당한 포지션 진입방법 … 10 100 200 … 모두 일최대 1개 … 언제든지 자동매매 할수 있게」:
   가상매매 규칙 12개 전부를 가족으로 등록 (후지모토·마하세븐은 자기 워커가 있어 제외) · 진입 방식 기본 = 분할 10/100/200 ·
   하루 최대 = app/services/auto_family_registry (daily_max_<가족키>, 기본 1). 근거 = docs/spec/AUTO_ENTRY_READY_2026-09-15.md.

가족 = (설정 {가족}_mode off|shadow|on · 템플릿 접두사 · strategy_type · 방향 · 가상 규칙 키 · 자리 필터 · 진입 방식 · 전용 상한 · 쿨다운).
실행 = app/workers/rule_family_worker.py (60초). 이 모듈은 설정 · 자리/신선도 판정 · 손절 환산만 한다 (주문·Redis 없음).

## 신호 출처 = 가상매매 실시간 진입 행 (paper_trades, source=live) — 봉을 한 번 더 받지 않는다
  · 규칙 판정 · 감시 대상(당일 상승/하락 50 + 3·5일) · 자리 태그(UP24/DOWN24/UP35_DOWN24/LIVE_OK/MKT_*)가
    **측정한 바로 그 코드**(paper_trading.evaluate_rules · group_of)에서 나온다 → 측정과 실행이 갈라질 자리가 없다.
  · 가상매매가 15분마다 100~150 심볼 봉을 이미 받는다. 같은 봉을 또 받으면 요청 무게가 두 배다 (IP ban 418 전력).
  · 한계: 가상매매가 멈추면 신호도 없다. 같은 (심볼, 규칙) 가상 포지션이 열려 있는 동안에는 새 행이 안 생긴다.

## 진입 방식 ({가족}_entry)
  split  (기본) 분할 10/100/200 — app/services/split_entry_executor (볼밴 분할 split_entry 경로) · rf_split_* 설정
  single        1회 진입 — surge_ladder_entry.create_surge_position · {가족}_capital_usdt · {가족}_sl_roi · rf_tp_percents
  실측 (2026-09-15, 가상 실시간 20,583건 × 15분봉 재생, 9/9~9/15 · USDT/건): 분할 TP1 5·손절 ROI 10 이 분할 변형 중 가장 안정.
  같은 방식의 무작위 기준선 대비(앞 반 / 뒤 반) — SHORT: off8 +1.0/+0.3 · wick_rev_short +0.5/+0.2 · s2_hist +0.2/+0.4 ·
  LONG: surge_start +2.1/−0.1 · pullback +1.1/−0.9. 나머지는 기준선 이하이거나 반쪽 부호가 갈린다. 6일 표본 = 시장 방향 영향 큼.

## 이전 채택 근거 (가상 v2 · 2026-09-13 재측정 · 기준선 대비 Δ · 심볼 홀짝×시간 반쪽 CV 4조각)
  3A s2_hist_turn_down SHORT  UP24∪UP35_DOWN24  house Δ+0.54 4/4 · live Δ+1.38 4/4
  3B bottom_331        LONG   LIVE_OK           house Δ+0.63 4/4 · live Δ+1.02 4/4
  3D surge_start_346   LONG   DOWN24            house Δ+0.57 4/4 · live Δ+0.21 3/4
  ⚠️ confirm_peak_111 · bottom_331 은 실매매 워커(급등 정점 SHORT · 저점 LONG)와 같은 계열 — 둘 다 켜면 같은 자리에 두 번 들어간다.
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
ENTRY_MODES = ("split", "single")
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
    label: str        # 화면 배지 · 로그 이름
    short: str = ""   # 배지 짧은 이름


FAMILIES: tuple[Family, ...] = (
    # 대기열 3 (2026-09-12) — 키·접두사·종류는 운영 행이 있어 바꾸지 않는다
    Family("rf_s2_short", "s2_hist_turn_down", "SHORT", "RF_S2SHORT", "rf_s2_hist_turn_down", "3A 반등 뒤 hist 꺾임 SHORT", "3A꺾임S"),
    Family("rf_bottom_long", "bottom_331", "LONG", "RF_BOTTOM", "rf_bottom_331", "3B 저점 반전 LONG", "3B저점L"),
    Family("rf_surge_long", "surge_start_346", "LONG", "RF_SURGESTART", "rf_surge_start_346", "3D 상승 초입 LONG (당일 하락50)", "3D초입L"),
    # 2026-09-15 추가 — 가상매매 나머지 규칙 (기본 shadow · 자리 ALL)
    Family("rf_confirm_peak", "confirm_peak_111", "SHORT", "RF_CONFPEAK", "rf_confirm_peak_111", "정점 확인 SHORT", "정점확인S"),
    Family("rf_toprev", "toprev_331", "SHORT", "RF_TOPREV", "rf_toprev_331", "정점 반전 SHORT", "정점반전S"),
    Family("rf_off8", "off8_267", "SHORT", "RF_OFF8", "rf_off8_267", "정점 대비 −8% SHORT", "−8%S"),
    Family("rf_s1_breakdown", "s1_breakdown", "SHORT", "RF_S1BREAK", "rf_s1_breakdown", "20봉 신저점 이탈 SHORT", "신저점S"),
    Family("rf_wick_short", "wick_rev_short_v220", "SHORT", "RF_WICKSHORT", "rf_wick_rev_short_v220", "윗꼬리 반전 SHORT", "윗꼬리S"),
    Family("rf_pullback_long", "pullback_331", "LONG", "RF_PULLBACK", "rf_pullback_331", "상승 중 조정 LONG", "조정L"),
    Family("rf_multiday_long", "multiday_rebound_352", "LONG", "RF_MULTIDAY", "rf_multiday_rebound_352", "다일 반등 LONG", "다일반등L"),
    Family("rf_l1_hist_long", "l1_hist_turn_up", "LONG", "RF_L1HIST", "rf_l1_hist_turn_up", "hist 상승 전환 LONG", "hist전환L"),
    Family("rf_wick_long", "wick_rev_long_v220", "LONG", "RF_WICKLONG", "rf_wick_rev_long_v220", "아래꼬리 반전 LONG", "아래꼬리L"),
)
FAMILY_BY_KEY = {f.key: f for f in FAMILIES}
RF_STRATEGY_TYPES = frozenset(f.stype for f in FAMILIES)
RF_TEMPLATE_PREFIXES = tuple(f.prefix for f in FAMILIES)

# ───────── 설정 키 (key: (기본값, 설명, 출처)) ─────────
SETTINGS: dict[str, tuple[str, str, str]] = {
    "rf_s2_short_mode": ("shadow", "off | shadow(신호만 기록) | on(실주문)", "Claude가 정함 — 실자금은 사장님이 켠다"),
    "rf_s2_short_places": ("UP24,UP35_DOWN24", "자리 (가상매매 태그 그룹, 쉼표 = 또는)", "가상 v2 채택 자리 (Claude가 정함)"),
    "rf_s2_short_capital_usdt": ("10", "단일 진입일 때 증거금", "사장님 1단계 10"),
    "rf_s2_short_sl_roi": ("25", "단일 진입일 때 강제손절 ROI %", "실코드 새 전략 기본 −25 (Fix 362)"),
    "rf_s2_short_stop_mode": ("roi", "단일 진입일 때 roi | swing8(직전 8봉 고점 + 1% 가격)", "사양 후보 택1 (Claude가 정함)"),
    "rf_s2_short_max_concurrent": ("2", "전용 동시 보유 상한", "Claude가 정함"),
    "rf_s2_short_cooldown_hours": ("4", "심볼당 진입(그림자 기록 포함) 뒤 재신호 무시 시간", "Claude가 정함"),
    "rf_bottom_long_mode": ("shadow", "off | shadow | on", "Claude가 정함 — 실자금은 사장님이 켠다"),
    "rf_bottom_long_places": ("LIVE_OK", "자리", "가상 v2 두 엔진 모두 채택 (Claude가 정함)"),
    "rf_bottom_long_capital_usdt": ("10", "단일 진입일 때 증거금", "사장님 1단계 10"),
    "rf_bottom_long_sl_roi": ("25", "단일 진입일 때 강제손절 ROI %", "실코드 새 전략 기본 −25 (Fix 362)"),
    "rf_bottom_long_max_concurrent": ("2", "전용 동시 보유 상한", "Claude가 정함"),
    "rf_bottom_long_cooldown_hours": ("4", "심볼당 재신호 무시 시간", "Claude가 정함"),
    "rf_surge_long_mode": ("shadow", "off | shadow | on", "Claude가 정함 — 실자금은 사장님이 켠다"),
    "rf_surge_long_places": ("DOWN24", "자리", "사양 (DOWN24 만)"),
    "rf_surge_long_capital_usdt": ("10", "단일 진입일 때 증거금", "사장님 1단계 10"),
    "rf_surge_long_sl_roi": ("25", "단일 진입일 때 강제손절 ROI %", "실코드 새 전략 기본 −25 (Fix 362)"),
    "rf_surge_long_max_concurrent": ("2", "전용 동시 보유 상한", "Claude가 정함"),
    "rf_surge_long_cooldown_hours": ("4", "심볼당 재신호 무시 시간", "Claude가 정함"),
    "rf_allow_hedge": ("0", "같은 심볼 반대 방향에 살아 있는 전략(종류 무관)이 있으면 진입 안 함 · 1 = 허용",
                       "Claude가 정함 — managed_symbols allow_hedge=0 관례 (반박 검증 9/13)"),
    "rf_leverage": ("2", "단일 진입 레버리지 (분할은 볼밴 분할과 같은 2)", "사장님 기본 2x"),
    "rf_tp_percents": ("15,20,25,30", "단일 진입 TP1~4 ROI % (각 25% 청산)", "실코드 기본 TP1 15"),
    "rf_max_signal_age_min": ("20", "가상 진입 봉 마감 뒤 이보다 늦은 신호는 주문하지 않음(분)", "Claude가 정함"),
    "rf_max_drift_pct": ("1.0", "진입 봉 종가 대비 지금 가격 이동(가격 %) 상한 — 넘으면 주문하지 않음", "Claude가 정함"),
    "rf_stop_pct_min": ("0.3", "swing8 손절폭(가격 %) 하한 — 좁으면 ROI 손절로", "Claude가 정함"),
    "rf_stop_pct_max": ("15", "swing8 손절폭(가격 %) 상한 — 넓으면 ROI 손절로", "Claude가 정함"),
    # 🗓 2026-09-15 분할 진입 (모든 가족 공통)
    "rf_split_capitals": ("10,100,200", "분할 1·2·3차 증거금 USDT", "사장님 2026-09-15 「10 100 200」"),
    "rf_split_steps": ("3,5,7", "분할 기준선 대비 심도 % (2·3차 = 1차 체결가 대비 약 2%씩)", "볼밴 분할과 같음"),
    "rf_split_sl_roi": ("10", "분할 평단 ROI 손절 % (가격상 2·3차 트리거보다 뒤 — 단 2·3차는 볼밴 분할 추가 게이트를 통과해야 들어가 1차만 든 채 손절될 수 있다)", "볼밴 분할과 같음 · 실측 A5/10"),
    "rf_split_tp1_pct": ("5", "분할 TP1 ROI % (TP2~4 = 2·3·4배, 25%씩)", "실측 A5/10 (TP1 15 + 손절 10 이 가장 나쁨)"),
    "rf_split_trailing_pct": ("3", "분할 TP1 뒤 고점 대비 회귀 % 잔량 청산", "볼밴 분할과 같음"),
}
for _f in FAMILIES[3:]:
    SETTINGS.update({
        f"{_f.key}_mode": ("shadow", "off | shadow | on", "Claude가 정함 — 실자금은 사장님이 켠다"),
        f"{_f.key}_places": ("ALL", "자리", "Claude가 정함 — 채택 자리 미측정이라 전체"),
        f"{_f.key}_capital_usdt": ("10", "단일 진입일 때 증거금", "사장님 1단계 10"),
        f"{_f.key}_sl_roi": ("25", "단일 진입일 때 강제손절 ROI %", "실코드 새 전략 기본 −25 (Fix 362)"),
        f"{_f.key}_max_concurrent": ("1", "전용 동시 보유 상한", "Claude가 정함"),
        f"{_f.key}_cooldown_hours": ("4", "심볼당 재신호 무시 시간", "Claude가 정함"),
    })
for _f in FAMILIES:
    SETTINGS[f"{_f.key}_entry"] = ("split", "split(분할 10/100/200, rf_split_*) | single(1회 진입)",
                                   "사장님 2026-09-15 「10 100 200」 · 실측 분할 TP1 5·손절 10")
    # 🎯 Fix 375 (2026-09-17 사장님 「차트를 분석하고 진입할수 있어야지」): 차트 자리 게이트 — app/services/entry_conditions
    SETTINGS[f"{_f.key}_chart_gate"] = ("on", "off | shadow(판정만 기록) | on(차트 자리가 아니면 진입 안 함)",
                                        "Claude가 정함 — 가상 22,652건 재계산 · 사전등록 이후 검증 통과 (진입을 줄이기만 한다)")
SETTINGS["entry_chart_gate_params"] = ("", "차트 게이트 숫자 JSON (비우면 기본: SHORT 16시간 고점 −3% 이내·일봉 UP 아님 / "
                                           "LONG 24h −5% 이하 또는 5분 고점 대비 −4% 이하)", "Claude가 정함 — 분석 값 그대로")


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


def chart_gate_of(db: Any, fam_key: str) -> str:
    m = setting(db, f"{fam_key}_chart_gate").lower()
    return m if m in ("off", "shadow", "on") else SETTINGS[f"{fam_key}_chart_gate"][0]


def entry_of(db: Any, fam_key: str) -> str:
    m = setting(db, f"{fam_key}_entry").lower()
    return m if m in ENTRY_MODES else SETTINGS[f"{fam_key}_entry"][0]


def split_config(db: Any) -> tuple[list, list, Any, float, float, str]:
    """(자본 3칸, 심도 3칸, 손절 ROI, TP1, 트레일링, 메모) — 손상·범위 밖·정합성 실패 = 기본값."""
    from app.services.split_entry_executor import parse_config
    caps, steps, sl, note = parse_config(setting(db, "rf_split_capitals"), setting(db, "rf_split_steps"), setting(db, "rf_split_sl_roi"))
    tp1 = setting_float(db, "rf_split_tp1_pct")
    tp1 = tp1 if 1 <= tp1 <= 50 else float(SETTINGS["rf_split_tp1_pct"][0])
    trail = setting_float(db, "rf_split_trailing_pct")
    trail = trail if 0.5 <= trail <= 20 else float(SETTINGS["rf_split_trailing_pct"][0])
    return caps, steps, sl, tp1, trail, note


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
