"""📊 Fix 429 (2026-10-10 사장님 첨부 `bollinger_ema_trading_strategy.md`) — 존 볼린저 「볼린저 밴드 + EMA」 → 외부 전략 4번째 가족 (일봉).

출처 (verbatim 요지):
  지표   : EMA 200(대세) · EMA 90(분기 사이클) · 볼린저 30 / 2σ (코인 = 30일 한 달 사이클) · 리버절 밴드(외곽 이탈 판별)
  전략 1 : 추세 — LONG = 가격 > EMA200 & EMA90 > EMA200 (정배열), 밴드가 **수축했다가 확장**하며 종가가 상단 이상 (SHORT 거울)
           손절 = 볼린저 중단 · 익절 = 추세·배열이 꺾일 때까지 보유
  전략 2 : 반전 — 밴드 밖으로 **강하게 이탈**(리버절 밴드 이탈)이면 반전 금지 = 추세 연장 / 밴드 안쪽에서 반전하면 반대편 밴드 목표
  출처 슈도코드: is_uptrend = close > EMA200 and EMA90 > EMA200 · bb_expanding = 폭[j] > 폭[j-1] · close >= BB_Upper → ENTER_LONG_TREND

출처에 숫자가 없는 곳(수축 판정·리버절 밴드 폭)은 설정 키로 뺐다(「Claude가 정함」).
기본 그림자(신호만 기록) · 켜기는 관제실 ⑥ (사장님). 판정 = 일봉 완성봉 (출처의 30일·분기 = 일 단위).
"""
from __future__ import annotations

import math
from typing import Any, Sequence

FIX = "Fix429"
PREFIX, STYPE = "BBEMA", "bb_ema"

# ───────── 출처 숫자 (verbatim) ─────────
EMA_LONG, EMA_MID = 200, 90
BB_N, BB_K = 30, 2.0

SETTINGS: dict[str, tuple[str, str, str]] = {
    "bbema_mode": ("shadow", "off | shadow(신호만 기록) — on 은 전용 추세 보유 청산이 생길 때까지 shadow 로 동작 (Fix 429)",
                   "Claude가 정함 — 실자금은 사장님이 켠다"),
    "bbema_sides": ("LONG,SHORT", "허용 방향", "출처(양방향)"),
    "bbema_interval": ("1d", "판정 봉 — 일봉만 (출처 숫자가 일 단위; 다른 값은 일봉으로 강제 + 경고)", "출처: 볼린저 30 = 30일 · EMA90 = 분기 → 일봉"),
    "bbema_capital_usdt": ("10", "1회 진입 증거금(USDT)", "Claude가 정함 — 실주문 규칙 가족과 같은 10"),
    "bbema_risk_pct": ("2", "2% 룰 상한 (외부 전략 공통)", "Claude가 정함"),
    "bbema_max_concurrent": ("2", "전용 동시 보유 상한", "Claude가 정함"),
    "bbema_cooldown_hours": ("20", "심볼당 신호 뒤 재신호 무시 (일봉: 다음 날 허용)", "Claude가 정함"),
    "bbema_squeeze_pct": ("25", "수축 = 밴드 폭이 최근 N봉 폭의 하위 이 % 안", "Claude가 정함 (출처 「좁게 수축」)"),
    "bbema_squeeze_lookback": ("120", "수축 판정 비교 창(봉)", "Claude가 정함"),
    "bbema_squeeze_within": ("5", "확장 직전 이 봉 수 안에 수축이 있었어야 함", "Claude가 정함 (출처 「수축을 유지하다가 확장」)"),
    "bbema_rev_k": ("3.0", "리버절 밴드 = 중단 ± 이 σ (이 밴드를 뚫으면 반전 금지)", "Claude가 정함 (출처 「외곽 이탈 범위」)"),
    "bbema_reversal_enabled": ("1", "전략 2(반전) 판정 (1=켬 0=끔)", "출처(전략 2)"),
}

_BOUNDS = {"bbema_squeeze_pct": (1.0, 100.0), "bbema_squeeze_lookback": (30, 500), "bbema_squeeze_within": (1, 30),
           "bbema_rev_k": (2.1, 6.0)}


def _f(g, key: str) -> float:
    d = float(SETTINGS[key][0])
    try:
        x = float(g(key))
    except (TypeError, ValueError):
        return d
    lo, hi = _BOUNDS.get(key, (-math.inf, math.inf))
    return x if math.isfinite(x) and lo <= x <= hi else d


