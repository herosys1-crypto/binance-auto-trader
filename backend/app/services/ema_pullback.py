"""📈 Fix 423 (2026-10-09) — EMA 추세 눌림 전략 (사장님 첨부 YAML 「Trading_Rules」 → 외부 전략 3번째 가족).

출처 규칙 (verbatim 요지):
  Trend_Filter   : Price > EMA20 & EMA20 기울기 UP → LONG ONLY / Price < EMA20 & 기울기 DOWN → SHORT ONLY
  Entry_Triggers : EMA 정배열(10 > 20 > 50) · EMA20/EMA50 까지 눌림 대기 · 거래량 확인 · 봉 마감 확정 뒤 진입
  Risk_Management: 손절 = 최근 박스(횡보) 저점 아래 (큰 추세는 EMA200 이탈) · 여러 지표(EMA+피보나치+거래량)가 겹칠 때만 30~50% 증액

출처에 숫자가 없는 곳은 설정 키로 뺐다(「Claude가 정함」). 판정은 **15분 완성봉** 기준(외부 전략 공통, ext_interval).
증액(30~50%)은 1차 버전에서 **실행하지 않고** 「겹침(confluence)」 여부만 기록한다 — 그림자 성과로 증액 효과를 먼저 본다.
실주문은 기본 꺼짐(shadow). 켜기는 사장님(관제실 ⑥ 외부 매매법).
"""
from __future__ import annotations

from typing import Any, Sequence

FIX = "Fix423"
PREFIX, STYPE = "EMAPB", "ema_pullback"

# ───────── 출처 숫자 (verbatim) ─────────
EMA_FAST, EMA_MID, EMA_SLOW, EMA_MACRO = 10, 20, 50, 200
FIB_LO, FIB_HI = 0.382, 0.618                # 「Fibonacci」 — 통상 되돌림 구간 (출처는 지표 이름만)
SCALE_UP_PCT = (30.0, 50.0)                  # 「Scale up (30-50%)」 — 1차 버전은 기록만

# ───────── 설정 키 (key: (기본값, 설명, 출처)) — external_strategies.SETTINGS 에 합쳐진다 ─────────
SETTINGS: dict[str, tuple[str, str, str]] = {
    "emapb_mode": ("shadow", "off | shadow(신호만 기록) | on(실주문)", "Claude가 정함 — 실자금은 사장님이 켠다"),
    "emapb_sides": ("LONG,SHORT", "허용 방향", "출처(LONG ONLY / SHORT ONLY 양쪽)"),
    "emapb_capital_usdt": ("10", "1회 진입 증거금(USDT)", "Claude가 정함 — 실주문 규칙 가족과 같은 10"),
    "emapb_risk_pct": ("2", "2% 룰 상한 (외부 전략 공통)", "Claude가 정함"),
    "emapb_max_concurrent": ("2", "전용 동시 보유 상한", "Claude가 정함"),
    "emapb_cooldown_hours": ("4", "심볼당 진입(또는 그림자 신호) 뒤 재신호 무시 시간", "Claude가 정함"),
    "emapb_slope_bars": ("3", "EMA20 기울기 = 지금 vs N봉 전", "Claude가 정함 (출처 「slope UP」)"),
    "emapb_touch_bars": ("5", "최근 N봉 안에 EMA20/50 에 닿았으면 눌림", "Claude가 정함 (출처 「Wait for pullback」)"),
    "emapb_touch_tol_pct": ("0.2", "닿음 허용 오차(가격 %)", "Claude가 정함"),
    "emapb_vol_mult": ("1.2", "확정봉 거래량 ≥ 직전 20봉 평균 × 이 배수", "Claude가 정함 (출처 「Volume Support」)"),
    "emapb_box_bars": ("10", "손절 = 최근 N봉 박스 저점(SHORT 는 고점)", "Claude가 정함 (출처 「recent consolidation low」)"),
    "emapb_fib_bars": ("40", "피보나치 기준 스윙(최근 N봉 고저)", "Claude가 정함"),
}

