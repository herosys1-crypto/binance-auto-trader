"""📊 OBV 방향 지표 — **단일 출처** (Fix 228).

사장님 원칙 (2026-08-30):
  "무엇보다 obv가 하락하지 않으면 결국은 obv 방향으로 간다는거야"

OBV 를 방향의 최종 판단으로 쓰려면 **모든 워커가 같은 숫자를 봐야 한다**.
그런데 실측 감사 결과 `obv_slope_pct` 라는 **한 컬럼에 최소 3가지 단위**가
섞여 들어가고 있었다:

    realtime_reentry_worker:299        obv[-1]-obv[-4]              → 원 계약수량
    bb_middle_scan:96                  (o[-1]-o[-10])/|o[-10]|      → 분모 0 이면 무계
    strategy_suggestion_generator:239  (o1-o0)/|o0|*100             → 누적 레벨이 분모

세 산식 모두 실행해 **2,249,160 / 2,249,159.9 / 3,600,000** 이 나오는 것을 확인했다.
진입 스냅샷 실측 최대값 2,249,160 과 자릿수가 같다.

## 왜 이 산식인가

    obv_direction_ratio = (OBV[-1] - OBV[-1-lookback]) / (창 안 |거래량| 합)

- **분모가 0 이 될 수 없다** (거래량 합은 항상 양수, 0 이면 None 반환).
- **-1 ~ +1 로 묶인다.** 창 안 모든 거래가 한 방향이면 ±1, 상쇄되면 0.
  → 「OBV 가 하락하지 않았다」가 `>= 0` 이라는 한 줄로 표현된다.
- **심볼 스케일에 무관하다.** 0.0001 짜리 잡코인과 BTC 를 같은 임계로 비교할 수 있다.
- 누적 OBV 의 **절대 레벨에 의존하지 않는다.** 기존 산식들의 공통 결함이 그것이었다
  (compute_obv 는 창의 첫 봉을 0 으로 놓으므로 절대 레벨은 fetch 시작점에 좌우되는 임의값).

⚠️ 이 함수는 **방향의 세기**만 잰다. 「세력 매집 극단」 판정은 obv_gate 가 따로 한다.
"""
from __future__ import annotations

from typing import Any, Sequence

__all__ = ["obv_direction_ratio", "DEFAULT_LOOKBACK"]

DEFAULT_LOOKBACK: int = 20


def _f(x: Any) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def obv_direction_ratio(
    obv: Sequence[Any] | None,
    volumes: Sequence[Any] | None,
    lookback: int = DEFAULT_LOOKBACK,
) -> float | None:
    """OBV 방향을 **-1 ~ +1** 로. 데이터가 모자라면 None.

    Args:
        obv: 누적 OBV 리스트 (ChartAnalyzer.compute_obv 결과)
        volumes: 같은 봉의 거래량 리스트 (analyze_timeframe 의 "volumes")
        lookback: 몇 봉을 볼 것인가

    Returns:
        (OBV 변화량) / (창 안 거래량 합).
        +1 에 가까울수록 그 구간 거래가 전부 매수 쪽, -1 이면 전부 매도 쪽.
        0 부근이면 매수·매도가 상쇄된 것 = 방향 없음.
        None = 봉 부족 / 거래량 0 / 값 파싱 실패.
    """
    if not obv or not volumes or lookback < 1:
        return None
    need = lookback + 1
    if len(obv) < need or len(volumes) < lookback:
        return None

    last, first = _f(obv[-1]), _f(obv[-need])
    if last is None or first is None:
        return None

    total = 0.0
    for v in volumes[-lookback:]:
        fv = _f(v)
        if fv is not None:
            total += abs(fv)
    if total <= 0:
        return None

    ratio = (last - first) / total
    # 수치 오차로 아주 살짝 넘는 경우가 있어 안전하게 묶는다.
    return max(-1.0, min(1.0, ratio))
