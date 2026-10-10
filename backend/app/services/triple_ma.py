"""📐 Fix 432 (2026-10-10 사장님 첨부 multi_moving_average_trading_strategy.md) — 9 EMA · 20 SMA · 200 SMA 눌림목 추세 추종 (외부 전략 6번째 가족).

출처(Emmanuel Malyarovich): 큰 흐름(SMA200)에 순응 → 중기 조정(SMA20)을 기다림 → 단기 반응(EMA9)으로 타점. 1시간·4시간봉.
  LONG : ① 가격 > SMA200 이고 SMA200 우상향 ② EMA9 > SMA20 ③ 눌림 = 직전 봉 종가 ≤ SMA20 또는 직전 EMA9 ≤ SMA20
         ④ 반등 = 종가 > EMA9 이고 EMA9 > SMA20   (③④ = 출처 슈도코드 그대로)
  SHORT: 출처 「가격 < SMA200 = 숏 전용」 → 거울
  손절 : 직전 스윙 로우(SHORT 는 스윙 하이) · 청산 : 종가가 EMA9 를 깨면
숫자: 9·20·200 = 출처. SMA200 기울기 창 · 스윙 창 · 최소 손익비 = 「Claude가 정함」 설정.
"""
from __future__ import annotations

import math
from typing import Any, Callable

FIX = "Fix432"
PREFIX = "TRIMA"
STYPE = "triple_ma"
EMA_FAST, SMA_MID, SMA_LONG = 9, 20, 200   # 출처

SETTINGS: dict[str, tuple[str, str, str]] = {
    "trima_mode": ("shadow", "off | shadow(신호만 기록) | on(실주문)", "Claude가 정함 — 실자금은 사장님이 켠다"),
    "trima_sides": ("LONG,SHORT", "허용 방향", "출처(가격 > SMA200 롱 전용 · < SMA200 숏 전용)"),
    "trima_interval": ("1h", "판정 봉 (1h · 4h · 15m)", "출처 「1시간봉/4시간봉」 → 1h (Claude가 정함)"),
    "trima_capital_usdt": ("10", "1회 진입 증거금(USDT)", "Claude가 정함 — 다른 외부 전략과 같은 10"),
    "trima_risk_pct": ("2", "2% 룰 상한 (외부 전략 공통)", "Claude가 정함"),
    "trima_max_concurrent": ("2", "전용 동시 보유 상한", "Claude가 정함"),
    "trima_cooldown_hours": ("6", "심볼당 신호 뒤 재신호 무시", "Claude가 정함"),
    "trima_slope_bars": ("10", "SMA200 우상향 = 지금 SMA200 > 이 봉 수 전 SMA200", "Claude가 정함 (출처 「우상향」)"),
    "trima_swing_bars": ("10", "손절 = 최근 이 봉 수 최저가(SHORT 최고가)", "Claude가 정함 (출처 「직전 스윙 로우」)"),
    "trima_max_sl_pct": ("8", "손절폭이 이보다 크면 진입 안 함(%)", "Claude가 정함"),
}
_BOUNDS = {"trima_slope_bars": (1, 100), "trima_swing_bars": (3, 60), "trima_max_sl_pct": (0.5, 30.0)}


