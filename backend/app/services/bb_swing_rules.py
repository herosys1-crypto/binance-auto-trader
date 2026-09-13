"""🌊 볼밴 스윙 (2026-09-14 사장님) — 진입 판정 순수 함수 + 설정. 워커 = app/workers/bb_swing_worker.py.

사장님 verbatim (2026-09-14):
  "볼밴로직은 상승중인 차트와 보조지표일때 볼밴상단위로 올라가고 보조지표가 고점신호인때 숏을 분할진입하고
   모든집입이 실패해서 모두 진입해고도 -10% 손실이면 청산하고 이익이 발행하면 빠른 tp1 부터 분할 익절하는
   시스템으로 전략인트턴스를 구성하면 될것 같아
   상승중 볼밴하단을 지지하면 다시 롱으로 같은 방식으로 전환하는 스윙자동매매를 하고 싶어 전략을 만들어줘"

규칙 (전부 **완성된 15분봉**, 흐름은 **완성된 4시간봉**):
  상승중  = 4H EMA20 > EMA50                                        (bb_swing_trend=ema)
  SHORT   = 15m 종가가 상단 밖 N봉 연속 + 그 구간 최고 종가에서 꺾임(지금 종가 < 최고)
            + RSI 고점 신호(직전 3봉 최고 ≥ 70 이고 지금 하락)          (bb_swing_short_indicator=rsi)
  LONG    = 15m 저가가 하단(+허용 %)에 닿고 종가는 하단 위 = 「하단 지지」 (선택: RSI 저점 신호)
  분할    = 볼밴 분할(split_entry)과 같은 실행 경로 — 1차 시장가 · 2·3차 실체결가 재앵커 · 평단 ROI 손절 전량 ·
            TP1 부터 25%씩 · 트레일링. 손절은 계산상 3차까지 체결된 뒤에만 닿는다(check_no_dead_stage 로 매 사이클 검산)
            = 사장님 「모두 진입하고도 -10% 손실이면 청산」.
  전환    = 반대 신호가 오면 같은 가족의 반대 포지션 잔량을 청산하고 새 방향으로 진입 (bb_swing_flip_close=1).

실측 (2026-09-14, docs/spec/BB_SWING_STRATEGY_2026-09-14.md):
  · MACD 는 고점 신호로 못 쓴다 — 상단 밖에서 꺾인 봉 271건 중 히스토그램 하락 **0건** (걸면 진입이 구조적으로 불가능).
  · SHORT 는 모든 변형이 적자, LONG 하단 지지는 흑자지만 뒷기간이 약하다 → 기본 shadow (주문 없음).
"""
from __future__ import annotations

import logging
import math
from decimal import Decimal
from typing import Any, Sequence

logger = logging.getLogger(__name__)

FIX = "BBSWING"
STRATEGY_TYPE = "bb_swing"
TEMPLATE_PREFIX = "BBSWING_"
LEVERAGE = 2                         # 볼밴 분할과 같음 (pump_split LEVERAGE)
MODES = ("off", "shadow", "on")
INDICATORS = ("rsi", "none")         # macd 는 넣지 않는다 — 위 실측(0/271)
BB_N, BB_K, RSI_N = 20, 2.0, 14
EMA_FAST, EMA_SLOW = 20, 50
MIN_15M_BARS = 40
MIN_4H_BARS = EMA_SLOW + 10

