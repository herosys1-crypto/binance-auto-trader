"""🌊 Fix 431 (2026-10-10 사장님 첨부 bollinger_wave_trading_strategy.md) — 볼린저 밴드 중심선 파동 돌파 (외부 전략 5번째 가족).

출처(퓨처온TV): 상·하단 역추세가 아니라 **중심선(SMA20)의 방향과 캔들의 중심선 돌파**로 추세 전환을 잡는다. 1분·5분 단타.
  진입(LONG): ① 중심선이 위로 꺾임(mid[k] > mid[k−1]) ② 직전 종가 < 중심선 → 돌파 봉 종가 ≥ 중심선 (슈도코드 그대로)
             ③ 가짜 돌파 거르기 — 돌파 봉 하나로 들어가지 않고 **다음 봉이 중심선 위에서 마감**하면 진입 (거래량 확인)
  손절     : 돌파 봉 시가 · 중심선이 다시 무너지면(종가 < 중심선) 청산 · 손절폭 3~5% 이내
  금지     : 중심선 돌파 시도가 3회 이상 반복된 구간(지지력 약화) · 횡보
숫자: BB 20 · 2.0σ · 「3회」 · 「−3~−5%」 = 출처. 나머지(거래량 배수 · 반복 세는 창 · SHORT 거울)는 「Claude가 정함」 설정.
출처는 LONG 만 규칙으로 적었다(하락 중심선 = 「관망 또는 숏 관점」) → 기본 sides=LONG, SHORT 거울은 설정으로만.
"""
from __future__ import annotations

import math
from typing import Any, Callable

FIX = "Fix431"
PREFIX = "BBWAVE"
STYPE = "bb_wave"
BB_N = 20                 # 출처
BB_K = 2.0                # 출처
MAX_TRIES = 3             # 출처 「3회 이상 반복 → 배제」
SL_MIN_PCT, SL_MAX_PCT = 3.0, 5.0   # 출처 「−3% ~ −5% 이내」

SETTINGS: dict[str, tuple[str, str, str]] = {
    "bbwave_mode": ("shadow", "off | shadow(신호만 기록) | on(실주문)", "Claude가 정함 — 실자금은 사장님이 켠다"),
    "bbwave_sides": ("LONG", "허용 방향 (LONG · SHORT 쉼표)", "출처 = LONG 규칙만 (SHORT 는 거울, Claude가 정함)"),
    "bbwave_interval": ("5m", "판정 봉 (5m · 15m)", "출처 「1분봉 또는 5분봉」 → 5m (1m 은 IP 무게로 제외, Claude가 정함)"),
    "bbwave_capital_usdt": ("10", "1회 진입 증거금(USDT)", "Claude가 정함 — 다른 외부 전략과 같은 10"),
    "bbwave_risk_pct": ("2", "2% 룰 상한 (외부 전략 공통)", "Claude가 정함"),
    "bbwave_max_concurrent": ("2", "전용 동시 보유 상한", "Claude가 정함"),
    "bbwave_cooldown_hours": ("2", "심볼당 신호 뒤 재신호 무시", "Claude가 정함"),
    "bbwave_vol_mult": ("1.0", "돌파 봉 거래량 ≥ 최근 20봉 평균 × 이 값 (0 = 안 봄)", "Claude가 정함 (출처 「거래량을 확인」)"),
    "bbwave_tries_lookback": ("30", "중심선 돌파 시도 횟수를 세는 창(봉)", "Claude가 정함 (출처 「3회 이상 반복」)"),
}
_BOUNDS = {"bbwave_vol_mult": (0.0, 5.0), "bbwave_tries_lookback": (10, 200)}


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
        "vol_mult": _f(v("bbwave_vol_mult"), 1.0, *_BOUNDS["bbwave_vol_mult"]),
        "lookback": int(_f(v("bbwave_tries_lookback"), 30, *_BOUNDS["bbwave_tries_lookback"])),
    }


def min_bars(p: dict | None = None) -> int:
    p = p or params_from()
    return BB_N + p["lookback"] + 5


def bands(c: list[float]) -> tuple[list, list]:
    """중심선 = SMA20, σ = 표본 표준편차(ddof=1 — pandas rolling().std() 와 같음)."""
    n = len(c)
    mid: list = [None] * n
    sd: list = [None] * n
    for i in range(BB_N - 1, n):
        w = c[i - BB_N + 1:i + 1]
        m = sum(w) / BB_N
        mid[i] = m
        sd[i] = math.sqrt(sum((x - m) ** 2 for x in w) / (BB_N - 1))
    return mid, sd


