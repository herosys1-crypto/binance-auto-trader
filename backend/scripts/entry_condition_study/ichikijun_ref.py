"""일목 기준선 복합 전략 — **참조 판정 구현** (사전 백테스트용 · 운영 코드 아님).

출처: 사장님 첨부 `code_artifact (1).md` 「일목균형표 기준선 및 복합 지표 통합 매매 전략 시스템 로직」 (2026-10-18).
/duel 로 만들 운영 모듈(app/services/ichimoku_kijun.py)은 이 파일과 **같은 입력 → 같은 판정**이어야 한다(일치 테스트).

출처 숫자 (verbatim): 일봉 · BTC SMA 20 · 기준선 26 · MA 5 / 20 · MACD 12/26/9 · RSI 14 기준 50 · 거래량 MA 30 · 손익비 1:2
출처에 숫자가 없는 곳 (「Claude가 정함」 — 운영에서는 system_settings 키):
  window      : 「동시 또는 근접한 시일」 = 기준선 돌파 봉(j) 기준 이전 window 봉 안에 골든/데드크로스·MACD 교차가 있었고 j 에 상태 유지
  obv_lookback: 「OBV 상승 추세」 = OBV[j] > OBV[j − obv_lookback]
  ma_type     : 「지수 또는 단순」 → 기본 sma
  stop clamp  : 손절폭 0.3% ~ 15% (외부 전략 공통 클램프와 같은 자리)
판정 봉 j 는 **완성봉**. BTC 장세는 같은 날(같은 open_time) BTC 완성 일봉.
"""
from __future__ import annotations

from typing import Any, Sequence

KIJUN_N = 26
BTC_SMA = 20
MA_S, MA_L = 5, 20
MACD_F, MACD_S, MACD_SIG = 12, 26, 9
RSI_N, RSI_MID = 14, 50.0
VOL_MA = 30
RR = 2.0

DEFAULTS: dict[str, Any] = {"window": 3, "obv_lookback": 5, "ma_type": "sma", "btc_filter": True,
                            "need_cross_event": True, "vol_filter": True, "obv_filter": True}