# key: (기본값, 뜻, 출처)
SETTINGS: dict[str, tuple[str, str, str]] = {
    "bb_swing_mode": ("shadow", "off | shadow(신호만 기록) | on(실주문)", "Claude가 정함 — 실자금은 사장님이 켠다"),
    "bb_swing_sides": ("SHORT,LONG", "허용 방향", "사장님 (숏·롱 스윙)"),
    "bb_swing_top_n": ("40", "감시 종목 = 거래대금 상위 N", "Claude가 정함"),
    "bb_swing_trend": ("ema", "상승중 판정: ema(4H EMA20>EMA50) | none", "Claude가 정함 (4H = 흐름)"),
    "bb_swing_short_persist": ("2", "SHORT: 15m 상단 밖 연속 봉수 (최소 2)", "Claude가 정함"),
    "bb_swing_short_indicator": ("rsi", "SHORT 고점 신호: rsi | none", "사장님 「보조지표 고점신호」 · 지표 선택은 Claude가 정함"),
    "bb_swing_rsi_high": ("70", "RSI 고점 기준 (직전 3봉 최고 ≥ 이 값 + 지금 하락)", "Claude가 정함"),
    "bb_swing_long_indicator": ("none", "LONG 저점 신호: rsi | none", "Claude가 정함 — 백테스트상 지표를 더하면 건당 수익 감소"),
    "bb_swing_rsi_low": ("35", "RSI 저점 기준 (직전 3봉 최저 ≤ 이 값 + 지금 상승)", "Claude가 정함"),
    "bb_swing_support_tol_pct": ("0", "하단 지지 = 저가 ≤ 하단 × (1 + 이 %) 이고 종가 > 하단", "Claude가 정함 — 백테스트와 같은 0 (0.2 는 검증 안 된 신호가 66%)"),
    "bb_swing_capitals": ("100,200,300", "1·2·3차 증거금 USDT", "볼밴 분할과 같음 (사장님 8/27)"),
    "bb_swing_steps": ("3,5,7", "기준선 대비 1·2·3차 심도 % (2·3차는 1차 체결가 기준 간격으로 재앵커)", "볼밴 분할과 같음"),
    "bb_swing_sl_roi": ("10", "평단 ROI 손절 % (전량)", "사장님 「-10% 손실이면 청산」"),
    "bb_swing_tp1_pct": ("5", "TP1 ROI % — TP2~4 = 2·3·4배, 25%씩", "볼밴 분할 「빠른 TP1」 5% (Fix 205)"),
    "bb_swing_trailing_pct": ("3", "TP1 뒤 고점 대비 회귀 % 에 잔량 청산", "볼밴 분할과 같음"),
    "bb_swing_max_concurrent": ("2", "전용 동시 보유 상한 (0 = 진입 끔)", "Claude가 정함"),
    "bb_swing_cycles_per_day": ("2", "심볼·방향당 24h 실진입 상한", "볼밴 분할 Fix 218 과 같음"),
    "bb_swing_flip_close": ("1", "반대 신호에 같은 가족 반대 포지션 잔량 청산 (1 = 전환)", "사장님 「다시 롱으로 전환」"),
}


# ── 설정 읽기 (행 없음·손상·범위 밖 = 기본값) ─────────────────────────────
def setting(db, key: str) -> str:
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


def setting_float(db, key: str, lo: float, hi: float) -> float:
    default = float(SETTINGS[key][0])
    try:
        v = float(setting(db, key))
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) and lo <= v <= hi else default


def setting_int(db, key: str, lo: int, hi: int) -> int:
    return int(setting_float(db, key, lo, hi))


def mode_of(db) -> str:
    m = setting(db, "bb_swing_mode").lower()
    return m if m in MODES else SETTINGS["bb_swing_mode"][0]


def sides_of(db) -> set[str]:
    return {s.strip().upper() for s in setting(db, "bb_swing_sides").split(",") if s.strip().upper() in ("LONG", "SHORT")}


def indicator_of(db, key: str) -> str:
    v = setting(db, key).lower()
    return v if v in INDICATORS else SETTINGS[key][0]


def tp_percents(tp1: float) -> list[float]:
    return [float(tp1) * k for k in (1, 2, 3, 4)]


# ── 지표 ─────────────────────────────────────────────────────────────────
def ema(v: Sequence[float], n: int) -> list[float]:
    k = 2.0 / (n + 1)
    out: list[float] = []
    e: float | None = None
    for x in v:
        e = float(x) if e is None else float(x) * k + e * (1 - k)
        out.append(e)
    return out


def rsi(closes: Sequence[float], n: int = RSI_N) -> list[float | None]:
    """Wilder RSI. 앞 n 봉은 None."""
    c = [float(x) for x in closes]
    out: list[float | None] = [None] * len(c)
    g = l = 0.0
    for i in range(1, len(c)):
        d = c[i] - c[i - 1]
        up, dn = max(d, 0.0), max(-d, 0.0)
        if i <= n:
            g += up / n
            l += dn / n
        else:
            g = (g * (n - 1) + up) / n
            l = (l * (n - 1) + dn) / n
        if i >= n:
            out[i] = 100.0 if l == 0 else 100.0 - 100.0 / (1.0 + g / l)
    return out


def bands(closes: Sequence[float], n: int = BB_N, k: float = BB_K) -> tuple[list, list, list]:
    """(중단, 상단, 하단). 모표준편차 — 차트 볼린저와 같은 정의. 앞 n-1 봉은 None."""
    c = [float(x) for x in closes]
    mid: list[float | None] = [None] * len(c)
    up, lo = mid[:], mid[:]
    for i in range(n - 1, len(c)):
        w = c[i - n + 1:i + 1]
        m = sum(w) / n
        sd = (sum((x - m) ** 2 for x in w) / n) ** 0.5
        mid[i], up[i], lo[i] = m, m + k * sd, m - k * sd
    return mid, up, lo