def params_from(settings_get=None) -> dict[str, Any]:
    g = settings_get or (lambda k: SETTINGS[k][0])
    rev = str(g("bbema_reversal_enabled") or "1").strip().lower() not in ("0", "false", "off", "no")
    return {"squeeze_pct": _f(g, "bbema_squeeze_pct"), "squeeze_lookback": int(_f(g, "bbema_squeeze_lookback")),
            "squeeze_within": int(_f(g, "bbema_squeeze_within")), "rev_k": _f(g, "bbema_rev_k"), "reversal": rev}


PAPER_PARAMS: dict[str, Any] = params_from()


def set_paper_params(settings_get) -> None:
    global PAPER_PARAMS
    try:
        PAPER_PARAMS = params_from(settings_get)
    except Exception:  # noqa: BLE001
        pass


def min_bars(p: dict[str, Any] | None = None) -> int:
    p = p or params_from()
    return max(EMA_LONG, BB_N + int(p["squeeze_lookback"])) + 5


# ───────── 지표 (출처 슈도코드와 같은 정의: EMA adjust=False · rolling std = 표본 표준편차 ddof=1) ─────────
def ema(v: Sequence[float], n: int) -> list[float]:
    k = 2.0 / (n + 1)
    out = [float(v[0])]
    for x in v[1:]:
        out.append(out[-1] + k * (float(x) - out[-1]))
    return out


def bands(c: Sequence[float], n: int = BB_N) -> tuple[list, list]:
    """(중단 SMA, 표본 표준편차) — n 봉 미만은 None."""
    mid: list[float | None] = [None] * len(c)
    sd: list[float | None] = [None] * len(c)
    for i in range(n - 1, len(c)):
        w = [float(x) for x in c[i - n + 1:i + 1]]
        m = sum(w) / n
        mid[i] = m
        sd[i] = math.sqrt(sum((x - m) ** 2 for x in w) / (n - 1))
    return mid, sd


def indicators(c: Sequence[float]) -> dict[str, list]:
    mid, sd = bands(c)
    return {"e200": ema(c, EMA_LONG), "e90": ema(c, EMA_MID), "mid": mid, "sd": sd}


def _bbw(ind, i: int) -> float | None:
    m, s = ind["mid"][i], ind["sd"][i]
    return (2 * BB_K * s / m) if (m and s is not None) else None


def _quantile(xs: list[float], q: float) -> float:
    ys = sorted(xs)
    k = max(0, min(len(ys) - 1, int(math.ceil(q / 100.0 * len(ys))) - 1))
    return ys[k]


def trend_signal(c, h, lo, j: int, side: str, p: dict | None = None, ind: dict | None = None) -> tuple[bool, dict]:
    """전략 1: EMA 정배열 + 수축 뒤 확장 + 종가가 밴드 밖(상단 이상 / 하단 이하). 손절 = 중단."""
    p = p or params_from()
    d: dict[str, Any] = {"kind": "trend", "trend": False, "expanding": False, "squeeze": False, "breakout": False,
                         "stop": None, "target": None, "bbw": None}
    if side not in ("LONG", "SHORT") or j < min_bars(p) - 5 or j >= len(c):
        return False, d
    ind = ind or indicators(c)
    up = ind["mid"][j] + BB_K * ind["sd"][j]
    dn = ind["mid"][j] - BB_K * ind["sd"][j]
    if side == "LONG":
        d["trend"] = c[j] > ind["e200"][j] and ind["e90"][j] > ind["e200"][j]
        d["breakout"] = c[j] >= up
    else:
        d["trend"] = c[j] < ind["e200"][j] and ind["e90"][j] < ind["e200"][j]
        d["breakout"] = c[j] <= dn
    w_now = _bbw(ind, j)
    d["bbw"] = w_now
    # 확장 = 출처 슈도코드 그대로 **절대 폭**(상단−하단 = 4σ) 비교 (교차 감사: 상대 폭은 중단이 오르면 확장을 놓친다). 수축은 상대 폭으로.
    s_now, s_prev = ind["sd"][j], ind["sd"][j - 1]
    d["expanding"] = s_now is not None and s_prev is not None and s_now > s_prev
    L, W = int(p["squeeze_lookback"]), int(p["squeeze_within"])
    hist = [x for x in (_bbw(ind, i) for i in range(j - L, j)) if x is not None]
    recent = [x for x in (_bbw(ind, i) for i in range(j - W, j)) if x is not None]
    if hist and recent:
        d["squeeze"] = min(recent) <= _quantile(hist, p["squeeze_pct"])
    d["stop"] = ind["mid"][j]
    ok = bool(d["trend"] and d["expanding"] and d["squeeze"] and d["breakout"])
    return ok, d


