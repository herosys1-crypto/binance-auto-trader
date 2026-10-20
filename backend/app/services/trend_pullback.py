"""🏔 Fix 475 (2026-10-21 사장님 「a b로 해줘」) — 정상 추세 눌림 LONG(대형) · 외부 전략 7번째 가족 (일봉 · 기본 그림자).

사장님 그림 ①(verbatim 요지): 「일봉이 지속적으로 상승하면서 볼밴 중단을 지지하고 다시 상승, 좀더 심하면 볼밴 하단까지 왔다가 다시 지속 상승」
  = 「코인 자체적인 상승 이슈」 (② 며칠~몇 주 급등·③ 당일 급등은 세력 장난 — 이 가족은 ① 만 LONG)
근거 [[일봉 세 그림 연구 2026-10-21]] (공개 일봉 517종목·4년, daily_three_patterns_2026_10_21.py 의 L1):
  전체 R +0.03(760) ≈ 0 · **시총 10억$↑ +0.22(160, 앞 +0.17 / 뒤 +0.28)** → 대형만. 수수료·펀딩 미반영 · 지금 상장 종목만.
판정(일봉 마감 봉 j, j 뒤 봉 안 읽음 — 숫자 「Claude가 정함」, 연구 L1 그대로):
  ① 중단(SMA20) > 10일 전 중단 ② 직전 10일 중 7일↑ 종가 > 중단
  ③ 직전 30일 고점 / 그 전 60일 최저 − 1 ≥ 30% ④ 하루 상승률(상승폭 ÷ 일수) < 1% (완만 = 코인 자체 상승)
  ⑤ 저가 ≤ 중단 (하단까지 내려가도 포함) ⑥ (설정) 종가 ≥ 중단
  손절 = max(min(하단 × 0.97, 종가 × 0.97), 종가 × 0.85) → 3~15% · 목표 = 직전 고점 (연구: 최대 40일)
  대형 = 시총 ≥ trpb_min_mcap_usd (coin_mcap, 받은 날 값 · 모름 = 안 봄)
레버리지 안전([[feedback-leverage-safety]]): 손절 ≤ 15% × 외부 전략 레버리지 2 = 증거금 −30% 안 · 청산 거리(≈ −50%) 보다 충분히 가깝다.
실주문: 출처 청산(직전 고점 익절·40일)이 실주문 경로에 없음 → on 이어도 그림자(EXIT_GAP).
"""
from __future__ import annotations

import math
from typing import Any, Callable

FIX = "Fix475"
PREFIX = "TRPB"
STYPE = "trend_pullback"
N, K = 20, 2.0
EXIT_GAP = "출처 청산(직전 고점 익절·최대 40일)이 실주문 경로에 없음 + 그림자 검증 전"

SETTINGS: dict[str, tuple[str, str, str]] = {
    "trpb_mode": ("shadow", "off | shadow(신호만 기록) — on 이어도 전용 청산이 생길 때까지 shadow (Fix 475)", "Claude가 정함 — 실자금은 사장님이 켠다"),
    "trpb_sides": ("LONG", "허용 방향 — LONG 전용", "사장님 그림 ① = 상승"),
    "trpb_interval": ("1d", "판정 봉 — 일봉만", "연구 = 일봉"),
    "trpb_capital_usdt": ("10", "1회 진입 증거금(USDT)", "Claude가 정함 — 다른 외부 전략과 같은 10"),
    "trpb_risk_pct": ("2", "2% 룰 상한 (외부 전략 공통)", "Claude가 정함"),
    "trpb_max_concurrent": ("2", "전용 동시 보유 상한", "Claude가 정함"),
    "trpb_cooldown_hours": ("120", "심볼당 신호 뒤 재신호 무시 (5일 — 같은 눌림 여러 번 안 셈)", "Claude가 정함"),
    "trpb_min_mcap_usd": ("1000000000", "대형 = 시총 이 값 이상 (USD, CoinGecko 받은 날 값)", "연구: 10억$↑ 에서만 + (Claude가 정함)"),
    "trpb_min_gain_pct": ("30", "랠리 = 직전 30일 고점 ÷ 그 전 60일 최저 − 1 ≥ 이 %", "연구 정의 (Claude가 정함)"),
    "trpb_max_speed_pct": ("1.0", "완만 = 하루 상승률 < 이 % (빠르면 세력 랠리)", "연구 정의 (Claude가 정함)"),
    "trpb_require_hold_mid": ("0", "1 = 눌림 날 종가가 중단 위여야 함 (연구 L1 은 0)", "Claude가 정함"),
}
_BOUNDS = {"trpb_min_mcap_usd": (0.0, 1e13), "trpb_min_gain_pct": (5.0, 500.0), "trpb_max_speed_pct": (0.1, 10.0)}


def _f(g: Callable[[str], Any], key: str) -> float:
    d = float(SETTINGS[key][0])
    try:
        x = float(str(g(key)).strip())
    except Exception:  # noqa: BLE001
        return d
    lo, hi = _BOUNDS[key]
    return x if math.isfinite(x) and lo <= x <= hi else d


def params_from(get: Callable[[str], Any] | None = None) -> dict:
    g = get or (lambda k: SETTINGS[k][0])
    try:
        hold = str(g("trpb_require_hold_mid")).strip().lower() in ("1", "true", "on", "yes")
    except Exception:  # noqa: BLE001
        hold = False
    return {"min_mcap": _f(g, "trpb_min_mcap_usd"), "min_gain": _f(g, "trpb_min_gain_pct") / 100,
            "max_speed": _f(g, "trpb_max_speed_pct") / 100, "hold_mid": hold}


def min_bars(p: dict | None = None) -> int:
    return 120                                   # 고점 30 + 그 전 최저 60 + 중단 20 + 비교 10 = 120 안


