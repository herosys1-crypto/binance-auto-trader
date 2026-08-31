"""🔋 OBV 회복률 — 「세력이 다시 들어왔는가」 (Fix 259).

## 사장님 verbatim (2026-09-01, AIOUSDT 차트)

  "급등후 급락했을때 obv 같이 급락하면 다시 지지반등 이상을 하려면
   **obv가 강력하게 상승해야해**. 이건 **작은 반등후 하락**하는거야.
   **세력이 모두 떠난후 다시 상승하려면 세력이 다시 들어와야** 하는데
   이차트는 그냥 **소소한 반등**이야"

「지금 OBV 가 오르는가」가 아니라 **「떨어진 만큼 얼마나 돌아왔는가」**다.
소소한 반등은 다시 떨어진다.

## 판정식

    OBV 고점  ->  그 뒤의 OBV 저점  ->  현재
    회복률 = (현재 - 저점) / (고점 - 저점)

    1.0 = 떨어진 만큼 전부 회복 (세력이 완전히 돌아옴)
    0.0 = 저점 그대로 (세력이 안 돌아옴)

## 실측 (진입 시점 캔들 복원, 2026-09-01)

    전략              결과        1H 회복률    4H 회복률
    #1890 SNXXUSDT   **+22.71**   **0.637**     0.187
    #1909 AIOUSDT     실패          0.060       0.266
    #1884 XPLUSDT     실패          0.106       0.069

🚨 **1시간봉이 판별자**다 — 4H 는 오히려 뒤집혀 있다(승 0.187 / 패 0.266).
   승자 0.637 vs 패자 0.060/0.106 = 사장님 말씀 그대로
   「세력이 다시 들어옴」 vs 「소소한 반등」.

⚠️ 표본 3건이다. 승자가 더 쌓이면 임계를 다시 잡을 것.

## 적용 범위

**OBV 가 실제로 떨어진 적이 있을 때만** 의미가 있다 (사장님: "obv 같이 급락하면").
하락 구간이 없으면 None 을 돌려주고, 호출자는 막지 않는다.
"""
from __future__ import annotations

from typing import Any, Sequence

__all__ = ["obv_recovery_ratio", "RECOVERY_MIN", "MIN_DROP_RATIO"]

# 실측: 승자 0.637 / 패자 0.060·0.106.
# 패자보다 넉넉히 위, 승자보다 넉넉히 아래.
RECOVERY_MIN: float = 0.30

# 「OBV 가 급락했다」로 볼 최소 낙폭 — 창 안 OBV 변동폭 대비.
# 이보다 작으면 애초에 「세력이 떠난」 상황이 아니라 판정 대상이 아니다.
MIN_DROP_RATIO: float = 0.20


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def obv_recovery_ratio(
    obv: Sequence[Any] | None,
    lookback: int = 60,
) -> tuple[float | None, dict[str, Any]]:
    """OBV 가 떨어진 만큼 얼마나 돌아왔는가.

    Args:
        obv: 누적 OBV (ChartAnalyzer.compute_obv). **1시간봉 권장** — 실측상 판별자.
        lookback: 몇 봉을 볼 것인가.

    Returns:
        (ratio, detail)
        ratio = (현재 - 저점) / (고점 - 저점). 하락 구간이 없으면 **None**.
                None 은 「막지 마라」다 — 사장님 조건이 "obv 같이 급락하면" 이므로
                급락하지 않았으면 이 규칙의 대상이 아니다.
    """
    d: dict[str, Any] = {"reason": ""}
    vals = []
    if obv:
        for x in obv[-lookback:]:
            fv = _f(x)
            if fv is not None:
                vals.append(fv)
    d["bars"] = len(vals)
    if len(vals) < 25:
        d["reason"] = "봉 부족"
        return None, d

    hi = max(range(len(vals)), key=lambda i: vals[i])
    if hi >= len(vals) - 2:
        # 고점이 바로 지금 = 떨어진 적이 없다 = 대상 아님
        d["reason"] = "고점이 현재 부근 (하락 구간 없음)"
        return None, d

    lo = min(range(hi, len(vals)), key=lambda i: vals[i])
    drop = vals[hi] - vals[lo]
    if drop <= 0:
        d["reason"] = "하락 구간 없음"
        return None, d

    span = max(vals) - min(vals)
    if span > 0 and (drop / span) < MIN_DROP_RATIO:
        # 낙폭이 창 전체 변동의 일부에 불과 = 「세력이 떠난」 수준이 아니다
        d["reason"] = f"낙폭 미미 ({drop / span:.2f} < {MIN_DROP_RATIO})"
        return None, d

    d.update(peak=vals[hi], trough=vals[lo], now=vals[-1], drop=drop, reason="ok")
    return (vals[-1] - vals[lo]) / drop, d