def reversal_signal(c, h, lo, j: int, side: str, p: dict | None = None, ind: dict | None = None) -> tuple[bool, dict]:
    """전략 2: 어제 **또는** 오늘 저가(고가)가 2σ 밴드에 닿았고, 이틀 모두 리버절 밴드(rev_k σ)는 안 뚫었고, 오늘 밴드 안으로 마감 + 반등(반락).
    리버절 밴드를 뚫었으면 = 추세 연장 → 반전 금지. 손절 = 리버절 밴드 · 목표 = 반대편 2σ 밴드."""
    p = p or params_from()
    d: dict[str, Any] = {"kind": "reversal", "touched": False, "held": False, "inside": False, "turn": False,
                         "stop": None, "target": None}
    if not p.get("reversal", True) or side not in ("LONG", "SHORT") or j < min_bars(p) - 5 or j >= len(c):
        return False, d
    ind = ind or indicators(c)
    k2, kr = BB_K, float(p["rev_k"])
    m, s = ind["mid"], ind["sd"]
    if side == "LONG":
        d["touched"] = any(lo[i] <= m[i] - k2 * s[i] for i in (j - 1, j))
        d["held"] = all(lo[i] > m[i] - kr * s[i] for i in (j - 1, j))
        d["inside"] = c[j] > m[j] - k2 * s[j]
        d["turn"] = c[j] > c[j - 1]
        d["stop"], d["target"] = m[j] - kr * s[j], m[j] + k2 * s[j]
    else:
        d["touched"] = any(h[i] >= m[i] + k2 * s[i] for i in (j - 1, j))
        d["held"] = all(h[i] < m[i] + kr * s[i] for i in (j - 1, j))
        d["inside"] = c[j] < m[j] + k2 * s[j]
        d["turn"] = c[j] < c[j - 1]
        d["stop"], d["target"] = m[j] + kr * s[j], m[j] - k2 * s[j]
    ok = bool(d["touched"] and d["held"] and d["inside"] and d["turn"])
    return ok, d


def signal(c, h, lo, j: int, side: str, p: dict | None = None, ind: dict | None = None) -> tuple[bool, dict]:
    """추세(전략 1)가 먼저, 없으면 반전(전략 2). 반환 상세의 kind 로 구분."""
    ind = ind or indicators(c)
    ok, d = trend_signal(c, h, lo, j, side, p, ind)
    if ok:
        return ok, d
    return reversal_signal(c, h, lo, j, side, p, ind)


# ───────── 가상매매 — 일봉 마감 뒤 1시간 창 · 하루 1회 (EMA 눌림·후지모토와 같은 장치) ─────────
def _daily(ctx: Any) -> tuple[list, list, list] | None:
    from app.services.ema_pullback import daily_is_fresh
    k1 = getattr(ctx, "kl1d", None)
    if not daily_is_fresh(k1, getattr(ctx, "kl15", None)):
        return None
    try:
        return [float(b[4]) for b in k1], [float(b[2]) for b in k1], [float(b[3]) for b in k1]
    except (TypeError, ValueError, IndexError):
        return None


def _paper(ctx: Any, side: str, kind: str) -> bool:
    dv = _daily(ctx)
    if dv is None:
        return False
    c, h, lo = dv
    fn = trend_signal if kind == "trend" else reversal_signal
    return bool(fn(c, h, lo, len(c) - 1, side, PAPER_PARAMS)[0])


def _r_tl(ctx): return _paper(ctx, "LONG", "trend")
def _r_ts(ctx): return _paper(ctx, "SHORT", "trend")
def _r_rl(ctx): return _paper(ctx, "LONG", "reversal")
def _r_rs(ctx): return _paper(ctx, "SHORT", "reversal")


PAPER_RULES: tuple[tuple[str, str, str, Any], ...] = (
    ("bbema_trend_long", "LONG", "볼린저 EMA 추세 LONG(일봉): 가격>EMA200 · EMA90>EMA200 · 수축→확장 · 종가≥상단 (Fix 429, shadow)", _r_tl),
    ("bbema_trend_short", "SHORT", "볼린저 EMA 추세 SHORT(일봉): 가격<EMA200 · EMA90<EMA200 · 수축→확장 · 종가≤하단 (Fix 429, shadow)", _r_ts),
    ("bbema_rev_long", "LONG", "볼린저 반전 LONG(일봉): 하단 2σ 터치 · 리버절 3σ 안 뚫음 · 밴드 안 반등 마감 (Fix 429, shadow)", _r_rl),
    ("bbema_rev_short", "SHORT", "볼린저 반전 SHORT(일봉): 상단 2σ 터치 · 리버절 3σ 안 뚫음 · 밴드 안 반락 마감 (Fix 429, shadow)", _r_rs),
)
