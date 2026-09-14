"""📐 Fix 372 (2026-09-15 사장님) — 일봉·4시간·5분·1분 차트 상태 기록 (학습 전용 · 매매 판정 없음).

사장님 verbatim:
  "5분과 일일 차트와 보조지표도 같이 계산해서 기록해줘 4시간 정기 흐름을 판단하지 일일차트에는 볼밴 하단이탈 지지 상단 저항과 돌파
   그리고 상단돌파후 조정시작과 큰조정 볼밴중단 저지와 이탈 돌파와 저항을 하단 이탈후 반등과 재상승시작점 그리고 하단이탈후 추세하락을
   확실하게 볼수 있어 지속적인 상승에서는 지지와 돌파 저항수 다시 재상승 하락에서 이것과 반대로 해석하면 될것 같아
   그리고 5분과 1분은 단기적을 최고점과 최저점을 예측할수 있었든것 같아 저항점과 하락 지지와 반등등 이것을 분석하면
   지금 우리가 놓치고있는 빠른 진입과 늦은 진입그리고 잘못된 포지션을 많이 개선할수 있을것 같아
   가상매매과 모든 거래에서 이제는 5분과 일일차트 그리고 필요하면 1분차트까지 학습해줘"

이 모듈은 **순수 계산**이다(주문·손절·자본 없음). 호출자가 봉을 넘기거나 `capture` 가 읽기 전용으로 조회한다.
  bb_state        일봉·4시간 볼밴 상태 — 사장님이 말한 이벤트를 숫자 규칙으로 (아래 BB_EVENTS)
  short_term      5분·1분 단기 — 직전 고점(저항)·저점(지지), 저항 반락·지지 반등·돌파·이탈·신고/신저·꺾임·반등·다이버전스
  tf_indicators   모든 시간봉 공통 보조지표 (볼밴 %B·폭·중단선 기울기 · RSI · MACD hist · EMA20/50 배열 · ATR% · 거래량 배수)
  timing_label    진입 **뒤** 5분봉으로 채점 — 너무 이름(EARLY) · 늦음(LATE) · 방향 틀림(WRONG_DIRECTION) · 좋음(GOOD)
완성봉만 쓴다(`now_ms` 이후에 닫히는 봉 제외 = 미래참조 금지). 모든 숫자는 THRESHOLDS(「Claude가 정함」) — 설정
`chart_state_thresholds`(JSON) 로 덮는다. 사장님 해석 「상승 추세에서는 지지·돌파·저항 뒤 재상승, 하락은 반대」는
판정에 섞지 않고 `trend` 와 이벤트를 따로 기록해 학습 보고서가 추세별로 가른다.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)

FIX = "Fix372"
VERSION = 1
S_ENABLED = "chart_state_enabled"        # 기본 1 — 가상매매·실거래 진입 기록에 붙인다
S_1M = "chart_state_1m_enabled"          # 기본 1 — 사장님 「필요하면 1분차트까지」
S_THRESH = "chart_state_thresholds"

MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
KEYS = {"1d": "d1", "4h": "h4", "1h": "h1", "15m": "m15", "5m": "m5", "1m": "m1"}
LIMITS = {"1d": 60, "4h": 60, "1h": 60, "15m": 60, "5m": 120, "1m": 60}

THRESHOLDS: dict[str, float] = {
    "bb_period": 20, "bb_k": 2.0,
    "tol_pct_1d": 0.5, "tol_pct_4h": 0.3, "tol_pct_short": 0.15,   # 밴드 「닿음」 허용 (가격 %)
    "lookback_1d": 5, "lookback_4h": 6,                            # 「돌파 뒤·이탈 뒤」 기억 봉 수
    "trend_slope_1d": 1.0, "trend_slope_4h": 0.5,                  # 중단선 3봉 기울기(%) 이상 = 추세
    "pivot_w": 3,                                                  # 단기 고점·저점 = 좌우 3봉보다 높/낮음 (확정까지 3봉 지연)
    "range_bars_5m": 24, "range_bars_1m": 60,                      # 위치 계산 창 (5분 2시간 · 1분 1시간)
    "near_pos": 0.85, "near_rsi_top": 65.0, "near_rsi_bottom": 35.0,
    "timing_pre_bars": 12, "timing_after_bars": 48,                # 진입 전 1시간 · 진입 뒤 4시간 (5분봉)
    "timing_win_pct": 1.5, "timing_early_adv_pct": 1.5, "timing_wrong_pct": 3.0, "timing_late_pct": 2.0,
}

BULL_EVENTS = ("UPPER_BREAKOUT", "UPPER_RIDE", "MID_RECLAIM", "MID_SUPPORT", "LOWER_SUPPORT",
               "REBOUND_AFTER_LOWER", "RERISE_START")
BEAR_EVENTS = ("LOWER_BREAKDOWN", "LOWER_RIDE", "MID_BREAKDOWN", "MID_RESIST", "UPPER_REJECT",
               "PULLBACK_START", "DEEP_PULLBACK")
BB_EVENTS = {
    "UPPER_BREAKOUT": "상단 돌파", "UPPER_RIDE": "상단 밖 지속 (돌파 유지)", "UPPER_REJECT": "상단 저항",
    "PULLBACK_START": "상단 돌파 뒤 조정 시작", "DEEP_PULLBACK": "상단 돌파 뒤 큰 조정 (중단선까지)",
    "MID_SUPPORT": "중단선 지지", "MID_BREAKDOWN": "중단선 이탈", "MID_RECLAIM": "중단선 돌파", "MID_RESIST": "중단선 저항",
    "LOWER_BREAKDOWN": "하단 이탈", "LOWER_RIDE": "하단 이탈 뒤 추세 하락", "LOWER_SUPPORT": "하단 지지",
    "REBOUND_AFTER_LOWER": "하단 이탈 뒤 반등", "RERISE_START": "재상승 시작점",
}
BB_PRIORITY = ("LOWER_BREAKDOWN", "UPPER_BREAKOUT", "LOWER_RIDE", "UPPER_RIDE", "RERISE_START", "REBOUND_AFTER_LOWER",
               "DEEP_PULLBACK", "PULLBACK_START", "MID_BREAKDOWN", "MID_RECLAIM", "UPPER_REJECT", "MID_RESIST",
               "MID_SUPPORT", "LOWER_SUPPORT")
TIMING_LABELS = {"GOOD": "좋은 진입", "EARLY": "빠른 진입 (먼저 역행)", "LATE": "늦은 진입 (움직임이 이미 지나감)",
                 "WRONG_DIRECTION": "잘못된 방향", "NO_MOVE": "움직임 없음"}


# ── 설정 ────────────────────────────────────────────────────────────────
def _f(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def thresholds(db: Any = None) -> dict[str, float]:
    th = dict(THRESHOLDS)
    if db is None:
        return th
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, S_THRESH)
        raw = json.loads(str(row.value)) if row is not None and row.value not in (None, "") else {}
        for k, v in (raw or {}).items():
            if k in th and _f(v) is not None:
                th[k] = float(v)
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] %s 읽기 실패 → 기본값: %s", FIX, S_THRESH, e)
    return th


def setting_on(db: Any, key: str, default: bool = True) -> bool:
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, key)
        if row is None or row.value in (None, ""):
            return default
        return str(row.value).strip().lower() not in ("0", "off", "false", "no")
    except Exception:  # noqa: BLE001
        return default


# ── 봉 · 지표 (순수) ─────────────────────────────────────────────────────
def normalize(kl: Sequence[Sequence[Any]] | None, interval: str, now_ms: int | None = None) -> list[list[float]]:
    """바이낸스 12필드 또는 6필드 → [t,o,h,l,c,v] float. now_ms 이후에 닫히는 봉(진행 중)은 뺀다."""
    step = MS.get(interval, 0)
    out: list[list[float]] = []
    for k in kl or []:
        try:
            t = int(float(k[0]))
            row = [t, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])]
        except (TypeError, ValueError, IndexError):
            continue
        if now_ms is not None and step and t + step > now_ms:
            continue
        out.append(row)
    return out


def _sma_series(vals: Sequence[float], p: int) -> list[float | None]:
    out: list[float | None] = [None] * len(vals)
    s = 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= p:
            s -= vals[i - p]
        if i >= p - 1:
            out[i] = s / p
    return out


def ema_series(vals: Sequence[float], p: int) -> list[float | None]:
    out: list[float | None] = [None] * len(vals)
    if len(vals) < p:
        return out
    k = 2 / (p + 1)
    e = sum(vals[:p]) / p
    out[p - 1] = e
    for i in range(p, len(vals)):
        e = vals[i] * k + e * (1 - k)
        out[i] = e
    return out


def bollinger(closes: Sequence[float], p: int = 20, kk: float = 2.0) -> tuple[list, list, list]:
    n = len(closes)
    mid: list[float | None] = [None] * n
    up: list[float | None] = [None] * n
    lo: list[float | None] = [None] * n
    for i in range(p - 1, n):
        w = closes[i - p + 1:i + 1]
        m = sum(w) / p
        sd = (sum((x - m) ** 2 for x in w) / p) ** 0.5
        mid[i], up[i], lo[i] = m, m + kk * sd, m - kk * sd
    return mid, up, lo


def rsi_series(closes: Sequence[float], p: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= p:
        return out
    gains = losses = 0.0
    for i in range(1, p + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    ag, al = gains / p, losses / p
    out[p] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(p + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (p - 1) + max(d, 0.0)) / p
        al = (al * (p - 1) + max(-d, 0.0)) / p
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def macd_hist_series(closes: Sequence[float]) -> list[float | None]:
    e12, e26 = ema_series(closes, 12), ema_series(closes, 26)
    line = [(a - b) if a is not None and b is not None else None for a, b in zip(e12, e26)]
    vals = [x for x in line if x is not None]
    sig = ema_series(vals, 9)
    out: list[float | None] = [None] * len(closes)
    off = len(closes) - len(vals)
    for i, s in enumerate(sig):
        if s is not None:
            out[off + i] = vals[i] - s
    return out


def _r(x: float | None, nd: int = 4) -> float | None:
    return None if x is None else round(float(x), nd)


def tf_indicators(bars: Sequence[Sequence[float]], th: Mapping[str, float] | None = None) -> dict[str, Any]:
    th = {**THRESHOLDS, **(th or {})}
    n = len(bars)
    if n < 30:
        return {"bars": n, "error": "bars"}
    c = [b[4] for b in bars]
    h = [b[2] for b in bars]
    l = [b[3] for b in bars]
    v = [b[5] for b in bars]
    p = int(th["bb_period"])
    mid, up, lo = bollinger(c, p, float(th["bb_k"]))
    rs = rsi_series(c)
    mh = macd_hist_series(c)
    e20, e50 = ema_series(c, 20), ema_series(c, 50)
    i = n - 1
    trs = [max(h[k] - l[k], abs(h[k] - c[k - 1]), abs(l[k] - c[k - 1])) for k in range(max(1, n - 14), n)]
    vol20 = sum(v[-21:-1]) / 20 if n >= 21 else None
    pctb = (c[i] - lo[i]) / (up[i] - lo[i]) if up[i] is not None and up[i] != lo[i] else None
    align = None
    if e20[i] is not None and e50[i] is not None:
        align = "UP" if c[i] > e20[i] > e50[i] else ("DOWN" if c[i] < e20[i] < e50[i] else "MIXED")
    return {
        "bars": n, "close": c[i], "chg_last_pct": _r((c[i] - c[i - 1]) / c[i - 1] * 100, 3),
        "bb_up": _r(up[i], 8), "bb_mid": _r(mid[i], 8), "bb_lo": _r(lo[i], 8), "pctb": _r(pctb),
        "bb_width_pct": _r((up[i] - lo[i]) / mid[i] * 100, 3) if mid[i] else None,
        "mid_slope3_pct": _r((mid[i] - mid[i - 3]) / mid[i - 3] * 100, 3) if n > p + 3 and mid[i - 3] else None,
        "rsi14": _r(rs[i], 2), "rsi14_prev": _r(rs[i - 1], 2),
        "macd_hist": _r(mh[i], 10), "macd_hist_prev": _r(mh[i - 1], 10),
        "macd_dir": (None if mh[i] is None or mh[i - 1] is None else ("UP" if mh[i] > mh[i - 1] else "DOWN")),
        "ema20": _r(e20[i], 8), "ema50": _r(e50[i], 8), "ema_align": align,
        "atr14_pct": _r(sum(trs) / len(trs) / c[i] * 100, 3) if trs and c[i] else None,
        "vol_ratio20": _r(v[i] / vol20, 3) if vol20 else None,
    }


# ── 일봉 · 4시간 볼밴 상태 ────────────────────────────────────────────────
def bb_state(bars: Sequence[Sequence[float]], *, tol_pct: float, lookback: int, slope_pct: float,
             th: Mapping[str, float] | None = None) -> dict[str, Any]:
    """마지막 완성봉 기준 볼밴 이벤트. 여러 이벤트가 동시에 참일 수 있다 → events 전부 + 우선순위 state 하나."""
    th = {**THRESHOLDS, **(th or {})}
    p = int(th["bb_period"])
    lookback = int(lookback)
    n = len(bars)
    if n < p + lookback + 4:
        return {"state": None, "events": [], "error": "bars", "bars": n}
    o = [b[1] for b in bars]
    h = [b[2] for b in bars]
    l = [b[3] for b in bars]
    c = [b[4] for b in bars]
    mid, up, lo = bollinger(c, p, float(th["bb_k"]))
    tol = tol_pct / 100.0
    i, q = n - 1, n - 2
    rng = range(i - lookback, i)
    above_recent = any(c[k] > up[k] for k in rng)
    below_recent = any(c[k] < lo[k] for k in rng)
    wide = range(i - 2 * lookback, i)
    above_wide = any(c[k] > up[k] for k in wide if up[k] is not None)
    below_wide = any(c[k] < lo[k] for k in wide if lo[k] is not None)
    mid_touch_recent = any(l[k] <= mid[k] * (1 + tol) for k in rng)
    ev: list[str] = []
    if c[i] > up[i]:
        ev.append("UPPER_RIDE" if c[q] > up[q] else "UPPER_BREAKOUT")
    if c[i] < lo[i]:
        ev.append("LOWER_RIDE" if c[q] < lo[q] else "LOWER_BREAKDOWN")
    if h[i] >= up[i] * (1 - tol) and c[i] < up[i] and not above_recent:
        ev.append("UPPER_REJECT")
    if above_recent and c[i] <= up[i] and c[i] < c[q]:
        ev.append("PULLBACK_START")
    if above_wide and (l[i] <= mid[i] * (1 + tol)) and c[i] <= up[i]:
        ev.append("DEEP_PULLBACK")
    if c[q] >= mid[q] and l[i] <= mid[i] * (1 + tol) and c[i] >= mid[i]:
        ev.append("MID_SUPPORT")
    if c[q] >= mid[q] and c[i] < mid[i]:
        ev.append("MID_BREAKDOWN")
    if c[q] < mid[q] and c[i] >= mid[i]:
        ev.append("MID_RECLAIM")
    if c[q] < mid[q] and h[i] >= mid[i] * (1 - tol) and c[i] < mid[i]:
        ev.append("MID_RESIST")
    if l[i] <= lo[i] * (1 + tol) and c[i] >= lo[i] and c[q] >= lo[q] and not below_recent:
        ev.append("LOWER_SUPPORT")
    if below_recent and c[i] >= lo[i] and c[i] > c[q]:
        ev.append("REBOUND_AFTER_LOWER")
    if (below_wide or mid_touch_recent) and c[i] > mid[i] and c[i] > max(h[k] for k in range(i - 3, i)):
        ev.append("RERISE_START")
    slope = (mid[i] - mid[i - 3]) / mid[i - 3] * 100 if mid[i - 3] else 0.0
    trend = "UP" if slope >= slope_pct else ("DOWN" if slope <= -slope_pct else "FLAT")
    state = next((s for s in BB_PRIORITY if s in ev), "ABOVE_MID" if c[i] >= mid[i] else "BELOW_MID")

    def _since(pred) -> int | None:
        for back in range(0, min(n - p, 60)):
            k = i - back
            if pred(k):
                return back
        return None

    return {
        "state": state, "state_ko": BB_EVENTS.get(state, "중단선 위" if state == "ABOVE_MID" else "중단선 아래"),
        "events": ev, "trend": trend, "mid_slope3_pct": round(slope, 3),
        "bias": sum(1 for e in ev if e in BULL_EVENTS) - sum(1 for e in ev if e in BEAR_EVENTS),
        "pos": ("ABOVE_UPPER" if c[i] > up[i] else "UPPER_HALF" if c[i] >= mid[i] else
                "LOWER_HALF" if c[i] >= lo[i] else "BELOW_LOWER"),
        "dist_up_pct": round((up[i] - c[i]) / c[i] * 100, 3), "dist_mid_pct": round((mid[i] - c[i]) / c[i] * 100, 3),
        "dist_lo_pct": round((lo[i] - c[i]) / c[i] * 100, 3),
        "bars_since_above_upper": _since(lambda k: up[k] is not None and c[k] > up[k]),
        "bars_since_below_lower": _since(lambda k: lo[k] is not None and c[k] < lo[k]),
        "candle_up": c[i] >= o[i],
    }


# ── 5분 · 1분 단기 고점·저점 ──────────────────────────────────────────────
def pivots(h: Sequence[float], l: Sequence[float], w: int) -> tuple[list[int], list[int]]:
    """확정된 고점·저점 인덱스 (좌우 w 봉 — 마지막 w 봉은 아직 확정 안 됨)."""
    highs, lows = [], []
    for k in range(w, len(h) - w):
        win_h = h[k - w:k + w + 1]
        win_l = l[k - w:k + w + 1]
        if h[k] == max(win_h) and win_h.index(h[k]) == w:
            highs.append(k)
        if l[k] == min(win_l) and win_l.index(l[k]) == w:
            lows.append(k)
    return highs, lows


def short_term(bars: Sequence[Sequence[float]], *, range_bars: int, th: Mapping[str, float] | None = None) -> dict[str, Any]:
    th = {**THRESHOLDS, **(th or {})}
    n = len(bars)
    w = int(th["pivot_w"])
    range_bars = int(range_bars)
    if n < max(30, range_bars + 2):
        return {"error": "bars", "bars": n}
    o = [b[1] for b in bars]
    h = [b[2] for b in bars]
    l = [b[3] for b in bars]
    c = [b[4] for b in bars]
    rs = rsi_series(c)
    tol = float(th["tol_pct_short"]) / 100.0
    i, q = n - 1, n - 2
    ph, pl = pivots(h, l, w)
    res = h[ph[-1]] if ph else None
    sup = l[pl[-1]] if pl else None
    hi = max(h[-range_bars:])
    lo_ = min(l[-range_bars:])
    pos = (c[i] - lo_) / (hi - lo_) if hi > lo_ else None
    ev: list[str] = []
    if res is not None:
        if h[i] >= res * (1 - tol) and c[i] < res and c[i] < o[i]:
            ev.append("RESIST_REJECT")
        if c[i] > res and c[q] <= res:
            ev.append("BREAK_RESIST")
    if sup is not None:
        if l[i] <= sup * (1 + tol) and c[i] >= sup and c[i] > o[i]:
            ev.append("SUPPORT_HOLD")
        if c[i] < sup and c[q] >= sup:
            ev.append("BREAK_SUPPORT")
    if h[i] >= hi:
        ev.append("NEW_HIGH")
    if l[i] <= lo_:
        ev.append("NEW_LOW")
    recent = range(max(0, i - 3), i)
    if any(h[k] >= hi for k in recent) and c[i] < l[q]:
        ev.append("ROLLOVER")
    if any(l[k] <= lo_ for k in recent) and c[i] > h[q]:
        ev.append("REBOUND")
    if len(ph) >= 2 and rs[ph[-1]] is not None and rs[ph[-2]] is not None:
        if h[ph[-1]] > h[ph[-2]] and rs[ph[-1]] < rs[ph[-2]]:
            ev.append("BEAR_DIV")
    if len(pl) >= 2 and rs[pl[-1]] is not None and rs[pl[-2]] is not None:
        if l[pl[-1]] < l[pl[-2]] and rs[pl[-1]] > rs[pl[-2]]:
            ev.append("BULL_DIV")
    r_now = rs[i]
    return {
        "events": ev,
        "resistance": _r(res, 8), "support": _r(sup, 8),
        "dist_res_pct": _r((res - c[i]) / c[i] * 100, 3) if res else None,
        "dist_sup_pct": _r((c[i] - sup) / c[i] * 100, 3) if sup else None,
        "bars_since_pivot_high": (i - ph[-1]) if ph else None, "bars_since_pivot_low": (i - pl[-1]) if pl else None,
        "range_pos": _r(pos), "range_high": _r(hi, 8), "range_low": _r(lo_, 8),
        "near_top": bool(pos is not None and r_now is not None and pos >= th["near_pos"] and r_now >= th["near_rsi_top"]),
        "near_bottom": bool(pos is not None and r_now is not None and pos <= 1 - th["near_pos"] and r_now <= th["near_rsi_bottom"]),
    }


# ── 진입 뒤 채점 ─────────────────────────────────────────────────────────
def timing_label(side: str, entry_price: float, entry_ms: int, bars5m: Sequence[Sequence[float]],
                 th: Mapping[str, float] | None = None) -> dict[str, Any]:
    """진입 전 pre_bars · 진입 뒤 after_bars 5분봉으로 진입 타이밍을 채점한다 (가격 %, 레버리지 무관).
    best_offset_bars = 그 창에서 방향상 가장 좋은 가격이 나온 봉 − 진입 (음수 = 진입 전에 이미 지나감 · 양수 = 더 기다렸어야)."""
    th = {**THRESHOLDS, **(th or {})}
    d = -1 if str(side).upper() == "SHORT" else 1
    E = float(entry_price)
    pre = [b for b in bars5m if b[0] + MS["5m"] <= entry_ms][-int(th["timing_pre_bars"]):]
    after = [b for b in bars5m if b[0] >= entry_ms][:int(th["timing_after_bars"])]
    if E <= 0 or len(after) < int(th["timing_after_bars"]) * 0.75:
        return {"label": None, "error": "bars", "after_bars": len(after)}
    fav = [((b[2] - E) if d > 0 else (E - b[3])) / E * 100 for b in after]
    adv = [((E - b[3]) if d > 0 else (b[2] - E)) / E * 100 for b in after]
    win, early, wrong, late_pct = th["timing_win_pct"], th["timing_early_adv_pct"], th["timing_wrong_pct"], th["timing_late_pct"]
    first_win = next((k for k, x in enumerate(fav) if x >= win), None)
    first_wrong = next((k for k, x in enumerate(adv) if x >= wrong), None)
    adv_before_win = max(adv[:first_win + 1]) if first_win is not None else max(adv)
    pre_improve = 0.0
    if pre:
        pre_improve = ((E - min(b[3] for b in pre)) if d > 0 else (max(b[2] for b in pre) - E)) / E * 100
    end_move = d * (after[-1][4] - E) / E * 100
    window = pre + after
    best = min(range(len(window)), key=lambda k: window[k][3]) if d > 0 else max(range(len(window)), key=lambda k: window[k][2])
    best_px = window[best][3] if d > 0 else window[best][2]
    if first_wrong is not None and (first_win is None or first_wrong < first_win) and end_move < 0:
        label = "WRONG_DIRECTION"
    elif first_win is not None and adv_before_win >= early:
        label = "EARLY"
    elif first_win is not None:
        label = "GOOD"
    elif pre_improve >= late_pct:
        label = "LATE"
    else:
        label = "NO_MOVE"
    return {
        "v": VERSION, "label": label, "label_ko": TIMING_LABELS[label],
        "max_fav_pct": round(max(fav), 3), "max_adv_pct": round(max(adv), 3),
        "adv_before_win_pct": round(adv_before_win, 3), "bars_to_win": first_win, "bars_to_wrong": first_wrong,
        "pre_improve_pct": round(pre_improve, 3), "late_flag": pre_improve >= late_pct,
        "end_move_pct": round(end_move, 3),
        "best_offset_bars": best - len(pre), "best_improve_pct": round(d * (E - best_px) / E * 100, 3),
    }


# ── 캡처 (읽기 전용 조회) ─────────────────────────────────────────────────
def _block(interval: str, bars: Sequence[Sequence[float]], th: Mapping[str, float]) -> dict[str, Any]:
    blk = tf_indicators(bars, th)
    if interval == "1d":
        blk["bb"] = bb_state(bars, tol_pct=th["tol_pct_1d"], lookback=th["lookback_1d"], slope_pct=th["trend_slope_1d"], th=th)
    elif interval == "4h":
        blk["bb"] = bb_state(bars, tol_pct=th["tol_pct_4h"], lookback=th["lookback_4h"], slope_pct=th["trend_slope_4h"], th=th)
    elif interval in ("5m", "1m"):
        blk["st"] = short_term(bars, range_bars=th["range_bars_5m" if interval == "5m" else "range_bars_1m"], th=th)
    return blk


def capture(bc: Any, symbol: str, side: str, *, now_ms: int | None = None,
            klines: Mapping[str, Sequence[Sequence[Any]] | None] | None = None,
            include_1m: bool = True, th: Mapping[str, float] | None = None,
            intervals: Sequence[str] = ("1d", "4h", "1h", "15m", "5m", "1m")) -> dict[str, Any]:
    """시간봉별 지표 + 일봉·4시간 볼밴 상태 + 5분·1분 단기 판정. 예외를 올리지 않는다(부분 결과).
    klines 에 이미 받은 봉(바이낸스 원본 또는 6필드)이 있으면 그대로 쓰고, 없는 간격만 조회한다."""
    th = {**THRESHOLDS, **(th or {})}
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    out: dict[str, Any] = {"v": VERSION, "at": datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).isoformat(),
                           "side": side, "symbol": symbol}
    for iv in intervals:
        if iv == "1m" and not include_1m:
            continue
        key = KEYS[iv]
        try:
            raw = (klines or {}).get(iv)
            if raw is None:
                if bc is None:
                    out[key] = {"error": "no_client"}
                    continue
                raw = bc.get_klines(symbol=symbol, interval=iv, limit=LIMITS[iv])
            out[key] = _block(iv, normalize(raw, iv, now_ms), th)
        except Exception as e:  # noqa: BLE001 — 한 간격 실패가 기록 전체를 막지 않게
            out[key] = {"error": str(e)[:120]}
    return out