def signal(o, h, lo, c, v, j: int, side: str, p: dict | None = None, ind: tuple | None = None) -> tuple[bool, dict]:
    """j = 확인 봉(가장 최근 완성봉). 돌파 봉 k = j−1. 미래 참조 없음(j 까지만 읽음)."""
    p = p or params_from()
    mid, _sd = ind or bands(c)
    d: dict[str, Any] = {"side": side}
    k = j - 1
    if k - 1 < 0 or mid[k - 1] is None or j >= len(c):
        d["why"] = "봉 부족"
        return False, d
    up = side == "LONG"
    sgn = 1 if up else -1
    d["slope_turn"] = sgn * (mid[k] - mid[k - 1]) > 0                       # ① 중심선이 진행 방향으로 꺾임
    d["cross"] = sgn * (c[k - 1] - mid[k - 1]) < 0 and sgn * (c[k] - mid[k]) >= 0   # ② 돌파 봉
    d["confirm"] = sgn * (c[j] - mid[j]) > 0                                # ③ 다음 봉도 중심선 너머에서 마감
    if p["vol_mult"] > 0 and k >= 20:
        avg = sum(v[k - 20:k]) / 20
        d["vol_ok"] = avg > 0 and v[k] >= p["vol_mult"] * avg
    else:
        d["vol_ok"] = True
    # 금지: 창 안에서 같은 방향 돌파 시도(종가가 중심선을 넘은 횟수)가 이미 3회 이상 = 지지력 약화
    tries = 0
    for i in range(max(BB_N, k - p["lookback"]), k):
        if mid[i - 1] is not None and sgn * (c[i - 1] - mid[i - 1]) < 0 and sgn * (c[i] - mid[i]) >= 0:
            tries += 1
    d["tries"] = tries
    d["tries_ok"] = tries < MAX_TRIES
    # 손절 = 돌파 봉 시가, 손절폭은 출처 3~5% 안으로 (가까우면 3%, 멀면 5% 로 자름)
    entry = c[j]
    raw = abs(entry - o[k]) / entry * 100 if entry > 0 else 0.0
    risk = min(max(raw, SL_MIN_PCT), SL_MAX_PCT)
    d["stop"] = entry * (1 - risk / 100) if up else entry * (1 + risk / 100)
    d["sl_pct"] = round(risk, 3)
    d["mid"] = mid[j]
    ok = d["slope_turn"] and d["cross"] and d["confirm"] and d["vol_ok"] and d["tries_ok"]
    return bool(ok), d


def _finite(*xs) -> bool:
    return all(x is not None and isinstance(x, (int, float)) and math.isfinite(x) for x in xs)


def evaluate(bars: list, j: int, side: str, p: dict | None = None, cache: dict | None = None) -> tuple[bool, dict]:
    """워커·가상 공용 어댑터. bars = [[open_time, o, h, l, c, v, ...], ...]. cache 로 같은 봉 묶음의 지표를 한 번만 계산."""
    try:
        if cache is not None and "arr" in cache:
            o, h, lo, c, v, ind = cache["arr"]
        else:
            o, h, lo, c, v = ([float(b[i]) for b in bars] for i in (1, 2, 3, 4, 5))
            ind = bands(c)
            if cache is not None:
                cache["arr"] = (o, h, lo, c, v, ind)
        pp = p or params_from()
        w0 = max(0, j - 1 - pp["lookback"] - BB_N - 2)          # 판정이 읽는 구간 전부(반복 세기 창 + 중심선 20봉) — 교차 감사
        if not (1 <= j < len(c)) or not _finite(*c[w0:j + 1], o[j - 1], *v[max(0, j - 21):j]):
            return False, {"why": "값 이상"}
        return signal(o, h, lo, c, v, j, side, p, ind)
    except (TypeError, ValueError, IndexError) as e:
        return False, {"why": f"입력 오류: {e}"}


# ───────── 가상매매 — 15분봉으로 판정 (가상 엔진 시리즈가 15분이다; 출처 봉 5분은 워커 그림자로) ─────────
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
    ("bbwave_long_15m", "LONG", "볼린저 중심선 파동 LONG(15분): 중심선 상향 꺾임 · 돌파 · 다음 봉 확인 · 거래량 · 반복<3 (Fix 431, shadow)", _r_l),
    ("bbwave_short_15m", "SHORT", "볼린저 중심선 파동 SHORT(15분, 거울): 중심선 하향 꺾임 · 하향 돌파 · 확인 (Fix 431, shadow)", _r_s),
)