# ── 판정 ─────────────────────────────────────────────────────────────────
def uptrend_4h(closes_4h: Sequence[float]) -> tuple[bool, str]:
    """상승중 = 완성된 4H 종가의 EMA20 > EMA50 (지속 상태 = EMA 배열)."""
    c = [float(x) for x in closes_4h]
    if len(c) < MIN_4H_BARS:
        return False, f"4H 봉 부족({len(c)}/{MIN_4H_BARS})"
    f, s = ema(c, EMA_FAST)[-1], ema(c, EMA_SLOW)[-1]
    return f > s, f"4H EMA{EMA_FAST} {f:.6g} {'>' if f > s else '≤'} EMA{EMA_SLOW} {s:.6g}"


def _rsi_turn(closes: Sequence[float], *, top: bool, level: float) -> tuple[bool, str]:
    r = rsi(closes)
    i = len(r) - 1
    prev = [x for x in r[max(0, i - 3):i] if x is not None]
    if len(prev) < 3 or r[i] is None or r[i - 1] is None:
        return False, "RSI 계산 봉 부족"
    if top:
        ok = max(prev) >= level and r[i] < r[i - 1]
        return ok, f"RSI 직전 최고 {max(prev):.1f} (기준 {level:g}) → 지금 {r[i]:.1f} {'하락' if r[i] < r[i - 1] else '상승'}"
    ok = min(prev) <= level and r[i] > r[i - 1]
    return ok, f"RSI 직전 최저 {min(prev):.1f} (기준 {level:g}) → 지금 {r[i]:.1f} {'상승' if r[i] > r[i - 1] else '하락'}"


def short_signal(closes: Sequence[float], *, persist: int = 2, indicator: str = "rsi",
                 rsi_high: float = 70.0) -> tuple[Decimal | None, str, dict[str, Any]]:
    """(기준선 = 판정봉 상단, 사유, 상세). 미충족 = 기준선 None. closes = **완성봉만**."""
    c = [float(x) for x in closes]
    d: dict[str, Any] = {}
    if len(c) < MIN_15M_BARS:
        return None, f"15m 봉 부족({len(c)})", d
    _mid, up, _lo = bands(c)
    i = len(c) - 1
    run, x = 0, i
    while x >= 0 and up[x] is not None and c[x] > up[x]:
        run += 1
        x -= 1
    need = max(int(persist), 2)          # 밖 1봉으로는 「최고점에서 꺾임」을 말할 수 없다
    d.update(run=run, need=need, close=c[i], upper=up[i])
    if run < need:
        return None, f"상단 밖 {run}봉 (필요 {need})", d
    ext = max(c[i - run + 1:i + 1])
    d["extreme"] = ext
    if not c[i] < ext:
        return None, f"상단 밖 {run}봉 · 최고점 갱신 중 (종가 {c[i]:g} = 최고)", d
    if indicator == "rsi":
        ok, why = _rsi_turn(c, top=True, level=rsi_high)
        d["rsi"] = why
        if not ok:
            return None, f"상단 밖 {run}봉 꺾임 · 고점 신호 없음 ({why})", d
    return Decimal(str(up[i])), (
        f"🎯 상단 밖 {run}봉 → 최고 {ext:g} 에서 꺾임 (종가 {c[i]:g})" + (f" · {d['rsi']}" if "rsi" in d else "")
    ), d


def long_signal(closes: Sequence[float], lows: Sequence[float], *, tol_pct: float = 0.0,
                indicator: str = "none", rsi_low: float = 35.0) -> tuple[Decimal | None, str, dict[str, Any]]:
    """(기준선 = 판정봉 하단, 사유, 상세). closes·lows = **완성봉만**, 길이 같아야 한다."""
    c = [float(x) for x in closes]
    lw = [float(x) for x in lows]
    d: dict[str, Any] = {}
    if len(c) < MIN_15M_BARS or len(lw) != len(c):
        return None, f"15m 봉 부족/길이 불일치({len(c)}/{len(lw)})", d
    _mid, _up, lo = bands(c)
    i = len(c) - 1
    line = lo[i] * (1 + float(tol_pct) / 100.0)
    d.update(low=lw[i], close=c[i], lower=lo[i], touch_line=line)
    if not lw[i] <= line:
        return None, f"하단 미접촉 (저가 {lw[i]:g} > {line:g})", d
    if not c[i] > lo[i]:
        return None, f"하단 아래 마감 (종가 {c[i]:g} ≤ 하단 {lo[i]:g}) = 지지 아님", d
    if indicator == "rsi":
        ok, why = _rsi_turn(c, top=False, level=rsi_low)
        d["rsi"] = why
        if not ok:
            return None, f"하단 지지 · 저점 신호 없음 ({why})", d
    return Decimal(str(lo[i])), (
        f"🎯 하단 지지 (저가 {lw[i]:g} ≤ 하단 {lo[i]:g}+{float(tol_pct):g}% · 종가 {c[i]:g} 위)"
        + (f" · {d['rsi']}" if "rsi" in d else "")
    ), d