VOL_N = 20                                   # 평균 거래량 창 (Claude가 정함)
# 설정 허용 범위 (교차 감사: nan·inf·음수가 판정을 깨거나 「거래량 0 도 통과」를 만들지 않게) — 벗어나면 기본값
_BOUNDS: dict[str, tuple[float, float]] = {
    "emapb_slope_bars": (1, 50), "emapb_touch_bars": (1, 50), "emapb_touch_tol_pct": (0.0, 5.0),
    "emapb_vol_mult": (0.5, 10.0), "emapb_box_bars": (2, 90), "emapb_fib_bars": (5, 90),
}


def _f(settings_get, key: str) -> float:
    import math
    default = float(SETTINGS[key][0])
    try:
        x = float(settings_get(key))
    except (TypeError, ValueError):
        return default
    lo_, hi_ = _BOUNDS.get(key, (-math.inf, math.inf))
    return x if math.isfinite(x) and lo_ <= x <= hi_ else default


def params_from(settings_get=None) -> dict[str, float]:
    """설정 읽기 함수(key → 문자열)를 받아 판정 인자 묶음을 만든다. None 이면 기본값."""
    g = settings_get or (lambda k: SETTINGS[k][0])
    return {
        "slope_bars": int(_f(g, "emapb_slope_bars")), "touch_bars": int(_f(g, "emapb_touch_bars")),
        "touch_tol_pct": _f(g, "emapb_touch_tol_pct"), "vol_mult": _f(g, "emapb_vol_mult"),
        "box_bars": int(_f(g, "emapb_box_bars")), "fib_bars": int(_f(g, "emapb_fib_bars")),
    }


# 가상매매 판정 인자 — 가상매매 워커가 사이클마다 운영 설정으로 갱신한다 (교차 감사: 실판정과 같은 숫자로 측정)
PAPER_PARAMS: dict[str, float] = params_from()


def set_paper_params(settings_get) -> None:
    global PAPER_PARAMS
    try:
        PAPER_PARAMS = params_from(settings_get)
    except Exception:  # noqa: BLE001 — 실패하면 직전 값 유지
        pass


def min_bars(p: dict[str, float] | None = None) -> int:
    p = p or params_from()
    return max(EMA_MACRO, int(p["fib_bars"]), int(p["box_bars"]), VOL_N, int(p["touch_bars"]), int(p["slope_bars"])) + 5


def emas(c: Sequence[float]) -> dict[int, list[float]]:
    from app.services.external_strategies import ema      # 지연 import — external_strategies 가 이 모듈의 SETTINGS 를 합친다(순환 방지)
    return {n: ema(c, n) for n in (EMA_FAST, EMA_MID, EMA_SLOW, EMA_MACRO)}