def _f(raw: Any, default: float, lo: float, hi: float) -> float:
    try:
        x = float(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return x if math.isfinite(x) and lo <= x <= hi else default


def params_from(get: Callable[[str], Any] | None = None) -> dict:
    g = get or (lambda k: SETTINGS[k][0])
    def v(k):
        try:
            return g(k)
        except Exception:  # noqa: BLE001
            return SETTINGS[k][0]
    return {
        "slope": int(_f(v("trima_slope_bars"), 10, *_BOUNDS["trima_slope_bars"])),
        "swing": int(_f(v("trima_swing_bars"), 10, *_BOUNDS["trima_swing_bars"])),
        "max_sl": _f(v("trima_max_sl_pct"), 8.0, *_BOUNDS["trima_max_sl_pct"]),
    }


def min_bars(p: dict | None = None) -> int:
    p = p or params_from()
    return SMA_LONG + p["slope"] + 2


def ema(c: list[float], n: int) -> list[float]:
    """pandas ewm(span=n, adjust=False) — 첫 값 시드."""
    if not c:
        return []
    a = 2.0 / (n + 1)
    out = [c[0]]
    for x in c[1:]:
        out.append(a * x + (1 - a) * out[-1])
    return out


def sma(c: list[float], n: int) -> list:
    out: list = [None] * len(c)
    s = 0.0
    for i, x in enumerate(c):
        s += x
        if i >= n:
            s -= c[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def indicators(c: list[float]) -> dict:
    return {"e9": ema(c, EMA_FAST), "s20": sma(c, SMA_MID), "s200": sma(c, SMA_LONG)}


def signal(h, lo, c, j: int, side: str, p: dict | None = None, ind: dict | None = None) -> tuple[bool, dict]:
    """j = 가장 최근 완성봉. 미래 참조 없음."""
    p = p or params_from()
    ind = ind or indicators(c)
    e9, s20, s200 = ind["e9"], ind["s20"], ind["s200"]
    d: dict[str, Any] = {"side": side}
    if j - p["slope"] < 0 or j >= len(c) or s200[j - p["slope"]] is None or s20[j - 1] is None:
        d["why"] = "봉 부족"
        return False, d
    up = side == "LONG"
    sgn = 1 if up else -1
    d["macro"] = sgn * (c[j] - s200[j]) > 0 and sgn * (s200[j] - s200[j - p["slope"]]) > 0   # ① 대세 + 기울기
    d["aligned"] = sgn * (e9[j] - s20[j]) > 0                                               # ② EMA9 vs SMA20
    d["pullback"] = sgn * (c[j - 1] - s20[j - 1]) <= 0 or sgn * (e9[j - 1] - s20[j - 1]) <= 0   # ③ 눌림
    d["trigger"] = sgn * (c[j] - e9[j]) > 0                                                  # ④ 반등
    w0 = max(0, j - p["swing"] + 1)
    stop = min(lo[w0:j + 1]) if up else max(h[w0:j + 1])
    d["stop"] = stop
    d["sl_pct"] = round(abs(c[j] - stop) / c[j] * 100, 3) if c[j] > 0 else None
    # 손절가가 진입가의 올바른 쪽에 있어야 한다 (교차 감사: 저가 > 종가 같은 이상 봉이면 abs 로는 못 거른다)
    d["sl_ok"] = d["sl_pct"] is not None and 0 < d["sl_pct"] <= p["max_sl"] and sgn * (c[j] - stop) > 0
    d["e9"], d["s20"], d["s200"] = e9[j], s20[j], s200[j]
    ok = d["macro"] and d["aligned"] and d["pullback"] and d["trigger"] and d["sl_ok"]
    return bool(ok), d


def _finite(*xs) -> bool:
    return all(x is not None and isinstance(x, (int, float)) and math.isfinite(x) for x in xs)


def evaluate(bars: list, j: int, side: str, p: dict | None = None, cache: dict | None = None) -> tuple[bool, dict]:
    """워커·가상 공용 어댑터. bars = [[open_time, o, h, l, c, v, ...], ...]."""
    try:
        if cache is not None and "arr" in cache:
            h, lo, c, ind = cache["arr"]
        else:
            h, lo, c = ([float(b[i]) for b in bars] for i in (2, 3, 4))
            ind = indicators(c)
            if cache is not None:
                cache["arr"] = (h, lo, c, ind)
        if not (0 <= j < len(c)) or not _finite(*c[max(0, j - SMA_LONG - 20):j + 1], *h[max(0, j - 60):j + 1], *lo[max(0, j - 60):j + 1]):
            return False, {"why": "값 이상"}
        return signal(h, lo, c, j, side, p, ind)
    except (TypeError, ValueError, IndexError) as e:
        return False, {"why": f"입력 오류: {e}"}


# ───────── 가상매매 — 15분봉으로 판정 (가상 엔진 시리즈 = 15분 260봉; SMA200 가능. 출처 봉 1시간은 워커 그림자로) ─────────
PAPER_PARAMS: dict[str, Any] = params_from()


def set_paper_params(settings_get) -> None:
    global PAPER_PARAMS
    try:
        PAPER_PARAMS = params_from(settings_get)
    except Exception:  # noqa: BLE001
        pass


def _paper(ctx: Any, side: str) -> bool:
    kl = getattr(ctx, "kl15", None) or []
    if len(kl) < min_bars(PAPER_PARAMS):
        return False
    return bool(evaluate(kl, len(kl) - 1, side, PAPER_PARAMS)[0])


def _r_l(ctx): return _paper(ctx, "LONG")
def _r_s(ctx): return _paper(ctx, "SHORT")


PAPER_RULES: tuple[tuple[str, str, str, Any], ...] = (
    ("trima_long_15m", "LONG", "3중 이평 LONG(15분): 가격>SMA200↑ · EMA9>SMA20 · 눌림 뒤 종가>EMA9 (Fix 432, shadow)", _r_l),
    ("trima_short_15m", "SHORT", "3중 이평 SHORT(15분): 가격<SMA200↓ · EMA9<SMA20 · 되돌림 뒤 종가<EMA9 (Fix 432, shadow)", _r_s),
)
