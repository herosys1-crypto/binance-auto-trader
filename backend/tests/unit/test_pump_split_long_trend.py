"""🚨 Fix 212 — 「긴 추세(중단선)」 모드가 진입 **불가능**했던 자기모순.

사장님 확정 설계 (2026-08-29):
  "볼밴 중단은 지속 상승일때 같은 전략으로 하고 지속 하락 할때도 볼밴 중단으로 활용해서"

그런데 코드는 두 조건이 **동시에 성립할 수 없었다**:
  _is_long_trend  — LONG 은 **현재 봉 포함** 6봉이 전부 `종가 > 중단선` 이어야 참
  _entry_plan     — 참이면 base=중단선, 진입은 `종가 <= 중단선 × 0.97`

같은 봉의 종가가 중단선보다 위이면서 동시에 3% 아래일 수는 없다.
= 긴 추세 모드는 **한 번도 작동한 적이 없다**. 실측 2026-08-29: 후보 9~12건이
  매 사이클 전부 `no_break`, 3시간 연속 진입 0건.

fix: 추세는 **직전 6봉**으로 보고, 현재 봉의 눌림목에서 산다.
"""
from __future__ import annotations

from decimal import Decimal

from app.workers.pump_split_entry_worker import (
    LONG_TREND_BARS,
    SPLIT_STEP_PCT,
    _entry_plan,
    _is_long_trend,
)


def _uptrend_then_dip(dip: float, n: int = 60):
    """마지막 봉만 눌린 상승 추세 15m 시리즈 + 그 시리즈로 계산한 실제 중단선.

    bb_mid_last 를 임의값으로 주면 시험이 거짓말을 한다 —
    분석기의 중단선은 **마지막 20봉 종가의 평균**이므로 그대로 계산해서 넣는다.
    """
    closes = [100.0 + 0.5 * k for k in range(n - 1)] + [dip]
    mid = sum(closes[-20:]) / 20.0
    return {
        "closes": closes,
        "bb_mid_last": mid,
        "bb_up_last": mid * 1.05,
        "bb_lo_last": mid * 0.95,
    }, mid


def test_uptrend_pullback_is_now_enterable():
    """상승 추세 중 중단선 -3% 눌림 = 사장님이 사겠다고 한 바로 그 자리."""
    a15, mid = _uptrend_then_dip(118.0)
    assert 118.0 <= mid * 0.97, "시험 조건 자체가 -3% 를 만족하지 않는다"

    long_trend, why = _is_long_trend(a15, "LONG")
    assert long_trend, f"직전 6봉이 전부 중단선 위인데 추세로 안 본다: {why}"

    base, why2 = _entry_plan(a15, "LONG", long_trend, SPLIT_STEP_PCT)
    assert base is not None, f"긴 추세 모드인데 진입 불가: {why2}"
    assert base == Decimal(str(mid)), "긴 추세면 기준선은 중단선이어야 한다"


def test_old_behaviour_was_a_contradiction():
    """음성 대조군 (헌법 170) — 옛 판정(현재 봉 포함)이 실제로 모순이었는가.

    같은 데이터를 옛 방식으로 판정하면 **반드시 거짓**이어야 한다.
    거짓이 아니라면 이 파일이 고친 게 없다는 뜻이다.
    """
    a15, mid = _uptrend_then_dip(118.0)
    closes = a15["closes"]
    n = len(closes)
    # 옛 코드의 i=1 (= 현재 봉) 판정을 그대로 재현
    mb = sum(closes[n - 20:n]) / 20.0
    c = closes[n - 1]
    assert c <= mb, (
        "현재 봉이 중단선 위다 = 옛 코드도 통과했을 것 = 대조군 무효. "
        f"c={c} mb={mb}"
    )
    assert abs(mb - mid) < 1e-9, "중단선 정의가 분석기와 어긋났다"


def test_short_side_is_symmetric():
    """SHORT = 지속 하락 중 중단선 +3% 되돌림 (사장님 「지속 하락 할때도 중단으로」)."""
    n = 60
    closes = [200.0 - 0.5 * k for k in range(n - 1)]
    mid_wo = 0.0
    bump = 0.0
    # 마지막 봉을 위로 튕겨 중단선 +3% 이상으로 만든다
    for cand in (185.0, 190.0, 195.0, 200.0, 205.0):
        m = (sum(closes[-19:]) + cand) / 20.0
        if cand >= m * 1.03:
            bump = cand
            mid_wo = m
            break
    assert bump, "시험 데이터를 만들지 못했다"
    a15 = {
        "closes": closes + [bump],
        "bb_mid_last": mid_wo,
        "bb_up_last": mid_wo * 1.05,
        "bb_lo_last": mid_wo * 0.95,
    }
    long_trend, why = _is_long_trend(a15, "SHORT")
    assert long_trend, f"직전 {LONG_TREND_BARS}봉이 전부 중단선 아래인데 추세로 안 본다: {why}"
    base, why2 = _entry_plan(a15, "SHORT", long_trend, SPLIT_STEP_PCT)
    assert base is not None, f"긴 하락 추세인데 진입 불가: {why2}"


def test_not_a_trend_falls_back_to_band():
    """추세가 아니면 기준선은 하단/상단 — 기존 동작이 그대로 살아 있어야 한다."""
    closes = [100.0] * 59 + [90.0]      # 횡보하다 급락 = 추세 아님
    a15 = {
        "closes": closes,
        "bb_mid_last": 99.5,
        "bb_up_last": 105.0,
        "bb_lo_last": 95.0,
    }
    long_trend, _ = _is_long_trend(a15, "LONG")
    assert not long_trend
    base, why = _entry_plan(a15, "LONG", long_trend, SPLIT_STEP_PCT)
    assert base == Decimal("95.0"), f"하단 모드여야 한다: {why}"


def test_insufficient_bars_is_refused_not_crashed():
    """봉이 모자라면 조용히 False — 인덱스 예외로 워커가 죽으면 안 된다."""
    a15 = {"closes": [100.0] * 10, "bb_mid_last": 100.0,
           "bb_up_last": 105.0, "bb_lo_last": 95.0}
    ok, why = _is_long_trend(a15, "LONG")
    assert ok is False
    assert "부족" in why
