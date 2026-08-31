"""📉 볼밴 지지 붕괴 — 「급락은 확실한 숏」을 숫자로 (Fix 254).

## 사장님 사상 ③ verbatim

  "당일 급등하는 심볼은 상승후 조정을 차는거고 **급락한것은 이전급등에 대한 급락**이라
   확실한 숏으로 급반등하는 위험을 줄이고 꾸준하게 수익을 만들수있어"
  "볼밴 중간하락 이후 와 **볼밴 하단 이탈시 지속적인 하락**에 포지션 진입.
   **볼밴 지지와 상승 / 볼밴 지지선 붕괴와 지속하락**을 찾아서 분할 포지션 진입이다"

**「볼밴 지지선 붕괴」가 이 파일이다.** 사상에 명시돼 있는데 코드에 없었다.

## 왜 필요한가 — 시스템이 붕괴를 LONG 으로 사고 있었다

`unified_15m_entry._detect_15m_surge` 는 방향을 **1시간 변동률 부호만으로** 정한다:

    side = "SHORT" if c1h > 0 else "LONG"

BTRUSDT 가 -44% 붕괴하면 이 코드는 「급락」으로 분류해 **LONG 을 산다.**
사상 ③ 은 정반대로 「확실한 숏」이라고 말한다.

## BTRUSDT #1488 실측 (단일 최대 손실 -6,552.45)

    08/26~27   0.0138 -> 0.22400   (+1,523%, 16배)     <- 선행 급등
    08/28~31   0.14~0.17 횡보       4~5일              <- 지지 구간
    08/31 15시 0.14 붕괴 -> 0.0823  (-44%)             <- 지지선 붕괴

정점(08/27)과 붕괴(08/31) 사이가 4~5일이다.
정점 직후 SHORT 는 그 4일을 -20~30% 물린 채 버텨야 했다 —
#1488 이 최대 +23.4% -> 최저 -61.6% 를 오간 구간이 정확히 그것이다.
**기다렸어야 할 자리가 「붕괴」다.**

## 판정 (전부 충족해야 한다)

    ① 선행 급등    창 안 고점이 저점 대비 +50% 이상   (사상 ③ "이전급등에 대한 급락")
    ② 지지 이탈    종가가 볼밴 중단선 아래 (bb_pos < 0.45)
    ③ 지지선 붕괴  종가가 직전 8봉의 최저가 아래 (= 지지가 깨졌다)
    ④ 거래량       현재 봉 거래량 >= 최근 평균 x 1.5  (붕괴에 물량이 실렸는가)
    ⑤ OBV 하락     obv_dir < 0                        (사상 ④)

⑤ 가 핵심이다 — 사장님 사상 ④:
  "볼밴 하단까지 갔다가도 **obv가 강하면 이것도 다시 상승으로 전환**된다"
OBV 가 안 꺾인 이탈은 **가짜 이탈**이므로 SHORT 자리가 아니다.

⚠️ 판정만 한다. 주문도 DB 쓰기도 하지 않는다.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Sequence

__all__ = ["BreakdownVerdict", "evaluate_support_breakdown", "THRESHOLDS"]

THRESHOLDS: dict[str, float] = {
    # ① 선행 급등 — 사상 ③ 「이전 급등에 대한 급락」. BTR 은 +1,523% 였다.
    "prior_rally_min_pct": 50.0,
    # ② 지지 이탈 — 중단선(0.5) 아래로 결정적으로. BTR 붕괴 시점 1H bb_pos = 0.434.
    "bb_pos_break_max": 0.45,
    # ③ 지지선 붕괴 — 직전 N봉의 **최저가**를 깼는가.
    #   🚨 처음엔 「중단선 위였다가 깨졌다」로 짰는데 **틀렸다**:
    #      16배 급등 뒤에는 20봉 볼밴이 너무 넓어져 횡보 구간이 **계속 중단선 아래**에
    #      머문다. 그래서 그 조건은 BTR 같은 폭등 후 붕괴에서 영원히 거짓이 된다.
    #      「지지선 붕괴」의 문자 그대로 — 직전 구간 저점 이탈로 판정한다.
    "support_lookback": 8.0,
    # ④ 거래량 — 붕괴에 물량이 실렸는가
    "vol_spike_min": 1.5,
    "vol_avg_bars": 20.0,
    # ⑤ OBV — 사상 ④. 안 꺾였으면 가짜 이탈이다.
    "obv_max": 0.0,
    # 볼밴 계산
    "bb_period": 20.0,
    "bb_std": 2.0,
    "window": 60.0,
}


@dataclass
class BreakdownVerdict:
    ok: bool = False
    passed: int = 0
    total: int = 0
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def reason(self) -> str:
        miss = [k for k, v in (self.detail.get("checks") or {}).items() if v is not True]
        if self.ok:
            return f"지지 붕괴 확인 ({self.passed}/{self.total})"
        return f"{self.passed}/{self.total} — 미충족: {', '.join(miss) or '데이터 부족'}"


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _bb_pos_at(closes: list[float], idx: int, period: int, k: float) -> float | None:
    """idx 시점의 볼밴 내 위치 (0=하단 / 0.5=중단 / 1=상단)."""
    if idx + 1 < period:
        return None
    w = closes[idx + 1 - period: idx + 1]
    mid = sum(w) / period
    sd = statistics.pstdev(w)
    if sd <= 0:
        return None
    up, lo = mid + k * sd, mid - k * sd
    return (closes[idx] - lo) / (up - lo)


def evaluate_support_breakdown(
    *,
    closes: Sequence[Any] | None,
    volumes: Sequence[Any] | None = None,
    obv_dir: Any = None,
    thresholds: dict[str, float] | None = None,
) -> BreakdownVerdict:
    """「급등 후 지지선 붕괴」인가 = SHORT 자리인가.

    Args:
        closes: 종가 (1H 또는 4H 권장 — 사장님 사상 ⑥ 「확정된 흐름」)
        volumes: 같은 봉의 거래량
        obv_dir: OBV 방향 -1~+1 (obv_metrics.obv_direction_ratio)

    ⚠️ 결측은 **통과로 세지 않는다** (fail-closed).
       이 판정은 **매매 방향을 뒤집는다** — 모르는데 뒤집으면 안 된다.
    """
    T = {**THRESHOLDS, **(thresholds or {})}
    v = BreakdownVerdict()
    d = v.detail
    checks: dict[str, bool | None] = {}

    vals = []
    if closes:
        for c in closes[-int(T["window"]):]:
            fv = _f(c)
            if fv is not None and fv > 0:
                vals.append(fv)
    d["bars"] = len(vals)
    period = int(T["bb_period"])
    if len(vals) < period + int(T["support_lookback"]) + 1:
        d["checks"] = {"데이터": None}
        v.total = 1
        return v

    # ── ① 선행 급등 (사상 ③) ──
    peak_i = max(range(len(vals)), key=lambda i: vals[i])
    low_before = min(vals[: peak_i + 1]) if peak_i > 0 else vals[0]
    rally = (vals[peak_i] - low_before) / low_before * 100.0 if low_before > 0 else 0.0
    d["prior_rally_pct"] = rally
    d["peak"] = vals[peak_i]
    checks["선행 급등"] = rally >= T["prior_rally_min_pct"]

    # ── ② 지지 이탈 ──
    now_pos = _bb_pos_at(vals, len(vals) - 1, period, T["bb_std"])
    d["bb_pos"] = now_pos
    checks["지지 이탈"] = None if now_pos is None else now_pos < T["bb_pos_break_max"]

    # ── ③ 지지선 붕괴 (직전 구간 저점을 깼는가) ──
    look = int(T["support_lookback"])
    prior = vals[-1 - look: -1]
    support = min(prior) if prior else None
    d["support"] = support
    d["now"] = vals[-1]
    checks["지지선 붕괴"] = None if support is None else vals[-1] < support

    # ── ④ 거래량 급증 ──
    vs = []
    if volumes:
        for x in volumes[-int(T["vol_avg_bars"]) - 1:]:
            fv = _f(x)
            if fv is not None and fv >= 0:
                vs.append(fv)
    if len(vs) >= 5:
        avg = sum(vs[:-1]) / max(1, len(vs) - 1)
        ratio = vs[-1] / avg if avg > 0 else None
        d["vol_ratio"] = ratio
        checks["거래량 급증"] = None if ratio is None else ratio >= T["vol_spike_min"]
    else:
        d["vol_ratio"] = None
        checks["거래량 급증"] = None

    # ── ⑤ OBV 하락 (사상 ④ — 안 꺾였으면 가짜 이탈) ──
    od = _f(obv_dir)
    d["obv_dir"] = od
    checks["OBV 하락"] = None if od is None else od < T["obv_max"]

    d["checks"] = checks
    v.total = len(checks)
    v.passed = sum(1 for r in checks.values() if r is True)
    # 🚨 전부 충족해야 한다 — 매매 **방향을 뒤집는** 판정이라 다수결로 정할 일이 아니다
    #    (Fix 250 에서 「N중 M」이 정의 조건을 덮어쓴 사고를 겪었다).
    v.ok = all(r is True for r in checks.values())
    return v
