"""📐 되돌림 비율 — LONG 이 「원점 회귀 종목」에 들어가지 않게 하는 판정 (Fix 236).

사장님 사상 ⑤ (2026-08-30 verbatim):
  "큰상승후 큰하락해서 **원점을 간 심볼은 다시 상승하는 심볼을 찾기는 힘들어**.
   그래서 롱은 **큰상승을 시작한 심볼**을 모니터링해서 포지션에 들어가는게 매우 유리해"

이 문장을 숫자로 옮긴 것이 이 파일이다. 사장님 요구 —
  "감이 아니라 **숫자로 된 판정식**"

## 판정식

    되돌림 = (고점 - 현재가) / (고점 - 상승 시작가)

    0.00 ~ 0.30   고점 부근      = 아직 조정이 얕다
    0.30 ~ 0.60   추세 중 조정   = ✅ LONG 자리 (사장님 「급등후 큰조정」)
    0.60 ~ 0.70   깊은 조정      = 회색지대 (막지는 않는다)
    0.70 이상     원점 회귀      = 🚫 LONG 금지
    1.00 이상     원점 아래      = 상승 시작가보다도 낮다 = 최악

「상승 시작가」는 **고점 이전의 최저 종가**다. 즉 이번 상승 파동의 출발점.

## 왜 종가인가

`ChartAnalyzer.analyze_timeframe` 은 `closes` 만 돌려준다(고가·저가 없음).
꼬리(wick)를 쓰면 순간 스파이크 하나가 분모·분자를 다 흔들어 되돌림이
과대·과소 계산된다. 종가 기준이 더 안정적이고, 이 판정의 목적
(「이번 상승이 얼마나 반납됐나」)에도 맞다.

## 왜 4시간봉인가

사장님 사상 ⑥ — **"4시간을 확정된 흐름으로 보고"**.
되돌림은 「국면」 판정이므로 15분봉이 아니라 4H 로 잰다.
"""
from __future__ import annotations

from typing import Any, Sequence

__all__ = [
    "retracement_ratio",
    "is_round_trip",
    "is_pullback_zone",
    "RETRACE_BLOCK_MIN",
    "PULLBACK_MIN",
    "PULLBACK_MAX",
    "DEFAULT_LOOKBACK_4H",
]

# 사장님 사상 ⑤ 의 숫자 (2026-08-30 verbatim: "70~80% 이상 금지 / 30~60% 진입")
RETRACE_BLOCK_MIN: float = 0.70   # 이 이상이면 원점 회귀 = LONG 금지
PULLBACK_MIN: float = 0.30        # 「추세 중 조정」 하한
PULLBACK_MAX: float = 0.60        # 「추세 중 조정」 상한

# 4H 60봉 = 10일. 사장님 "몇일 이상 상승" 을 담을 수 있는 최소 창.
DEFAULT_LOOKBACK_4H: int = 60

# 상승 파동으로 인정할 최소 크기. 이보다 작으면 「큰상승」이 아니라 잡음이고,
# 분모가 작아 되돌림 비율이 의미 없이 튄다.
MIN_RALLY_PCT: float = 5.0


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None   # NaN 제외


def retracement_ratio(
    closes: Sequence[Any] | None,
    lookback: int = DEFAULT_LOOKBACK_4H,
) -> tuple[float | None, dict[str, Any]]:
    """되돌림 비율과 근거를 함께 돌려준다.

    Args:
        closes: 종가 리스트 (오래된 것 -> 최신). 4H 권장.
        lookback: 몇 봉을 볼 것인가.

    Returns:
        (ratio, detail)
        ratio  = (고점 - 현재가) / (고점 - 상승 시작가). 판정 불가면 None.
                 1.0 을 넘을 수 있다 = 상승 시작가보다도 아래로 내려갔다는 뜻.
        detail = {"reason", "peak", "start", "now", "rally_pct", "bars"}
                 ratio 가 None 이어도 reason 으로 왜 못 쟀는지 알 수 있다.

    ⚠️ **ratio 가 None 이면 「안전」이 아니라 「모름」이다.**
       호출자는 fail-open 할지 fail-closed 할지 스스로 정해야 한다.
       (is_round_trip 은 모름을 「막지 않음」으로 처리한다 — 데이터 부족만으로
        기회를 버리지 않기 위해서다. 대신 로그에 남는다.)
    """
    detail: dict[str, Any] = {"reason": "", "peak": None, "start": None,
                              "now": None, "rally_pct": None, "bars": 0}
    if not closes or lookback < 3:
        detail["reason"] = "no_data"
        return None, detail

    vals = [v for v in (_f(c) for c in closes[-lookback:]) if v is not None and v > 0]
    detail["bars"] = len(vals)
    if len(vals) < 3:
        detail["reason"] = "bars<3"
        return None, detail

    peak_idx = max(range(len(vals)), key=lambda i: vals[i])
    if peak_idx == 0:
        # 고점이 창의 맨 처음 = 이번 창 안에 상승 파동이 없다 (계속 내리막)
        detail["reason"] = "peak_at_window_start"
        return None, detail

    start_idx = min(range(peak_idx + 1), key=lambda i: vals[i])
    peak, start, now = vals[peak_idx], vals[start_idx], vals[-1]
    detail.update(peak=peak, start=start, now=now)

    rally = peak - start
    if rally <= 0:
        detail["reason"] = "no_rally"
        return None, detail

    rally_pct = rally / start * 100.0
    detail["rally_pct"] = rally_pct
    if rally_pct < MIN_RALLY_PCT:
        # 상승폭이 너무 작으면 분모가 작아 비율이 의미 없이 튄다.
        detail["reason"] = f"rally_too_small({rally_pct:.1f}%<{MIN_RALLY_PCT}%)"
        return None, detail

    detail["reason"] = "ok"
    return (peak - now) / rally, detail


def is_round_trip(ratio: float | None) -> bool:
    """🚫 원점 회귀인가 (= LONG 금지).

    ratio 가 None(판정 불가)이면 **막지 않는다** — 데이터 부족만으로 기회를
    버리지 않기 위해서다. 대신 호출자가 그 사실을 로그에 남겨야 한다.
    """
    return ratio is not None and ratio >= RETRACE_BLOCK_MIN


def is_pullback_zone(ratio: float | None) -> bool:
    """✅ 사장님이 말한 「급등후 큰조정」 구간인가 (30~60%)."""
    return ratio is not None and PULLBACK_MIN <= ratio <= PULLBACK_MAX
