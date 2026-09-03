"""📐 지지선 판정 7점 — 「반등하는가 / 더 내려가는가」 (Fix 327).

## 사장님 지시 (2026-09-03)

  "차트와 보조지표 급등과 급락 그리고 보합 그리고 **다시 지지반등과 지지선
   추가 하락**시 보조지표의 움직임과 수치를 전문가가 분석해서 **수치화**해서
   내가 시스템에 만들고자한 로직으로 만들어줘"

  "오늘 이런 차트 흐름에 우리 시스템 로직에서 포지션 진입을 할수 있고
   진입해서 손절하고 다시 진입해서 수익을 낼수있는 시스템 로직이 필요해"

## 🚨 가장 중요한 발견 — 「반등을 보고 들어가면 진다」

차트분석 에이전트팀이 30심볼 × 15m/1h/4h × 300봉으로 실측한 결과,
**반등의 「신호」로 흔히 쓰는 것들이 전부 반대이거나 아티팩트**였다:

    아래꼬리가 길면 반등          d = **-0.45**  (부호 반대)
    RSI 상향 전환이면 반등        d = **-0.303** (부호 반대)
      └ 지지선 지정가로 가정하면 +0.080 으로 뒤집힘 = **순수 진입가 아티팩트**
        ("이미 반등해서 비싸게 사는" 것을 신호로 착각한 것)
    거래량 급증이 반등 신호        두 그룹에서 부호 뒤집힘
    **15m MACD hist 3봉 상승중**  d = **-0.380** ← 채택했으되 **역방향으로**

즉 **오르기 시작한 걸 보고 사면 진다.** 지지선에 **미리 걸어놔야** 이긴다.
이것은 사장님 사상과 정확히 같다 —
  "4H 지속상승 + 지금 4H 조정 → LONG 을 **미리미리 분할**(바닥 확인 X)"

## 판정식 — 7개 규칙 각 1점 (등가중)

가중치를 붙여도 개선되지 않아 등가중을 택했다(단순 = 과적합 방어).

    id                       tf    조건                              해당시 승률  Δ
    h1_macdh_pos             1h    MACD hist > 0                      65.5%   +21.6
    h1_above_ema20           1h    close > EMA20                      65.4%   +19.7
    h1_rsi12_ge_50           1h    RSI(12) >= 50                      64.7%   +18.1
    m15_macdh_not_rising3    15m   **NOT** (hist[i] > hist[i-3])      61.5%   +18.7
    m15_rsi24_ge_45          15m   RSI(24) >= 45                      62.7%   +16.6
    m15_drop96_ge_m15        15m   96봉 고점 대비 낙폭 >= -15%         61.6%   +19.8
    m15_above_ema50          15m   close > EMA50                      67.7%   +17.7

## 판정 결과 (기준선 55.0%, n=264)

    score >= 7   LONG_STRONG   n=47  승률 **76.9%**  (A 78.3 / B 75.0)
    score >= 6   LONG          n=80  승률 **70.6%**  (A 75.0 / B 64.3)
    2 ~ 5        관망          진입 금지
    score <= 1   SHORT         n=67  승률 **63.9%**  (A 72.2 / B 60.5)
    score == 0   SHORT_STRONG  n=22  승률 **71.4%**  (A 80.0 / B 63.6)

**두 그룹(심볼 홀짝 15/15) 모두에서 기준선을 넘는다.** 24h 상승 종목군
(기준선 67.4 → score>=6 74.4)과 하락 종목군(47.0 → 65.5) 양쪽에서 작동한다.

## 지지선 정의 — 9개를 재서 골랐다

**채택: `swing_low`(좌우 3봉 피벗 저점, 96봉 이내)** — OOS 평균 |d| 0.517 로 1위.

🚨 **기각된 것**(그룹을 바꾸면 판정이 정반대):
    볼린저 하단      OOS **-0.125**  ← 접촉은 잦은데(252건) 지지선으로 기능 안 함
    fib 0.5 / 0.618  OOS **-0.72 / -0.66**  ← 완전 반전
    단순 N봉 저점     접촉 자체가 「이미 신저점」이라 BOUNCE 비율 43~49%

## 🚨 재진입에 별도 규칙을 만들지 않는다

사장님 관심사인 「손절하고 다시 진입」을 실측했다:

    직전 접촉이 손절로 끝남   n=55  승률 **49.1%**  (A 52.6 / B 47.1)
    직전 접촉이 반등으로 끝남 n=72  승률   57.4%   (A 56.2 / B 58.3)
    기준선                   n=264 승률   55.0%

**「손절당한 자리가 더 좋다」는 성립하지 않는다.** 접촉 횟수도 두 그룹에서
부호가 뒤집혀(-0.304 / +0.095) 정보가 없다.
→ 재진입도 **같은 score 로 판정**한다. 자본 배수 인상은 근거가 없다.

⚠️ 순진하게 재면 「직전손절 36.8% / 직전반등 69.7%」라는 극적인 값이 나오는데,
   그것은 **미래참조**다(234건 중 102건 = 43.6% 가 이번 접촉 시점에 아직
   결착 나지 않았다). 그 숫자로 코딩하면 안 된다.

## 이 모듈이 답하지 않는 것

**「어디서 사는가」만 답한다.** 「얼마를」은 자본 사다리, 「언제 파는가」는
적응 TP 가 정한다.

근거: `docs/spec/SUPPORT_BOUNCE_VS_BREAKDOWN_2026-09-03.{json,md}`
표본 264건 / 30심볼 / 15분봉 75시간 — 방향은 신뢰할 만하나 절대 승률은 ±5%p.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "SETTING_ENABLED", "SETTING_MIN_LONG", "SETTING_MAX_SHORT",
    "MIN_LONG_DEFAULT", "MAX_SHORT_DEFAULT", "MAX_SCORE",
    "gate_enabled", "min_long_score", "max_short_score",
    "find_swing_low", "is_touching", "compute_score", "decide", "evaluate",
]

SETTING_ENABLED = "support_score_gate_enabled"
SETTING_MIN_LONG = "support_score_min_long"      # 이 점수 이상이면 LONG 허용
SETTING_MAX_SHORT = "support_score_max_short"    # 이 점수 이하면 SHORT 허용

MIN_LONG_DEFAULT = 6        # 승률 70.6% (n=80)
MAX_SHORT_DEFAULT = 1       # 승률 63.9% (n=67)

LOOKBACK_BARS = 96          # 지지선 탐색 범위
PIVOT_HALF_WIDTH = 3        # 좌우 3봉보다 낮아야 피벗 저점
EXCLUDE_RECENT = 4          # 최근 4봉은 아직 피벗 확정 불가
MAX_SCORE = 7


# ══════════════════════════════════════════════════════════════════════
# 설정
# ══════════════════════════════════════════════════════════════════════

def _setting(db, key: str):
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, key)
        if row is None or row.value is None:
            return None
        return str(row.value).strip() or None
    except Exception as e:
        logger.warning("[Fix327] %s 조회 실패: %s", key, e)
        return None


def gate_enabled(db) -> bool:
    """기본 OFF. 진입 판정을 바꾸는 큰 변화라 명시적으로 켠다 (헌법 161)."""
    v = _setting(db, SETTING_ENABLED)
    return bool(v) and v.lower() in ("1", "true", "on", "yes")


def _int_setting(db, key: str, default: int, lo: int, hi: int) -> int:
    v = _setting(db, key)
    if v is None:
        return default
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        logger.warning("[Fix327] %s=%r 파싱 실패 → 기본 %d", key, v, default)
        return default
    if n < lo or n > hi:
        logger.warning("[Fix327] %s=%s 범위밖(%d~%d) → 기본 %d", key, n, lo, hi, default)
        return default
    return n


def min_long_score(db) -> int:
    return _int_setting(db, SETTING_MIN_LONG, MIN_LONG_DEFAULT, 0, MAX_SCORE)


def max_short_score(db) -> int:
    return _int_setting(db, SETTING_MAX_SHORT, MAX_SHORT_DEFAULT, 0, MAX_SCORE)


# ══════════════════════════════════════════════════════════════════════
# 지표 — 독립 구현 (chart_analyzer 에는 CCI/OBV 만 있다)
# ══════════════════════════════════════════════════════════════════════

def _ema(v: list[float], n: int) -> list[float]:
    if not v:
        return []
    k = 2.0 / (n + 1)
    out = [v[0]]
    for x in v[1:]:
        out.append(x * k + out[-1] * (1 - k))
    return out


def _macd_hist(closes: list[float]) -> list[float] | None:
    """MACD(12,26,9) hist. 40봉 미만이면 신뢰할 수 없어 None."""
    if len(closes) < 40:
        return None
    fast, slow = _ema(closes, 12), _ema(closes, 26)
    macd = [a - b for a, b in zip(fast, slow)]
    sig = _ema(macd, 9)
    return [a - b for a, b in zip(macd, sig)]


def _rsi(closes: list[float], period: int) -> float | None:
    """Wilder RSI. 마지막 값만 돌려준다."""
    if len(closes) < period + 1:
        return None
    gains = losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    ag, al = gains / period, losses / period
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (period - 1) + max(d, 0.0)) / period
        al = (al * (period - 1) + max(-d, 0.0)) / period
    if al == 0:
        return 100.0
    rs = ag / al
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(highs: list[float], lows: list[float], closes: list[float], n: int = 14) -> float | None:
    if len(closes) < n + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        trs.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))
    if len(trs) < n:
        return None
    return sum(trs[-n:]) / n


# ══════════════════════════════════════════════════════════════════════
# 지지선
# ══════════════════════════════════════════════════════════════════════

def find_swing_low(lows: list[float]) -> tuple[float | None, int | None]:
    """좌우 3봉보다 낮은 피벗 저점 중 **가장 최근** 것.

    최근 4봉은 아직 오른쪽 3봉이 없어 피벗을 확정할 수 없으므로 제외한다.

    Returns:
        (지지선 가격, 그 봉의 인덱스). 없으면 (None, None).
    """
    n = len(lows)
    if n < PIVOT_HALF_WIDTH * 2 + EXCLUDE_RECENT + 1:
        return None, None
    start = max(PIVOT_HALF_WIDTH, n - LOOKBACK_BARS)
    end = n - EXCLUDE_RECENT           # 배타
    for i in range(end - 1, start - 1, -1):
        lo = lows[i]
        left = lows[i - PIVOT_HALF_WIDTH:i]
        right = lows[i + 1:i + 1 + PIVOT_HALF_WIDTH]
        if len(right) < PIVOT_HALF_WIDTH or len(left) < PIVOT_HALF_WIDTH:
            continue
        if all(lo < x for x in left) and all(lo < x for x in right):
            return lo, i
    return None, None


def is_touching(highs: list[float], lows: list[float], closes: list[float],
                support: float) -> tuple[bool, str, dict[str, Any]]:
    """지금 봉이 지지선에 **막 닿았는가**.

    세 조건을 모두 만족해야 한다:
      1. 이번 봉 저가가 지지선 + 허용오차 이내로 내려왔다
      2. **직전 봉 종가는 그 위였다** (이미 한참 아래면 접촉이 아니라 이탈)
      3. 최근 24봉 고점 대비 -1% 이상 내려와 있다 (고점권 잡티 제외)

    허용오차 = max(0.2%, 0.25 x ATR14/close) — 변동성이 큰 종목은 더 넓게.
    """
    d: dict[str, Any] = {}
    if support is None or support <= 0 or len(closes) < 25:
        return False, "데이터 부족", d
    atr = _atr(highs, lows, closes)
    px = closes[-1]
    tol = max(0.002, 0.25 * (atr / px)) if (atr and px) else 0.002
    d.update(support=support, tol_pct=tol * 100, close=px)

    if not (lows[-1] <= support * (1 + tol)):
        return False, "지지선까지 안 내려옴", d
    if not (closes[-2] > support * (1 + tol)):
        return False, "직전 봉이 이미 지지선 아래 (접촉이 아니라 이탈)", d
    hi24 = max(highs[-24:])
    drop = (px / hi24 - 1) * 100 if hi24 else 0.0
    d["drop_from_hi24_pct"] = drop
    if not (drop <= -1.0):
        return False, f"최근 24봉 고점 대비 {drop:+.2f}% (고점권)", d
    return True, "지지선 접촉", d


# ══════════════════════════════════════════════════════════════════════
# 7점 채점
# ══════════════════════════════════════════════════════════════════════

def compute_score(kl_15m: list, kl_1h: list) -> tuple[int | None, dict[str, Any]]:
    """7개 규칙을 채점한다.

    Returns:
        (score 0~7, 상세). 1H 데이터가 없으면 (None, ...) —
        **판정을 내리지 않는다.** 1H 규칙 3개가 점수의 핵심이다.
    """
    d: dict[str, Any] = {}
    if not kl_15m or len(kl_15m) < 100:
        return None, {"reason": "15m 봉 부족"}
    if not kl_1h or len(kl_1h) < 40:
        return None, {"reason": "1h 봉 부족 (1H 규칙 3개가 핵심이라 판정 보류)"}

    c15 = [float(k[4]) for k in kl_15m]
    h15 = [float(k[2]) for k in kl_15m]
    c1h = [float(k[4]) for k in kl_1h]

    rules: dict[str, bool] = {}

    # ── 1H (방향축) ───────────────────────────────────────────────
    mh1 = _macd_hist(c1h)
    rules["h1_macdh_pos"] = bool(mh1 and mh1[-1] > 0)
    rules["h1_above_ema20"] = bool(c1h[-1] > _ema(c1h, 20)[-1])
    r12 = _rsi(c1h, 12)
    rules["h1_rsi12_ge_50"] = bool(r12 is not None and r12 >= 50)

    # ── 15m (타이밍축) ────────────────────────────────────────────
    # 🚨 **역방향 규칙** — 이미 오르고 있으면 점수를 주지 않는다.
    #    d = -0.380. 층별 통제(-0.40/-0.49)와 지정가 가정(-0.298)에서
    #    살아남은 유일한 역방향 지표다.
    mh15 = _macd_hist(c15)
    rules["m15_macdh_not_rising3"] = bool(
        mh15 and len(mh15) > 3 and not (mh15[-1] > mh15[-4])
    )
    r24 = _rsi(c15, 24)
    rules["m15_rsi24_ge_45"] = bool(r24 is not None and r24 >= 45)
    hi96 = max(h15[-96:]) if len(h15) >= 96 else max(h15)
    drop96 = (c15[-1] / hi96 - 1) * 100 if hi96 else 0.0
    rules["m15_drop96_ge_m15"] = bool(drop96 >= -15.0)
    rules["m15_above_ema50"] = bool(c15[-1] > _ema(c15, 50)[-1])

    score = sum(1 for v in rules.values() if v)
    d.update(rules=rules, score=score, drop96_pct=drop96,
             rsi12_1h=r12, rsi24_15m=r24,
             macdh_1h=(mh1[-1] if mh1 else None))
    return score, d


def decide(score: int, side: str, *, min_long: int = MIN_LONG_DEFAULT,
           max_short: int = MAX_SHORT_DEFAULT) -> tuple[bool, str]:
    """이 점수에서 이 방향으로 들어가도 되는가."""
    s = str(side).upper()
    if s == "LONG":
        if score >= min_long:
            tag = "매우 강함" if score >= MAX_SCORE else "강함"
            return True, f"지지선 {score}/7점 ({tag}) — LONG 허용"
        return False, f"지지선 {score}/7점 < {min_long} — LONG 근거 부족"
    if s == "SHORT":
        if score <= max_short:
            tag = "매우 약함" if score == 0 else "약함"
            return True, f"지지선 {score}/7점 ({tag}) — 추가하락 SHORT 허용"
        return False, f"지지선 {score}/7점 > {max_short} — 추가하락 근거 부족"
    return True, f"방향 불명({side}) — 판정 안 함"


# ══════════════════════════════════════════════════════════════════════
# 공용 진입점
# ══════════════════════════════════════════════════════════════════════

def evaluate(db, bc, symbol: str, side: str) -> tuple[bool, str, dict[str, Any]]:
    """지지선 판정 — 진입해도 되는가.

    Returns:
        (통과, 사유, 상세)

    ⚠️ **fail-open**. 데이터를 못 받았다고 매매를 멈추면 안 된다.
       이건 「더 좋은 자리만 고르는」 필터이지 안전장치가 아니다
       (Fix 270 과 같은 성격).
    """
    d: dict[str, Any] = {"symbol": symbol, "side": side}
    if not gate_enabled(db):
        return True, "", d
    try:
        kl15 = bc.get_klines(symbol=symbol, interval="15m", limit=200)
        kl1h = bc.get_klines(symbol=symbol, interval="1h", limit=120)
    except Exception as e:
        logger.warning("[Fix327] %s 시세 조회 실패 → 통과 (fail-open): %s", symbol, e)
        return True, "시세 조회 실패 (fail-open)", d

    try:
        # 🚨 진행 중인 봉을 잘라낸다. 진행 중 봉으로 판정하면
        #    macdh_not_rising3 이 봉 중간에 계속 뒤집힌다.
        kl15c = kl15[:-1] if len(kl15) > 100 else kl15
        kl1hc = kl1h[:-1] if len(kl1h) > 40 else kl1h

        lows = [float(k[3]) for k in kl15c]
        highs = [float(k[2]) for k in kl15c]
        closes = [float(k[4]) for k in kl15c]

        sup, idx = find_swing_low(lows)
        d.update(support=sup, support_idx=idx)
        if sup is None:
            return True, "지지선(피벗 저점) 없음 — 판정 안 함 (fail-open)", d

        touching, why_t, dt = is_touching(highs, lows, closes, sup)
        d.update(touch=touching, touch_detail=dt)

        score, ds = compute_score(kl15c, kl1hc)
        d.update(score_detail=ds)
        if score is None:
            return True, f"채점 불가 ({ds.get('reason')}) — 판정 안 함 (fail-open)", d

        ok, why = decide(score, side,
                         min_long=min_long_score(db),
                         max_short=max_short_score(db))
        # 접촉 상태가 아니면 「기록만」 하고 막지 않는다.
        # 판정식은 **지지선 접촉 시점**의 264건으로 만들어졌다.
        # 다른 자리에 적용하면 표본 밖이다.
        if not touching:
            return True, f"지지선 접촉 아님 ({why_t}) — 판정 미적용 [{score}/7점]", d
        return ok, why, d
    except Exception as e:
        logger.warning("[Fix327] %s 판정 실패 → 통과 (fail-open): %s", symbol, e)
        d["error"] = str(e)[:200]
        return True, f"판정 실패 (fail-open): {e}", d
