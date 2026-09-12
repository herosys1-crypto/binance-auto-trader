"""🎯 Fix 368 (2026-09-12) — 외부 전략 2종을 우리 시스템에 얹는다 (사장님 「이 내용을 우리 시스템 로직에 반영해서 운영할 수 있게」).

① 후지모토 시게루 「MACD + RSI + 일목균형표 3역 호전」 (rufu_trading_strategy.md)
   1차 10%: RSI14 가 30 아래로 갔다가 다시 30 위로 복귀
   2차 20%: 상승 다이버전스(가격 저점 하락 · RSI 저점 상승) + MACD 가 시그널을 **영선 아래에서** 골든크로스
   3차 70%: 전환선(9)이 기준선(26)을 상향 돌파 + 종가가 구름대 위 + 후행스팬(종가 > 26봉 전 종가)
   SHORT 는 거울: 70 아래로 꺾임 / 하락 다이버전스 + 데드크로스 + RSI<50 / 구름대 하단 이탈 + 전환선 하향 돌파
   2% 룰: 한 거래의 최대 손실 ≤ 총자산 × 2%  →  최대 진입금액 = 총자산×0.02 ÷ 손절폭(%)
② 마하세븐(한봉호) 「이동평균선 속임수 돌파」 (mach7_ma_strategy.md)
   LONG : 200선 우상향 + 30선을 잠깐 깼다가 **2봉 연속** 30선 위 마감 + 30선 기울기 필터. 손절 = 함정 최저점
   SHORT: 200선 우하향 + 30선을 잠깐 뚫었다가 2봉 연속 30선 아래 마감. 손절 = 함정 최고점

우리 시스템으로 옮길 때 정한 것 (전부 설정 키, 「Claude가 정함」 표시):
  · 봉 = 15분 (사장님 사상: 15분 = 진입 타이밍). 출처는 주식 일봉이라 「30일선/200일선」의 「일」은 그대로 못 옮긴다 → 봉 수 30/200 만 유지.
  · 「30선 각도 30도 이상」은 차트 배율에 따라 달라 값이 없다 → 「30선 5봉 기울기 %」(mach7_min_slope_pct) 로 대체, 가상매매로 보정.
  · 진입 크기: 출처는 총자산 비율(10/20/70%)인데 실자금에 그대로 쓰면 크므로 「가족 배정액」(fujimoto_total_alloc_usdt) 의 10/20/70% 를
    쓰고, 그 위에 2% 룰 상한을 건다. 2·3차는 같은 인스턴스에 「포지션 추가」(preserve) 로 얹는다 (우리 단계 워커·피라미딩은 안 건드린다).
  · 손절은 가격 기준(함정 극값 / 최근 스윙) → force_sl_roi_override 로 환산 (surge_peak_ladder.sl_roi_for_price_pct).
  · 기본 모드 **shadow** (신호만 기록, 주문 없음). 사장님이 `fujimoto_mode=on` / `mach7_mode=on` 으로 켠다.
  · 가상매매(paper_trading) 규칙 레지스트리에 8개 규칙을 등록해 자리별 Δ·CV 를 잰다 (chart_learning.RULES).

주문을 내는 코드는 전부 이미 검증된 경로를 재사용한다: surge_ladder_entry.create_surge_position (1단계 템플릿 + MARKET + 손절/TP 세팅 +
킬스위치·ban·잔액·중복·전용 슬롯 가드) 와 ExecutionService.add_position_now (추가). 이 모듈은 **판정과 크기 계산만** 한다.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Sequence

logger = logging.getLogger(__name__)

FIX = "Fix368"

# ───────── 출처 숫자 (verbatim) ─────────
RSI_N = 14
RSI_OVERSOLD = 30.0
RSI_OVERBOUGHT = 70.0
RSI_MID = 50.0
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
ICHI_TENKAN, ICHI_KIJUN, ICHI_SENKOU_B, ICHI_SHIFT = 9, 26, 52, 26
FUJIMOTO_RATIOS = (10.0, 20.0, 70.0)          # 1:2:7 분할
FUJIMOTO_RISK_PCT = 2.0                        # 2% 룰
MACH7_MA_SHORT, MACH7_MA_LONG = 30, 200
MACH7_CONFIRM_BARS = 2                         # 「캔들 2개 연속」
MACH7_TREND_LOOKBACK = 5                       # 슈도코드 ma_long[-1] > ma_long[-5]
MACH7_STOP_BARS = 3                            # 슈도코드 min(low[-3:]) / max(high[-3:])

# ───────── 설정 키 (key: (기본값, 설명, 출처)) ─────────
SETTINGS: dict[str, tuple[str, str, str]] = {
    "fujimoto_mode": ("shadow", "off | shadow(신호만 기록) | on(실주문)", "Claude가 정함 — 실자금은 사장님이 켠다"),
    "fujimoto_sides": ("LONG,SHORT", "허용 방향", "출처(양방향)"),
    "fujimoto_total_alloc_usdt": ("100", "가족 배정액(증거금) — 1·2·3차 = 10/20/70%", "Claude가 정함"),
    "fujimoto_stage_ratios": ("10,20,70", "1:2:7 분할 비율(%)", "출처 verbatim"),
    "fujimoto_risk_pct": ("2", "2% 룰 — 한 거래 최대 손실 ≤ 총자산 × 이 %", "출처 verbatim"),
    "fujimoto_max_concurrent": ("2", "전용 동시 보유 상한", "Claude가 정함"),
    "fujimoto_swing_lookback": ("20", "1차 손절 = 최근 N봉 스윙 저점/고점", "Claude가 정함 (출처 「최근 지지/저항」)"),
    "fujimoto_div_lookback": ("30", "다이버전스 비교 창(봉)", "Claude가 정함"),
    "fujimoto_cooldown_hours": ("4", "심볼당 진입 뒤 재신호 무시 시간", "Claude가 정함"),
    "mach7_mode": ("shadow", "off | shadow | on", "Claude가 정함 — 실자금은 사장님이 켠다"),
    "mach7_sides": ("LONG,SHORT", "허용 방향", "출처(양방향)"),
    "mach7_capital_usdt": ("50", "1회 진입 증거금(USDT)", "Claude가 정함"),
    "mach7_risk_pct": ("2", "2% 룰 상한(출처는 손절가만 정함 → 같은 룰을 상한으로)", "Claude가 정함"),
    "mach7_max_concurrent": ("2", "전용 동시 보유 상한", "Claude가 정함"),
    "mach7_min_slope_pct": ("0.5", "LONG 만: 30선 5봉 기울기 % 하한 (출처 「각도 30도」 대체)", "Claude가 정함 — 가상매매로 보정"),
    "mach7_cooldown_hours": ("4", "심볼당 진입 뒤 재신호 무시 시간", "Claude가 정함"),
    "ext_interval": ("15m", "판정 봉", "Claude가 정함 (사장님 사상: 15분 = 타이밍)"),
    "ext_universe_top_n": ("60", "거래대금 상위 N 심볼만 감시", "Claude가 정함"),
    "ext_min_quote_volume": ("5000000", "24h 거래대금 하한(USDT)", "Claude가 정함"),
    "ext_stop_pct_min": ("0.3", "손절폭(가격 %) 하한 — 너무 좁은 손절은 스프레드에 죽는다", "Claude가 정함"),
    "ext_stop_pct_max": ("15", "손절폭(가격 %) 상한", "Claude가 정함"),
    "ext_leverage": ("2", "레버리지", "사장님 기본 2x"),
}
FUJIMOTO_PREFIX, FUJIMOTO_TYPE = "FUJIMOTO", "fujimoto_3stage"
MACH7_PREFIX, MACH7_TYPE = "MACH7", "mach7_ma_trap"
MODES = ("off", "shadow", "on")


def setting(db, key: str) -> str:
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


def setting_float(db, key: str) -> float:
    try:
        v = float(setting(db, key))
        return v if math.isfinite(v) else float(SETTINGS[key][0])
    except (TypeError, ValueError):
        return float(SETTINGS[key][0])


def mode_of(db, key: str) -> str:
    m = setting(db, key).lower()
    return m if m in MODES else SETTINGS[key][0]


def sides_of(db, key: str) -> set[str]:
    return {s.strip().upper() for s in setting(db, key).split(",") if s.strip().upper() in ("LONG", "SHORT")}


def stage_ratios(db) -> tuple[float, float, float]:
    try:
        parts = [float(x) for x in setting(db, "fujimoto_stage_ratios").split(",")]
        if len(parts) == 3 and all(p > 0 for p in parts):
            return parts[0], parts[1], parts[2]
    except ValueError:
        pass
    return FUJIMOTO_RATIOS


# ───────── 지표 (순수 함수) ─────────
def sma(v: Sequence[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(v)
    s = 0.0
    for i, x in enumerate(v):
        s += float(x)
        if i >= n:
            s -= float(v[i - n])
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(v: Sequence[float], n: int) -> list[float]:
    if not v:
        return []
    k = 2.0 / (n + 1)
    out = [float(v[0])]
    for x in v[1:]:
        out.append(out[-1] + k * (float(x) - out[-1]))
    return out


def macd_lines(c: Sequence[float]) -> tuple[list[float], list[float], list[float]]:
    """(macd, signal, hist). 35봉 미만이면 전부 0 (판정은 j 로 막는다)."""
    if len(c) < MACD_SLOW + MACD_SIGNAL:
        z = [0.0] * len(c)
        return z, list(z), list(z)
    m = [a - b for a, b in zip(ema(c, MACD_FAST), ema(c, MACD_SLOW))]
    s = ema(m, MACD_SIGNAL)
    return m, s, [a - b for a, b in zip(m, s)]


def rsi(c: Sequence[float], n: int = RSI_N) -> list[float | None]:
    out: list[float | None] = [None] * len(c)
    if len(c) <= n:
        return out
    g = lo = 0.0
    for i in range(1, n + 1):
        d = float(c[i]) - float(c[i - 1])
        g += max(d, 0.0)
        lo += max(-d, 0.0)
    ag, al = g / n, lo / n
    out[n] = 100.0 - 100.0 / (1.0 + (ag / al if al else 1e9))
    for i in range(n + 1, len(c)):
        d = float(c[i]) - float(c[i - 1])
        ag = (ag * (n - 1) + max(d, 0.0)) / n
        al = (al * (n - 1) + max(-d, 0.0)) / n
        out[i] = 100.0 - 100.0 / (1.0 + (ag / al if al else 1e9))
    return out


def _mid_hl(h: Sequence[float], lo: Sequence[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(h)
    for i in range(n - 1, len(h)):
        out[i] = (max(h[i - n + 1:i + 1]) + min(lo[i - n + 1:i + 1])) / 2.0
    return out


def ichimoku(h: Sequence[float], lo: Sequence[float]) -> dict[str, list[float | None]]:
    """전환선(9) · 기준선(26) · 선행스팬 A/B (계산 시점 값; 구름은 26봉 앞에 그려지므로 cloud_at 이 되돌려 읽는다)."""
    tenkan = _mid_hl(h, lo, ICHI_TENKAN)
    kijun = _mid_hl(h, lo, ICHI_KIJUN)
    span_a: list[float | None] = [None if (t is None or k is None) else (t + k) / 2.0 for t, k in zip(tenkan, kijun)]
    span_b = _mid_hl(h, lo, ICHI_SENKOU_B)
    return {"tenkan": tenkan, "kijun": kijun, "span_a": span_a, "span_b": span_b}


def cloud_at(ichi: dict[str, list[float | None]], j: int) -> tuple[float, float] | None:
    """j 봉 위에 그려진 구름 (26봉 전에 계산된 선행스팬 A/B) 의 (상단, 하단)."""
    i = j - ICHI_SHIFT
    if i < 0:
        return None
    a, b = ichi["span_a"][i], ichi["span_b"][i]
    if a is None or b is None:
        return None
    return max(a, b), min(a, b)


@dataclass
class Ind:
    c: Sequence[float]
    h: Sequence[float]
    l: Sequence[float]
    rsi: Sequence[float | None]
    macd: Sequence[float]
    sig: Sequence[float]
    tenkan: Sequence[float | None]
    kijun: Sequence[float | None]
    ichi: dict[str, list[float | None]]
    sma_s: Sequence[float | None]
    sma_l: Sequence[float | None]


def compute(c: Sequence[float], h: Sequence[float], lo: Sequence[float], *, rsi14: Sequence[float | None] | None = None,
            ma_short: int = MACH7_MA_SHORT, ma_long: int = MACH7_MA_LONG) -> Ind:
    m, s, _ = macd_lines(c)
    ic = ichimoku(h, lo)
    return Ind(c=c, h=h, l=lo, rsi=(rsi14 if rsi14 is not None else rsi(c)), macd=m, sig=s,
               tenkan=ic["tenkan"], kijun=ic["kijun"], ichi=ic, sma_s=sma(c, ma_short), sma_l=sma(c, ma_long))


# ───────── 다이버전스 ─────────
def _argext(v: Sequence[float], a: int, b: int, *, lowest: bool) -> int:
    idx = a
    for i in range(a, b):
        if (v[i] < v[idx]) if lowest else (v[i] > v[idx]):
            idx = i
    return idx


def bullish_divergence(c: Sequence[float], r: Sequence[float | None], j: int, lookback: int) -> bool:
    """가격 저점은 낮아졌는데 RSI 저점은 높아졌다 (창을 반으로 갈라 각 반쪽의 최저점을 비교)."""
    if j < lookback or lookback < 4:
        return False
    a0, a1 = j - lookback, j - lookback // 2
    i1, i2 = _argext(c, a0, a1, lowest=True), _argext(c, a1, j + 1, lowest=True)
    if r[i1] is None or r[i2] is None:
        return False
    return c[i2] < c[i1] and r[i2] > r[i1]


def bearish_divergence(c: Sequence[float], r: Sequence[float | None], j: int, lookback: int) -> bool:
    if j < lookback or lookback < 4:
        return False
    a0, a1 = j - lookback, j - lookback // 2
    i1, i2 = _argext(c, a0, a1, lowest=False), _argext(c, a1, j + 1, lowest=False)
    if r[i1] is None or r[i2] is None:
        return False
    return c[i2] > c[i1] and r[i2] < r[i1]


# ───────── 후지모토 3역 호전 ─────────
def fujimoto_stages(ind: Ind, j: int, side: str, *, div_lookback: int = 30) -> dict[int, bool]:
    """j 봉(완성봉)에서 1·2·3차 조건이 각각 성립하는가. 데이터가 모자라면 전부 False."""
    out = {1: False, 2: False, 3: False}
    r, c = ind.rsi, ind.c
    if j < ICHI_SENKOU_B + ICHI_SHIFT or j >= len(c) or r[j] is None or r[j - 1] is None:
        return out
    m, s = ind.macd, ind.sig
    t, k = ind.tenkan, ind.kijun
    cloud = cloud_at(ind.ichi, j)
    if side == "LONG":
        out[1] = r[j - 1] < RSI_OVERSOLD <= r[j]
        out[2] = bullish_divergence(c, r, j, div_lookback) and m[j - 1] <= s[j - 1] and m[j] > s[j] and m[j] < 0
        out[3] = (t[j - 1] is not None and k[j - 1] is not None and t[j] is not None and k[j] is not None
                  and t[j - 1] <= k[j - 1] and t[j] > k[j] and cloud is not None and c[j] > cloud[0]
                  and c[j] > c[j - ICHI_SHIFT])
    else:
        out[1] = r[j - 1] > RSI_OVERBOUGHT >= r[j]
        out[2] = bearish_divergence(c, r, j, div_lookback) and m[j - 1] >= s[j - 1] and m[j] < s[j] and r[j] < RSI_MID
        out[3] = (t[j - 1] is not None and k[j - 1] is not None and t[j] is not None and k[j] is not None
                  and t[j - 1] >= k[j - 1] and t[j] < k[j] and cloud is not None and c[j] < cloud[1])
    return out


# ───────── 마하세븐 속임수 돌파 ─────────
def mach7_signal(ind: Ind, j: int, side: str, *, min_slope_pct: float = 0.5,
                 trend_lookback: int = MACH7_TREND_LOOKBACK) -> tuple[bool, dict[str, Any]]:
    """(성립?, 상세). 상세에 stop(함정 극값)·slope_pct·trend 가 들어 있다."""
    d: dict[str, Any] = {"trend": None, "trap": False, "slope_pct": None, "stop": None}
    s, L = ind.sma_s, ind.sma_l
    n = MACH7_CONFIRM_BARS
    if j < MACH7_MA_LONG + trend_lookback or j >= len(ind.c):
        return False, d
    if L[j] is None or L[j - trend_lookback] is None or any(s[j - i] is None for i in range(n + 1)):
        return False, d
    c = ind.c
    if side == "LONG":
        d["trend"] = L[j] > L[j - trend_lookback]
        # 「30선을 잠깐 깼다가(n+1 봉 전 종가 < 30선) 2봉 연속 30선 위 마감」
        d["trap"] = c[j - n] < s[j - n] and all(c[j - i] > s[j - i] for i in range(n))
        base = s[j - trend_lookback]
        d["slope_pct"] = ((s[j] - base) / base * 100.0) if base else None
        d["stop"] = min(ind.l[j - MACH7_STOP_BARS + 1:j + 1])
        ok = bool(d["trend"] and d["trap"] and d["slope_pct"] is not None and d["slope_pct"] >= min_slope_pct)
    else:
        d["trend"] = L[j] < L[j - trend_lookback]
        d["trap"] = c[j - n] > s[j - n] and all(c[j - i] < s[j - i] for i in range(n))
        d["stop"] = max(ind.h[j - MACH7_STOP_BARS + 1:j + 1])
        ok = bool(d["trend"] and d["trap"])          # 출처: SHORT 엔 각도 필터가 없다
    return ok, d


# ───────── 크기·손절 계산 (2% 룰) ─────────
def swing_stop(ind: Ind, j: int, side: str, lookback: int) -> float:
    a = max(0, j - lookback + 1)
    return min(ind.l[a:j + 1]) if side == "LONG" else max(ind.h[a:j + 1])


def stop_pct(entry: float, stop: float, side: str) -> float:
    """진입가 대비 손절폭(가격 %, 양수). 방향이 어긋나면 0."""
    if entry <= 0 or stop <= 0:
        return 0.0
    d = (entry - stop) / entry * 100.0 if side == "LONG" else (stop - entry) / entry * 100.0
    return max(0.0, d)


def clamp_stop_pct(p: float, lo: float, hi: float) -> float:
    return min(max(p, lo), hi)


def risk_capped_margin(*, equity: float, risk_pct: float, stop_price_pct: float, leverage: float,
                       wanted_margin: float) -> tuple[float, bool]:
    """2% 룰: 최대 명목 = 총자산×risk% ÷ 손절폭%. 증거금 = 명목 ÷ 레버. (배정액, 상한에 걸렸나)."""
    if equity <= 0 or risk_pct <= 0 or stop_price_pct <= 0 or leverage <= 0:
        return wanted_margin, False
    max_notional = equity * (risk_pct / 100.0) / (stop_price_pct / 100.0)
    max_margin = max_notional / leverage
    return (min(wanted_margin, max_margin), wanted_margin > max_margin)


def roi_for_stop(entry: float, stop: float, side: str, leverage: float) -> float | None:
    """평단 대비 손절가 → force_sl_roi_override (양수 ROI %)."""
    p = stop_pct(entry, stop, side)
    return p * leverage if p > 0 else None


# ───────── 가상매매(chart_learning.RULES) 규칙 — 시리즈당 지표 1회 캐시 ─────────
_IND_CACHE: dict[tuple[int, int], Ind] = {}
_IND_CACHE_MAX = 6


def _ind_of(ctx: Any) -> Ind:
    key = (id(ctx.c), len(ctx.c))
    hit = _IND_CACHE.get(key)
    if hit is not None:
        return hit
    ind = compute(ctx.c, ctx.h, ctx.l, rsi14=getattr(ctx, "rsi14", None))
    if len(_IND_CACHE) >= _IND_CACHE_MAX:
        _IND_CACHE.pop(next(iter(_IND_CACHE)))
    _IND_CACHE[key] = ind
    return ind


def _fj(ctx: Any, side: str, stage: int) -> bool:
    return bool(fujimoto_stages(_ind_of(ctx), ctx.j, side, div_lookback=int(SETTINGS["fujimoto_div_lookback"][0]))[stage])


def _r_fujimoto_l1(ctx: Any) -> bool: return _fj(ctx, "LONG", 1)
def _r_fujimoto_l2(ctx: Any) -> bool: return _fj(ctx, "LONG", 2)
def _r_fujimoto_l3(ctx: Any) -> bool: return _fj(ctx, "LONG", 3)
def _r_fujimoto_s1(ctx: Any) -> bool: return _fj(ctx, "SHORT", 1)
def _r_fujimoto_s2(ctx: Any) -> bool: return _fj(ctx, "SHORT", 2)
def _r_fujimoto_s3(ctx: Any) -> bool: return _fj(ctx, "SHORT", 3)
def _r_mach7_long(ctx: Any) -> bool:
    return mach7_signal(_ind_of(ctx), ctx.j, "LONG", min_slope_pct=float(SETTINGS["mach7_min_slope_pct"][0]))[0]
def _r_mach7_short(ctx: Any) -> bool:
    return mach7_signal(_ind_of(ctx), ctx.j, "SHORT")[0]


# (key, side, label, fn) — chart_learning.RULES 가 Rule 로 감싼다
PAPER_RULES: tuple[tuple[str, str, str, Any], ...] = (
    ("fujimoto_l1_rsi", "LONG", "후지모토 1차: RSI14 30 재돌파 (Fix 368, shadow)", _r_fujimoto_l1),
    ("fujimoto_l2_div_gc", "LONG", "후지모토 2차: 상승 다이버전스 + 영선 아래 골든크로스", _r_fujimoto_l2),
    ("fujimoto_l3_ichimoku", "LONG", "후지모토 3차: 전환선↑기준선 + 구름 위 + 후행스팬", _r_fujimoto_l3),
    ("fujimoto_s1_rsi", "SHORT", "후지모토 1차: RSI14 70 아래로 꺾임", _r_fujimoto_s1),
    ("fujimoto_s2_div_dc", "SHORT", "후지모토 2차: 하락 다이버전스 + 데드크로스 + RSI<50", _r_fujimoto_s2),
    ("fujimoto_s3_ichimoku", "SHORT", "후지모토 3차: 구름 하단 이탈 + 전환선↓기준선", _r_fujimoto_s3),
    ("mach7_trap_long", "LONG", "마하세븐 숏트랩: 200선↑ + 30선 이탈 뒤 2봉 복귀 + 기울기", _r_mach7_long),
    ("mach7_trap_short", "SHORT", "마하세븐 롱트랩: 200선↓ + 30선 돌파 뒤 2봉 복귀", _r_mach7_short),
)
