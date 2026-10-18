"""🗾 Fix 465 (2026-10-18 사장님 첨부 `code_artifact (1).md`) — 일목 기준선 복합 전략 판정 + 변형 실험실 변형표.

출처 숫자 (verbatim): BTC SMA 20 장세 · 기준선 26 · MA 5/20 · MACD 12/26/9 · RSI 14 기준 50 · 거래량 MA 30 · 손익비 1:2
  LONG = BTC 종가 > SMA20 · 종가가 기준선 상향 돌파 · MA5↑MA20 · MACD↑시그널 · RSI ≥ 50 · 거래량 > MA30 · OBV 상승 (SHORT 거울)
  1차 손절 = 진입·직전 봉 저점(고점) · 2차 = 종가가 기준선 재이탈 → 종가 청산 · 익절 = 손절폭 × 2
출처에 없는 숫자(근접 창 3봉 · OBV 5봉 · 되돌림 5봉·0.5% · 손절 클램프 0.3~15% · 최대 60봉)는 「Claude가 정함」
(docs/spec/ICHIMOKU_KIJUN_COMBO_2026-10-18.md). 참조 구현 scripts/entry_condition_study/ichikijun_ref.py 와 판정이 같아야 한다.

주문 없음 — 순수 함수만. 실험실 워커(app/workers/ichikijun_lab_worker.py)가 쓴다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

FIX = "Fix465"
KIJUN_N, BTC_SMA = 26, 20
MA_S, MA_L = 5, 20
MACD_F, MACD_S, MACD_SIG = 12, 26, 9
RSI_N, RSI_MID = 14, 50.0
VOL_MA = 30
WINDOW = 3            # 「동시 또는 근접한 시일」 (Claude가 정함)
OBV_LOOKBACK = 5      # 「OBV 상승 추세」 (Claude가 정함)
PB_BARS = 5           # 되돌림 진입: 신호 뒤 이 봉 수 안 (Claude가 정함)
PB_TOL_PERMILLE = 5   # 되돌림 진입: 기준선 ± 0.5%(천분율 5) 안 닿음 (Claude가 정함 · 정수 비교로 LONG/SHORT 경계 대칭 — 교차 감사)
STOP_MIN, STOP_MAX = 0.003, 0.15
MAX_HOLD = 60

INTERVALS = ("1h", "4h", "1d")
FILTERS = ("src", "loose")
ENTRIES = ("now", "pb")
EXITS = {"r2": (2.0, False), "r15": (1.5, False), "r2kj": (2.0, True)}   # (익절 R, 기준선 청산)


@dataclass(frozen=True)
class Variant:
    iv: str
    flt: str
    ent: str
    ext: str

    @property
    def key(self) -> str:
        return f"{self.iv}_{self.flt}_{self.ent}_{self.ext}"

    @property
    def rr(self) -> float:
        return EXITS[self.ext][0]

    @property
    def kijun_exit(self) -> bool:
        return EXITS[self.ext][1]


VARIANTS: tuple[Variant, ...] = tuple(Variant(i, f, e, x) for i in INTERVALS for f in FILTERS for e in ENTRIES for x in EXITS)
BY_KEY = {v.key: v for v in VARIANTS}
SOURCE_KEY = "1d_src_now_r2kj"         # 출처 그대로


# ───────── 지표 (ref 와 같은 정의) ─────────
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
    if not v:
        return []
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
    out = [0.0] if c else []
    for i in range(1, len(c)):
        out.append(out[-1] + (v[i] if c[i] > c[i - 1] else -v[i] if c[i] < c[i - 1] else 0.0))
    return out


@dataclass
class Bars:
    ts: list[int]
    o: list[float]
    h: list[float]
    lo: list[float]
    c: list[float]
    v: list[float]
    ind: dict[str, list]


def bars_from(kl: list) -> Bars | None:
    """바이낸스 klines 행 → Bars. 값 이상(NaN·0 이하 가격)이 하나라도 있으면 None (판정하지 않는다)."""
    try:
        ts = [int(b[0]) for b in kl]
        o, h, lo, c, v = ([float(b[i]) for b in kl] for i in (1, 2, 3, 4, 5))
    except (TypeError, ValueError, IndexError):
        return None
    if not all(math.isfinite(x) and x > 0 for x in (*o, *h, *lo, *c)) or not all(math.isfinite(x) and x >= 0 for x in v):
        return None
    m = [a - b for a, b in zip(ema(c, MACD_F), ema(c, MACD_S))]
    ind = {"kj": kijun(h, lo), "ms": sma(c, MA_S), "ml": sma(c, MA_L), "macd": m, "sig": ema(m, MACD_SIG),
           "rsi": rsi(c), "vma": sma(v, VOL_MA), "obv": obv(c, v)}
    return Bars(ts, o, h, lo, c, v, ind)


def min_bars() -> int:
    return max(MACD_S + MACD_SIG, VOL_MA, KIJUN_N, MA_L) + WINDOW + OBV_LOOKBACK + 2


def _cross(a, b, i: int, up: bool) -> bool:
    if i < 1 or None in (a[i], b[i], a[i - 1], b[i - 1]):
        return False
    return (a[i - 1] <= b[i - 1] and a[i] > b[i]) if up else (a[i - 1] >= b[i - 1] and a[i] < b[i])


def signal(B: Bars, j: int, side: str, btc_up: bool | None, flt: str = "src") -> tuple[bool, dict]:
    """j = 완성봉. 출처 판정. flt=loose 면 거래량·OBV 를 보지 않는다. btc_up=None(모름) 이면 진입 없음."""
    up = side == "LONG"
    if side not in ("LONG", "SHORT") or j < min_bars() or j >= len(B.c):
        return False, {"why": "봉 부족"}
    I, c, v = B.ind, B.c, B.v
    kj, ms, ml, mc, sg, rs, vm, ob = (I[k] for k in ("kj", "ms", "ml", "macd", "sig", "rsi", "vma", "obv"))
    if None in (kj[j], kj[j - 1], ms[j], ml[j]):
        return False, {"why": "지표 없음"}
    d: dict[str, Any] = {"btc": (btc_up is True) if up else (btc_up is False)}
    d["kijun"] = (c[j - 1] <= kj[j - 1] and c[j] > kj[j]) if up else (c[j - 1] >= kj[j - 1] and c[j] < kj[j])
    rng = range(j - WINDOW, j + 1)
    trend = (((ms[j] > ml[j]) if up else (ms[j] < ml[j])) and ((mc[j] > sg[j]) if up else (mc[j] < sg[j]))
             and any(_cross(ms, ml, i, up) for i in rng) and any(_cross(mc, sg, i, up) for i in rng))
    d["trend"] = trend
    d["rsi"] = rs[j] is not None and ((rs[j] >= RSI_MID) if up else (rs[j] < RSI_MID))
    d["vol"] = vm[j] is not None and v[j] > vm[j]
    d["obv"] = (ob[j] > ob[j - OBV_LOOKBACK]) if up else (ob[j] < ob[j - OBV_LOOKBACK])
    loose = flt == "loose"
    ok = bool(d["btc"] and d["kijun"] and trend and d["rsi"] and (loose or (d["vol"] and d["obv"])))
    d["stop"] = min(B.lo[j], B.lo[j - 1]) if up else max(B.h[j], B.h[j - 1])
    return ok, d


def entry_at(B: Bars, k: int, side: str, var: Variant, btc_up_at) -> tuple[bool, float | None, int | None]:
    """봉 k 가 이 변형의 **진입 봉**인가 → (진입, 손절가, 신호 봉). btc_up_at(j) = 그 봉의 BTC 장세.
    now = 신호 봉 = 진입 봉. pb = 신호 j(k−5 ≤ j < k) 뒤 **첫** 되돌림 봉(저가 ≤ 기준선×(1+0.5%) 이고 종가 > 기준선; SHORT 거울)."""
    up = side == "LONG"
    if var.ent == "now":
        ok, d = signal(B, k, side, btc_up_at(k), var.flt)
        return (True, d["stop"], k) if ok else (False, None, None)
    kj = B.ind["kj"]
    if kj[k] is None:
        return False, None, None
    for j in range(k - 1, max(k - PB_BARS, 0) - 1, -1):          # 가장 최근 신호부터
        ok, _ = signal(B, j, side, btc_up_at(j), var.flt)
        if not ok:
            continue
        for m in range(j + 1, k + 1):                             # j 뒤 첫 되돌림 봉이 k 여야 한다
            if kj[m] is None:
                break
            if not _touch(B, m, up):
                continue
            if m != k:
                break
            stop = min(B.lo[k], B.lo[k - 1]) if up else max(B.h[k], B.h[k - 1])
            return True, stop, j
        return False, None, None                                 # 가장 최근 신호의 되돌림만 본다
    return False, None, None


def _touch(B: Bars, m: int, up: bool) -> bool:
    """되돌림 닿음 — LONG 저가 ≤ 기준선×(1+0.5%) 이고 종가 > 기준선 (SHORT 거울). 천분율 정수 곱으로 비교."""
    kj = B.ind["kj"][m]
    if up:
        return B.lo[m] * 1000 <= kj * (1000 + PB_TOL_PERMILLE) and B.c[m] > kj
    return B.h[m] * 1000 >= kj * (1000 - PB_TOL_PERMILLE) and B.c[m] < kj


def clamp_stop(entry: float, stop: float) -> tuple[float, bool]:
    """손절폭(비율) 0.3~15% 클램프 → (폭, 상한에 걸림). 기획서: 「상한에 걸리면 clamped=1」(하한 0.3% 로 넓힌 건은 표식 안 함)."""
    raw = abs(entry - stop) / entry
    return min(max(raw, STOP_MIN), STOP_MAX), raw > STOP_MAX


def simulate(B: Bars, j: int, side: str, risk: float, rr: float, kijun_exit: bool,
             max_hold: int = MAX_HOLD) -> dict[str, Any]:
    """진입 = j 봉 종가 · 손절폭 risk(비율). j 뒤 완성봉을 처음부터 다시 걷는다(상태 없음 · 같은 입력 = 같은 결과).
    반환 status OPEN(아직) / CLOSED + exit(SL/TP/KJ/TIME) · r(손절폭 단위) · bars. 같은 봉 손절·익절 = 손절."""
    up = side == "LONG"
    c, h, lo, kj = B.c, B.h, B.lo, B.ind["kj"]
    entry = c[j]
    stop = entry * (1 - risk) if up else entry * (1 + risk)
    tgt = entry * (1 + rr * risk) if up else entry * (1 - rr * risk)
    last = min(len(c) - 1, j + max_hold)
    for k in range(j + 1, last + 1):
        if (lo[k] <= stop) if up else (h[k] >= stop):
            return {"status": "CLOSED", "exit": "SL", "r": -1.0, "bars": k - j, "exit_ts": B.ts[k]}
        if (h[k] >= tgt) if up else (lo[k] <= tgt):
            return {"status": "CLOSED", "exit": "TP", "r": rr, "bars": k - j, "exit_ts": B.ts[k]}
        if kijun_exit and kj[k] is not None and ((c[k] < kj[k]) if up else (c[k] > kj[k])):
            return {"status": "CLOSED", "exit": "KJ", "r": ((c[k] - entry) if up else (entry - c[k])) / entry / risk,
                    "bars": k - j, "exit_ts": B.ts[k]}
    if last - j >= max_hold:
        k = last
        return {"status": "CLOSED", "exit": "TIME", "r": ((c[k] - entry) if up else (entry - c[k])) / entry / risk,
                "bars": k - j, "exit_ts": B.ts[k]}
    return {"status": "OPEN", "bars": last - j}


def net_r(r: float, risk: float, cost_pct: float) -> float:
    """비용(왕복 %) 을 R 로 환산해 뺀다."""
    return r - (cost_pct / 100.0) / risk