def sma(v: Sequence[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(v)
    s = 0.0
    for i, x in enumerate(v):
        s += x
        if i >= n:
            s -= v[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(v: Sequence[float], n: int) -> list[float]:
    k = 2.0 / (n + 1)
    out = [float(v[0])]
    for x in v[1:]:
        out.append(out[-1] + k * (x - out[-1]))
    return out


def rsi(c: Sequence[float], n: int = RSI_N) -> list[float | None]:
    out: list[float | None] = [None] * len(c)
    if len(c) <= n:
        return out
    g = lo = 0.0
    for i in range(1, n + 1):
        d = c[i] - c[i - 1]
        g += max(d, 0.0)
        lo += max(-d, 0.0)
    ag, al = g / n, lo / n
    out[n] = 100.0 - 100.0 / (1.0 + (ag / al if al else 1e9))
    for i in range(n + 1, len(c)):
        d = c[i] - c[i - 1]
        ag = (ag * (n - 1) + max(d, 0.0)) / n
        al = (al * (n - 1) + max(-d, 0.0)) / n
        out[i] = 100.0 - 100.0 / (1.0 + (ag / al if al else 1e9))
    return out


def kijun(h: Sequence[float], lo: Sequence[float], n: int = KIJUN_N) -> list[float | None]:
    out: list[float | None] = [None] * len(h)
    for i in range(n - 1, len(h)):
        out[i] = (max(h[i - n + 1:i + 1]) + min(lo[i - n + 1:i + 1])) / 2.0
    return out


def obv(c: Sequence[float], v: Sequence[float]) -> list[float]:
    out = [0.0]
    for i in range(1, len(c)):
        out.append(out[-1] + (v[i] if c[i] > c[i - 1] else -v[i] if c[i] < c[i - 1] else 0.0))
    return out


def indicators(o, h, lo, c, v, ma_type: str = "sma") -> dict[str, list]:
    ma = (lambda x, n: ema(x, n)) if ma_type == "ema" else sma
    m = [a - b for a, b in zip(ema(c, MACD_F), ema(c, MACD_S))]
    return {"kj": kijun(h, lo), "ms": ma(c, MA_S), "ml": ma(c, MA_L), "macd": m, "sig": ema(m, MACD_SIG),
            "rsi": rsi(c), "vma": sma(v, VOL_MA), "obv": obv(c, v)}


def min_bars(p: dict | None = None) -> int:
    p = {**DEFAULTS, **(p or {})}
    return max(MACD_S + MACD_SIG, VOL_MA, KIJUN_N, MA_L) + int(p["window"]) + int(p["obv_lookback"]) + 2


def _cross(a, b, i: int, up: bool) -> bool:
    if i < 1 or None in (a[i], b[i], a[i - 1], b[i - 1]):
        return False
    return (a[i - 1] <= b[i - 1] and a[i] > b[i]) if up else (a[i - 1] >= b[i - 1] and a[i] < b[i])


def signal(o, h, lo, c, v, j: int, side: str, btc_up: bool | None, p: dict | None = None,
           ind: dict | None = None) -> tuple[bool, dict]:
    """j = 완성 일봉. btc_up = 같은 날 BTC 종가 > BTC SMA20 (None = 모름 → 장세 필터가 켜져 있으면 진입 안 함)."""
    p = {**DEFAULTS, **(p or {})}
    ind = ind or indicators(o, h, lo, c, v, p["ma_type"])
    up = side == "LONG"
    d: dict[str, Any] = {}
    if j < min_bars(p) or j >= len(c):
        return False, {"why": "봉 부족"}
    kj, ms, ml, mc, sg, rs, vm, ob = (ind[k] for k in ("kj", "ms", "ml", "macd", "sig", "rsi", "vma", "obv"))
    # 1 장세
    d["btc"] = (btc_up is True) if up else (btc_up is False)
    # 2 핵심 타점 = j 봉에서 종가가 기준선을 돌파/이탈 (출처: 「종가가 기준선을 상향 돌파」)
    d["kijun"] = (c[j - 1] <= kj[j - 1] and c[j] > kj[j]) if up else (c[j - 1] >= kj[j - 1] and c[j] < kj[j])
    # 3 추세 확인 — 근접한 시일(window) 안 교차 + j 에 상태 유지
    W = int(p["window"])
    rng = range(j - W, j + 1)
    d["ma_state"] = (ms[j] > ml[j]) if up else (ms[j] < ml[j])
    d["macd_state"] = (mc[j] > sg[j]) if up else (mc[j] < sg[j])
    d["ma_cross"] = any(_cross(ms, ml, i, up) for i in rng)
    d["macd_cross"] = any(_cross(mc, sg, i, up) for i in rng)
    trend_ok = d["ma_state"] and d["macd_state"] and (not p["need_cross_event"] or (d["ma_cross"] and d["macd_cross"]))
    # 4 모멘텀·수급
    d["rsi"] = rs[j] is not None and ((rs[j] >= RSI_MID) if up else (rs[j] < RSI_MID))
    d["vol"] = vm[j] is not None and v[j] > vm[j]
    L = int(p["obv_lookback"])
    d["obv"] = (ob[j] > ob[j - L]) if up else (ob[j] < ob[j - L])
    ok = bool((d["btc"] or not p["btc_filter"]) and d["kijun"] and trend_ok and d["rsi"]
              and (d["vol"] or not p["vol_filter"]) and (d["obv"] or not p["obv_filter"]))
    # 5 1차 손절 = 진입 봉·직전 봉 저점(LONG) / 고점(SHORT)
    d["stop"] = min(lo[j], lo[j - 1]) if up else max(h[j], h[j - 1])
    return ok, d


def kijun_exit(c, kj, k: int, side: str) -> bool:
    """2차 손절(추세 이탈) — 종가가 기준선 반대편으로 마감."""
    if kj[k] is None:
        return False
    return (c[k] < kj[k]) if side == "LONG" else (c[k] > kj[k])