def _mid_lo(c: list[float], i: int) -> tuple[float, float]:
    w = c[i - N + 1:i + 1]
    m = sum(w) / N
    sd = math.sqrt(sum((x - m) ** 2 for x in w) / N)     # 모집단 σ (연구와 같음)
    return m, m - K * sd


def evaluate(bars: list, j: int, side: str, p: dict | None = None, cache: dict | None = None) -> tuple[bool, dict]:
    """bars = [[open_ms, o, h, l, c, v, ...], ...] · j = 판정 마감 봉. j 뒤 봉은 읽지 않는다."""
    if side != "LONG":
        return False, {"why": "LONG 전용"}
    p = p or params_from()
    try:
        if not (isinstance(j, int) and 0 <= j < len(bars)):
            return False, {"why": "봉 부족"}
        lo_i = max(0, j - 100)                            # 판정이 읽는 가장 앞(최저 탐색 60 + 고점 30 + 여유) — 그 앞·j 뒤 봉은 파싱도 안 한다(Gemini 심판)
        key = (id(bars), len(bars), j)
        if cache is not None and cache.get("k") == key:
            h, lw, c = cache["hlc"]
        else:
            seg = bars[lo_i:j + 1]
            h, lw, c = ([None] * lo_i + [float(b[i]) for b in seg] for i in (2, 3, 4))
            if cache is not None:
                cache.update(k=key, hlc=(h, lw, c))
    except (TypeError, ValueError, IndexError) as e:
        return False, {"why": f"입력 오류: {e}"}
    if j < min_bars(p):
        return False, {"why": "봉 부족"}
    win = h[lo_i:j + 1] + lw[lo_i:j + 1] + c[lo_i:j + 1]
    if any(not math.isfinite(x) or x <= 0 for x in win):
        return False, {"why": "값 이상"}
    mid, lo = _mid_lo(c, j)
    mid10, _ = _mid_lo(c, j - 10)
    d: dict[str, Any] = {"mid": mid, "lower": lo}
    if not mid > mid10:
        return False, {**d, "why": "중단 하락·평평"}
    above = sum(1 for i in range(j - 10, j) if c[i] > _mid_lo(c, i)[0])
    if above < 7:
        return False, {**d, "why": f"중단 위 마감 {above}/10"}
    pk = max(range(j - 30, j), key=lambda i: h[i])        # 같으면 앞쪽
    org = min(range(max(0, pk - 60), pk + 1), key=lambda i: lw[i])
    gain = h[pk] / lw[org] - 1
    speed = gain / max(1, pk - org)
    d.update(target=h[pk], gain=round(gain, 4), speed=round(speed, 5), dd=round(1 - c[j] / h[pk], 4), hold_mid=c[j] >= mid)
    if gain < p["min_gain"]:
        return False, {**d, "why": f"랠리 {gain:.0%} 부족"}
    if not speed < p["max_speed"]:
        return False, {**d, "why": f"하루 {speed:.1%} 가파름(세력 랠리)"}
    if not lw[j] <= mid:
        return False, {**d, "why": "중단까지 안 눌림"}
    if p["hold_mid"] and not d["hold_mid"]:
        return False, {**d, "why": "중단 아래 마감"}
    e = c[j]
    stop = max(min(lo * 0.97, e * 0.97), e * 0.85)
    d.update(stop=stop, sl_pct=round((1 - stop / e) * 100, 3), why="")
    return True, d


def symbol_ok(sym: str, p: dict) -> tuple[bool, str]:
    """공용 루프 거르기 — 대형(시총 ≥ min_mcap)만. 모름 = 안 봄."""
    from app.services import coin_mcap as CM
    mc = CM.get(sym)
    if mc is None:
        return False, "시총 모름"
    return (True, "") if mc >= p["min_mcap"] else (False, "시총 작음")


# ───────── 가상매매 — 일봉 마감 뒤 1시간 창 · 하루 1회 (EMA 눌림·볼린저 EMA 와 같은 장치) ─────────
PAPER_PARAMS: dict = params_from()
PAPER_SYMBOL: str | None = None


def set_paper_params(get) -> None:
    global PAPER_PARAMS
    try:
        PAPER_PARAMS = params_from(get)
    except Exception:  # noqa: BLE001
        pass


def set_paper_symbol(sym: str | None) -> None:
    global PAPER_SYMBOL
    PAPER_SYMBOL = sym


def _daily_fresh(ctx: Any) -> bool:
    from app.services.ema_pullback import daily_is_fresh
    return daily_is_fresh(getattr(ctx, "kl1d", None), getattr(ctx, "kl15", None))


DAILY_FRESH: Callable[[Any], bool] = _daily_fresh


def _r_all(ctx) -> bool:
    k1 = getattr(ctx, "kl1d", None)
    if not k1 or not DAILY_FRESH(ctx):
        return False
    return bool(evaluate(k1, len(k1) - 1, "LONG", PAPER_PARAMS)[0])


def _r_big(ctx) -> bool:
    if not _r_all(ctx) or not PAPER_SYMBOL:
        return False
    from app.services import coin_mcap as CM
    mc = CM.get(PAPER_SYMBOL)
    return mc is not None and mc >= PAPER_PARAMS["min_mcap"]


PAPER_RULES: tuple[tuple[str, str, str, Any], ...] = (
    ("trpb_long", "LONG", "정상 추세 눌림 LONG(일봉, 전체): 중단↑ · 10일 중 7일 중단 위 · 랠리 +30%↑ 완만(하루<1%) · 저가≤중단 (Fix 475, shadow)", _r_all),
    ("trpb_long_big", "LONG", "정상 추세 눌림 LONG(일봉, 시총 10억$↑): 위 조건 + 대형 (Fix 475, shadow)", _r_big),
)