def signal(c: Sequence[float], h: Sequence[float], lo: Sequence[float], v: Sequence[float], j: int, side: str,
           p: dict[str, float] | None = None, e: dict[int, list[float]] | None = None) -> tuple[bool, dict[str, Any]]:
    """j 봉(완성봉)에서 성립? (bool, 상세). 상세: trend·align·pullback·volume·stop·fib_ok·confluence·macro."""
    p = p or params_from()
    d: dict[str, Any] = {"trend": False, "align": False, "pullback": False, "volume": False, "stop": None,
                         "fib": None, "fib_ok": False, "confluence": False, "macro": None, "vol_ratio": None}
    if side not in ("LONG", "SHORT") or j < min_bars(p) - 5 or j >= len(c) or j < 1:
        return False, d
    e = e or emas(c)
    e10, e20, e50, e200 = e[EMA_FAST], e[EMA_MID], e[EMA_SLOW], e[EMA_MACRO]
    sb, tb = max(1, int(p["slope_bars"])), max(1, int(p["touch_bars"]))
    tol = p["touch_tol_pct"] / 100.0
    long_ = side == "LONG"

    # ① 추세 필터 + ② 정배열
    if long_:
        d["trend"] = c[j] > e20[j] and e20[j] > e20[j - sb]
        d["align"] = e10[j] > e20[j] > e50[j]
    else:
        d["trend"] = c[j] < e20[j] and e20[j] < e20[j - sb]
        d["align"] = e10[j] < e20[j] < e50[j]

    # ③ 눌림: 최근 tb 봉(확정봉 포함) 안에 EMA20 또는 EMA50 에 닿았고, 그 사이 종가가 EMA50 을 깨지 않았다.
    #    확정: 이번 봉이 EMA20 위(아래)로 마감 + 직전 종가보다 위(아래) — 「candle close confirmation」
    a = j - tb + 1
    if long_:
        touched = any(lo[i] <= e20[i] * (1 + tol) or lo[i] <= e50[i] * (1 + tol) for i in range(a, j + 1))
        held = all(c[i] >= e50[i] * (1 - tol) for i in range(a, j + 1))
        confirm = c[j] > e20[j] and c[j] > c[j - 1]
    else:
        touched = any(h[i] >= e20[i] * (1 - tol) or h[i] >= e50[i] * (1 - tol) for i in range(a, j + 1))
        held = all(c[i] <= e50[i] * (1 + tol) for i in range(a, j + 1))
        confirm = c[j] < e20[j] and c[j] < c[j - 1]
    d["pullback"] = bool(touched and held and confirm)

    # ④ 거래량: 확정봉 거래량 ≥ 직전 20봉 평균 × 배수
    base = [float(x) for x in v[j - VOL_N:j]]
    avg = sum(base) / len(base) if base else 0.0
    if avg > 0:
        d["vol_ratio"] = float(v[j]) / avg
        d["volume"] = d["vol_ratio"] >= p["vol_mult"]

    # 손절 = 최근 박스 저점(고점). 큰 추세 기준선(EMA200)은 기록만 — 위치 판단은 그림자 성과로 본다.
    bb = max(1, int(p["box_bars"]))
    d["stop"] = min(lo[j - bb + 1:j + 1]) if long_ else max(h[j - bb + 1:j + 1])
    d["macro"] = (c[j] > e200[j]) if long_ else (c[j] < e200[j])
    d["ema200"] = e200[j]

    # 증액 조건(기록만): 눌림 깊이가 최근 스윙의 피보나치 0.382~0.618 + 거래량 확인
    fb = max(5, int(p["fib_bars"]))
    sw_hi, sw_lo = max(h[j - fb + 1:j + 1]), min(lo[j - fb + 1:j + 1])
    rng = sw_hi - sw_lo
    if rng > 0:
        if long_:
            depth = (sw_hi - min(lo[a:j + 1])) / rng
        else:
            depth = (max(h[a:j + 1]) - sw_lo) / rng
        d["fib"] = round(depth, 4)
        d["fib_ok"] = FIB_LO <= depth <= FIB_HI
    d["confluence"] = bool(d["fib_ok"] and d["volume"] and d["align"])

    ok = bool(d["trend"] and d["align"] and d["pullback"] and d["volume"])
    return ok, d


# ───────── 가상매매(chart_learning.RULES) — 시리즈당 EMA 1회 캐시 ─────────
_EMA_CACHE: dict[tuple[int, int], tuple[Any, dict[int, list[float]]]] = {}
_EMA_CACHE_MAX = 6


def _emas_of(ctx: Any) -> dict[int, list[float]]:
    key = (id(ctx.c), len(ctx.c))
    hit = _EMA_CACHE.get(key)
    if hit is not None and hit[0] is ctx.c:       # 교차 감사: id 재사용(다른 심볼 리스트) 방지 — 원본 참조를 쥐고 동일성 확인
        return hit[1]
    e = emas(ctx.c)
    if len(_EMA_CACHE) >= _EMA_CACHE_MAX:
        _EMA_CACHE.pop(next(iter(_EMA_CACHE)))
    _EMA_CACHE[key] = (ctx.c, e)
    return e


def _paper(ctx: Any, side: str) -> bool:
    return signal(ctx.c, ctx.h, ctx.l, ctx.v, ctx.j, side, PAPER_PARAMS, e=_emas_of(ctx))[0]


def _r_long(ctx: Any) -> bool: return _paper(ctx, "LONG")
def _r_short(ctx: Any) -> bool: return _paper(ctx, "SHORT")


PAPER_RULES: tuple[tuple[str, str, str, Any], ...] = (
    ("emapb_long", "LONG", "EMA 눌림 LONG: 가격>EMA20↑ · 10>20>50 · 20/50 눌림 · 거래량 · 마감 확정 (Fix 423, shadow)", _r_long),
    ("emapb_short", "SHORT", "EMA 눌림 SHORT: 가격<EMA20↓ · 10<20<50 · 20/50 되돌림 · 거래량 · 마감 확정 (Fix 423, shadow)", _r_short),
)
