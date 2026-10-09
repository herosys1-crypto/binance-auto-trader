"""📈 Fix 423 (2026-10-09) — EMA 추세 눌림 전략 (사장님 첨부 YAML 「Trading_Rules」 → 외부 전략 3번째 가족).

출처 규칙 (verbatim 요지):
  Trend_Filter   : Price > EMA20 & EMA20 기울기 UP → LONG ONLY / Price < EMA20 & 기울기 DOWN → SHORT ONLY
  Entry_Triggers : EMA 정배열(10 > 20 > 50) · EMA20/EMA50 까지 눌림 대기 · 거래량 확인 · 봉 마감 확정 뒤 진입
  Risk_Management: 손절 = 최근 박스(횡보) 저점 아래 (큰 추세는 EMA200 이탈) · 여러 지표(EMA+피보나치+거래량)가 겹칠 때만 30~50% 증액

출처에 숫자가 없는 곳은 설정 키로 뺐다(「Claude가 정함」).
🗓 Fix 424 (2026-10-09 사장님 「전부 일봉」): 추세·정배열·눌림·거래량·확정 모두 **일봉 완성봉** 기준 (`emapb_interval` = 1d).
   + 「진입 준비」 알림(텔레그램 + 화면): 추세·정배열이 맞고 **현재가**가 EMA20 근처로 눌려 온 상태 — 사장님이 직접 매매할 때 쓰는 신호.
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
    "emapb_cooldown_hours": ("20", "심볼당 진입(또는 그림자 신호) 뒤 재신호 무시 시간 (일봉: 다음 날 신호는 허용 — 판정 시각 흔들림 여유)", "Claude가 정함"),
    "emapb_interval": ("1d", "판정 봉 (1d 일봉 · 4h · 15m)", "사장님 10/09 「전부 일봉」"),
    "emapb_ready_near_pct": ("2", "진입 준비 = 현재가가 EMA20 의 이 % 안 (LONG 은 위쪽, SHORT 는 아래쪽)", "Claude가 정함"),
    "emapb_max_ext_pct": ("10", "진입 신호 = 확정봉 종가가 EMA20 에서 이 % 안 (멀리 달아난 날 추격 금지, Fix 425)", "사장님 10/09 「1번 진행」 (예 10%)"),
    "emapb_coin_only": ("1", "코인 무기한만 감시·판정 (1=주식·금·원유 등 TradFi 제외, Fix 425)", "사장님 10/09 「2번 진행」"),
    "emapb_alert_enabled": ("1", "진입 준비·진입 신호 텔레그램 알림 (1=켬 0=끔, 화면 카드는 항상)", "사장님 10/09 「텔레그램 + 화면」"),
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
    "emapb_max_ext_pct": (0.5, 100.0),
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
        "max_ext_pct": _f(g, "emapb_max_ext_pct"),
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
    """판정에 필요한 최소 봉 수. EMA200 은 기록 전용이라 넣지 않는다(일봉 = 상장 200일 미만 코인도 판정, Fix 424)."""
    p = p or params_from()
    return max(EMA_SLOW + 10, int(p["fib_bars"]), int(p["box_bars"]), VOL_N, int(p["touch_bars"]), int(p["slope_bars"])) + 5


def emas(c: Sequence[float]) -> dict[int, list[float]]:
    from app.services.external_strategies import ema      # 지연 import — external_strategies 가 이 모듈의 SETTINGS 를 합친다(순환 방지)
    return {n: ema(c, n) for n in (EMA_FAST, EMA_MID, EMA_SLOW, EMA_MACRO)}


def signal(c: Sequence[float], h: Sequence[float], lo: Sequence[float], v: Sequence[float], j: int, side: str,
           p: dict[str, float] | None = None, e: dict[int, list[float]] | None = None) -> tuple[bool, dict[str, Any]]:
    """j 봉(완성봉)에서 성립? (bool, 상세). 상세: trend·align·pullback·volume·stop·fib_ok·confluence·macro."""
    p = p or params_from()
    d: dict[str, Any] = {"trend": False, "align": False, "pullback": False, "volume": False, "stop": None,
                         "fib": None, "fib_ok": False, "confluence": False, "macro": None, "vol_ratio": None,
                         "ext_pct": None, "near": False}
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
    if j >= EMA_MACRO:                           # EMA200 은 200봉 이상일 때만 의미 — 모자라면 기록하지 않는다 (Fix 424)
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

    # ⑤ Fix 425 (사장님 10/09): 확정봉 종가가 EMA20 에서 너무 멀면(추격) 신호 아님 — OGN 종가가 EMA20 의 2배였던 신호 차단
    ext = ((c[j] - e20[j]) if long_ else (e20[j] - c[j])) / e20[j] * 100.0 if e20[j] else None
    d["ext_pct"] = ext
    d["near"] = ext is not None and ext <= float(p.get("max_ext_pct", 10.0))

    ok = bool(d["trend"] and d["align"] and d["pullback"] and d["volume"] and d["near"])
    return ok, d


# ───────── Fix 425 (사장님 10/09 「2번」): 코인 무기한만 ─────────
def is_coin_row(raw: Any, contract_type: Any) -> bool:
    """거래소 정보 underlyingType == COIN (없으면 contract_type == PERPETUAL). 주식·금·원유 = TRADIFI_PERPETUAL."""
    ut = (raw or {}).get("underlyingType") if isinstance(raw, dict) else None
    if ut:
        return str(ut).upper() == "COIN"
    return str(contract_type or "").upper() == "PERPETUAL"


def coin_symbols(db, symbols) -> list[str]:
    """symbols 중 코인 무기한만 (순서 유지).

    교차 감사: 호출한 워커의 세션을 건드리지 않게 **조회 전용 세션**을 따로 연다(db=None 이면). 실패해도 워커 세션은 rollback 하지 않는다.
    조회 실패·0행(종목 표 비었음·표기 불일치) = 거르지 않고 그대로 — 알림·판정이 통째로 멈추지 않게, 경고만 남긴다.
    db 를 넘기면(테스트) 그 객체로 조회만 한다.
    """
    import logging
    log = logging.getLogger(__name__)
    syms = list(symbols)
    if not syms:
        return syms
    own = db is None
    s_ = None
    try:
        from sqlalchemy import select
        from app.models.symbol import Symbol
        if own:
            from app.core.database import SessionLocal
            s_ = SessionLocal()
        rows = (s_ if own else db).execute(select(Symbol.symbol, Symbol.raw_exchange_info, Symbol.contract_type)
                                           .where(Symbol.symbol.in_(syms))).all()
    except Exception as e:  # noqa: BLE001
        log.warning("[Fix425] 코인 여부 조회 실패 → 거르지 않음: %s", e)
        return syms
    finally:
        if s_ is not None:
            try:
                s_.close()
            except Exception:  # noqa: BLE001
                pass
    if not rows:
        log.warning("[Fix425] 종목 표에서 %d개 중 0개 찾음 → 거르지 않음 (종목 동기화 확인)", len(syms))
        return syms
    ok = {r[0] for r in rows if is_coin_row(r[1], r[2])}
    return [s for s in syms if s in ok]


def coin_only_on(settings_get) -> bool:
    return str(settings_get("emapb_coin_only") or "1").strip().lower() not in ("0", "false", "off", "no")


# ───────── 🗓 Fix 424 진입 준비 (사장님 수동 매매용 알림) ─────────
def ready_state(c: Sequence[float], h: Sequence[float], lo: Sequence[float], v: Sequence[float], live: float, side: str,
                p: dict[str, float] | None = None, e: dict[int, list[float]] | None = None,
                near_pct: float = 2.0) -> tuple[bool, dict[str, Any]]:
    """마지막 완성봉 기준 추세·정배열이 맞고, 진행 중 봉의 현재가(live)가 EMA20 근처까지 눌려 왔나.

    LONG : EMA20×(1−허용오차) ≤ 현재가 ≤ EMA20×(1+near%) 이고 현재가 ≥ EMA50×(1−허용오차)
    SHORT: 반대. 진입 신호(마감 확정)는 아직 아님 — 「준비」다. 상세에 EMA20·EMA50·거리%·예상 손절가.
    """
    p = p or params_from()
    j = len(c) - 1
    d: dict[str, Any] = {"trend": False, "align": False, "dist_pct": None, "ema20": None, "ema50": None, "stop": None}
    if side not in ("LONG", "SHORT") or j < min_bars(p) - 5 or not live or live <= 0:
        return False, d
    _ok, sd = signal(c, h, lo, v, j, side, p, e)
    e = e or emas(c)
    e20, e50 = e[EMA_MID][j], e[EMA_SLOW][j]
    tol = p["touch_tol_pct"] / 100.0
    near = max(0.0, float(near_pct)) / 100.0
    d.update(trend=sd["trend"], align=sd["align"], ema20=e20, ema50=e50, dist_pct=(live - e20) / e20 * 100.0 if e20 else None)
    bb = max(1, int(p["box_bars"]))
    if side == "LONG":
        zone = e20 * (1 - tol) <= live <= e20 * (1 + near) and live > e50          # EMA50 은 허용오차 없이 (교차 감사)
        d["stop"] = min(min(lo[j - bb + 1:j + 1]), live)
    else:
        zone = e20 * (1 - near) <= live <= e20 * (1 + tol) and live < e50
        d["stop"] = max(max(h[j - bb + 1:j + 1]), live)
    return bool(sd["trend"] and sd["align"] and zone), d


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


MS_15M, MS_DAY = 900_000, 86_400_000


def needs_daily(kl15: Sequence[Sequence[float]] | None) -> bool:
    """가상매매 워커가 일봉을 받아야 하나 = 이 15분봉이 UTC 하루의 마지막 봉(일봉 마감 직후 판정). (Fix 424)"""
    try:
        return bool(kl15) and int(kl15[-1][0]) % MS_DAY == MS_DAY - MS_15M
    except (TypeError, ValueError, IndexError):
        return False


# Fix 425: 가상매매 워커가 심볼마다 「이 심볼은 EMA 눌림 판정 대상인가(코인)」를 알려 준다 (RuleCtx 에는 심볼이 없다)
PAPER_SYMBOL_OK: bool = True


def set_paper_symbol_ok(ok: bool) -> None:
    global PAPER_SYMBOL_OK
    PAPER_SYMBOL_OK = bool(ok)


def _paper(ctx: Any, side: str) -> bool:
    """🗓 Fix 424: 일봉 규칙 — 하루 마지막 15분봉에서만, 방금 닫힌 일봉까지로 판정 (하루 한 번)."""
    k1 = getattr(ctx, "kl1d", None)
    if not PAPER_SYMBOL_OK or not needs_daily(getattr(ctx, "kl15", None)) or not k1:
        return False
    try:
        if int(k1[-1][0]) + MS_DAY != int(ctx.kl15[-1][0]) + MS_15M:
            return False                               # 일봉이 방금 닫힌 그날 것이 아니다 (조회 지연·누락) → 판정 안 함
        c = [float(b[4]) for b in k1]
        h = [float(b[2]) for b in k1]
        lo = [float(b[3]) for b in k1]
        v = [float(b[5]) for b in k1]
    except (TypeError, ValueError, IndexError):
        return False
    return signal(c, h, lo, v, len(c) - 1, side, PAPER_PARAMS)[0]


def _r_long(ctx: Any) -> bool: return _paper(ctx, "LONG")
def _r_short(ctx: Any) -> bool: return _paper(ctx, "SHORT")


PAPER_RULES: tuple[tuple[str, str, str, Any], ...] = (
    ("emapb_long", "LONG", "EMA 눌림 LONG(일봉): 가격>EMA20↑ · 10>20>50 · 20/50 눌림 · 거래량 · 마감 확정 (Fix 423·424, shadow)", _r_long),
    ("emapb_short", "SHORT", "EMA 눌림 SHORT(일봉): 가격<EMA20↓ · 10<20<50 · 20/50 되돌림 · 거래량 · 마감 확정 (Fix 423·424, shadow)", _r_short),
)
