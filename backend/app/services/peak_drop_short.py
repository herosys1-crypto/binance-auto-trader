"""⏱️ 「너무 빨리 들어간 SHORT」를 막는다 — 정점 확인 게이트 (Fix 248).

## 사장님 verbatim (2026-08-31, SKRUSDT 차트를 보여주시며)

  "이렇게 **큰하락에 포지션진입을 해야 하는데 너무 빨리 진입하여 큰손실**을 본거야.
   그래서 시스템이 이런 차트로직을 학습해서 투자를 할려고 하는거야"

즉 방향(SHORT)은 맞았고 **타이밍만 일렀다**. 이 파일은 그 「이름」을 숫자로 옮긴 것이다.

## 실패 사례 — SKRUSDT #1873 (실측)

    진입 평단        0.019818   <- 아직 상승 중일 때 SHORT
    이후 정점        0.034856   (+75.9%)
    강제 청산        0.023333   ROI -35.48% / -724.80 USDT
    그 뒤 실제 하락  0.034856 -> 0.023  (-33.8%)   <- 방향은 맞았다

## 사장님이 보여주신 「진짜 자리」의 숫자

                        1시간봉                       15분봉
    볼밴 위치      0.471 (중단선 아래로 이탈)      0.066 (하단 부근)
    MACD 히스트    -0.000633 (음수 전환 직후)      -0.000554 (확대 중)
    RSI(6)         36.7 (여유)                     25.1 (과매도)
    OBV            고점에서 꺾임                    하락
    고점 대비      -33.8%

## 실측 데이터가 같은 말을 한다 (독립 확인)

    진 SHORT    볼밴 4H 1.005 (상단 밖)   OBV 0.530   3일 +98%
    이긴 SHORT  볼밴 4H 0.923             OBV 0.331   3일 +53%

= 지는 SHORT 는 **아직 밴드 위에 있을 때** 들어간 것이다.

## 설계 — 「필수 조건」이 아니라 「차단 조건」

정점 확인을 **요구**하면 진입이 거의 안 난다(볼밴 3차 0건 사고와 같은 함정).
그래서 **너무 이른 자리만 막는다**:

    🚫 종가가 볼밴 **상단 밖**       -> 아직 급등 중
    🚫 MACD 히스토그램이 **양수**    -> 아직 상승 모멘텀
    🚫 고점 대비 하락이 **미미**      -> 정점이 아직 확인 안 됨
    🚫 볼밴 **하단 부근 + OBV 상승**  -> 되돌아 오른다 (사장님 사상 ④)

앞의 셋은 「너무 빨리」, 마지막 하나는 「너무 늦게」를 막는다.
둘 사이가 **진입 창**이다.


⚠️ 판정만 한다. 주문도 DB 쓰기도 하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

__all__ = ["PeakDropVerdict", "evaluate_peak_drop_short", "THRESHOLDS"]

THRESHOLDS: dict[str, float] = {
    # 볼밴 상단 밖 = 아직 급등 중. 실측 진 SHORT 중앙값이 **1.005** 였다.
    "bb_pos_max": 1.00,
    # 🎯 반대쪽 실패 — 볼밴 **하단 부근**에서 OBV 가 살아나면 되돌아 오른다.
    #   사장님 사상 ④ verbatim:
    #     "볼밴 하단까지 갔다가도 **obv가 강하면 이것도 다시 상승으로 전환**된다고 봐야해"
    #   사장님이 보여주신 SKR 15분봉 실측 (2026-08-31 18시대, 3장 연속):
    #       가격   0.023120 -> 0.023383 -> 0.023449
    #       RSI(6)   24.5   ->   28.5   ->   29.4     과매도에서 회복
    #       OBV     2.201B  ->  2.43B   ->  2.451B    상승
    #       볼밴 위치  0.120 (하단 부근)
    #   여기서 SHORT 를 넣으면 **반등에 맞는다**. #1873 과 정반대 방향의 실패다.
    "bb_pos_min": 0.20,
    "obv_rebound_min": 0.0,     # 하단 부근에서 OBV 가 이 위면 반등 위험
    # 고점 대비 최소 하락률. 정점이 「확인」되려면 되돌아 나와야 한다.
    # 3% = 노이즈는 아니되 늦지 않은 선. SKR 실제 자리는 -33.8% 였다.
    "min_drop_from_peak_pct": 3.0,
    # 고점 탐색 창 (봉 수). 1H 60봉 = 2.5일 / 15m 60봉 = 15시간.
    "peak_lookback": 60.0,
}


@dataclass
class PeakDropVerdict:
    allow: bool = True
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def evaluate_peak_drop_short(
    *,
    closes: Sequence[Any] | None,
    bb_pos: Any = None,
    macd_hist: Any = None,
    obv_dir: Any = None,
    thresholds: dict[str, float] | None = None,
) -> PeakDropVerdict:
    """SHORT 를 지금 넣어도 되는가 — **양쪽 끝**을 막고 그 사이만 남긴다.

    Args:
        closes: 종가 리스트 (1H 또는 4H 권장 — 사장님 사상 ⑥ 「확정된 흐름」)
        bb_pos: 볼밴 내 위치 (0=하단 / 0.5=중단 / 1=상단, 1 초과 = 상단 밖)
        macd_hist: MACD 히스토그램 마지막 값
        obv_dir: OBV 방향 -1~+1 (obv_metrics.obv_direction_ratio).
            볼밴 하단 부근에서 이 값이 양수면 「되돌아 오른다」로 본다 (사장님 ④).

    Returns:
        PeakDropVerdict. allow=False 면 「아직 이르다」.

    ⚠️ 결측은 **막지 않는다** (fail-open). 이 게이트는 차단 전용이라
       모르는 것으로 기회를 없애지 않는다. 대신 detail 에 남는다.
    """
    T = {**THRESHOLDS, **(thresholds or {})}
    v = PeakDropVerdict()
    d = v.detail

    bp = _f(bb_pos)
    d["bb_pos"] = bp
    if bp is not None and bp > T["bb_pos_max"]:
        v.allow = False
        v.reason = (
            f"아직 급등 중 — 볼밴 위치 {bp:.3f} > {T['bb_pos_max']:.2f} (상단 밖). "
            "실측: 진 SHORT 중앙값 1.005"
        )
        return v

    # 🎯 사장님 사상 ④ — 하단 부근 + OBV 살아남 = 되돌아 오른다 = SHORT 금지
    od = _f(obv_dir)
    d["obv_dir"] = od
    if (bp is not None and bp < T["bb_pos_min"]
            and od is not None and od > T["obv_rebound_min"]):
        v.allow = False
        v.reason = (
            f"반등 위험 — 볼밴 {bp:.3f} < {T['bb_pos_min']:.2f} (하단 부근) 인데 "
            f"OBV {od:+.3f} 상승. 사장님 ④: 「하단까지 갔다가도 obv가 강하면 "
            "다시 상승으로 전환」"
        )
        return v

    mh = _f(macd_hist)
    d["macd_hist"] = mh
    if mh is not None and mh > 0:
        v.allow = False
        v.reason = f"아직 상승 모멘텀 — MACD 히스토그램 {mh:+.6f} > 0 (음수 전환 전)"
        return v

    lookback = int(T["peak_lookback"])
    vals = []
    if closes:
        for c in closes[-lookback:]:
            fv = _f(c)
            if fv is not None and fv > 0:
                vals.append(fv)
    d["bars"] = len(vals)
    if len(vals) >= 5:
        peak = max(vals)
        now = vals[-1]
        drop = (peak - now) / peak * 100.0 if peak > 0 else 0.0
        d["peak"] = peak
        d["now"] = now
        d["drop_from_peak_pct"] = drop
        if drop < T["min_drop_from_peak_pct"]:
            v.allow = False
            v.reason = (
                f"정점 미확인 — 고점 대비 {drop:.1f}% 하락 "
                f"< {T['min_drop_from_peak_pct']:.1f}% (아직 고점 부근)"
            )
            return v
    else:
        d["peak_why"] = "봉 부족"

    v.reason = "정점 확인 후 하락 진행 = SHORT 허용"
    return v
