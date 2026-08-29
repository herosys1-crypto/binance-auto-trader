"""🚨 Fix 212 / Fix 215 — 「긴 추세(중단선)」 모드가 실제로 진입 가능한가.

사장님 확정 설계 (2026-08-29):
  "볼밴 중단은 지속 상승일때 같은 전략으로 하고 지속 하락 할때도 볼밴 중단으로 활용해서"

## Fix 212 — 자기모순 (진입이 **수학적으로** 불가능했다)

  _is_long_trend  — LONG 은 **현재 봉 포함** 6봉이 전부 `종가 > 중단선` 이어야 참
  _entry_plan     — 참이면 base=중단선, 진입은 `종가 <= 중단선 × 0.97`

같은 봉의 종가가 중단선보다 위이면서 동시에 3% 아래일 수는 없다.
→ 추세는 **직전 6봉**으로 보고(현재 봉 제외), 현재 봉의 눌림목에서 산다.

## Fix 215 — 중단은 「-3%」가 아니라 「이탈」 (사장님 「b」)

사장님 원문이 하단과 중단을 **다르게** 말한다:
  "볼밴 하단 **-3%**일때 100 진입"   /   "긴상승에는 중단 **이탈시**"

실측 2026-08-29 16:19 사이클 — 중단에도 -3% 를 요구하니 1차 목표가가
현재가에서 **중앙값 -7.2%, 최대 -15.1%**(PROMUSDT: 현재가가 중단선보다 +14.2% 위).
그래서 후보 14건이 전부 no_break 였다. → 중단은 이탈 즉시, 간격은 그대로(0/2/4).
"""
from __future__ import annotations

from decimal import Decimal

from app.workers.pump_split_entry_worker import (
    LONG_TREND_BARS,
    SPLIT_STEP_PCT,
    _entry_plan,
    _is_long_trend,
    check_no_dead_stage,
    mid_steps,
)

LEV = 2


def _uptrend_then_dip(dip: float, live: float | None = None, n: int = 62):
    """상승 추세 → **완료봉**에서 눌림 → 마지막에 진행 중 봉.

    🚨 Fix 216 이후 중단 모드의 판정 봉은 `closes[-2]`(마지막 완료봉)다.
       실제 `analyze_timeframe` 은 klines 를 자르지 않아 `closes[-1]` 이
       **아직 안 끝난 봉**이므로, 시험 데이터도 그 모양이어야 한다.
    """
    body = [100.0 + 0.5 * k for k in range(n - 2)]
    closes = body + [dip, dip if live is None else live]
    mid_completed = sum(closes[-21:-1]) / 20.0     # closes[-2] 시점의 20MA
    return {
        "closes": closes,
        "bb_mid_last": sum(closes[-20:]) / 20.0,   # 진행 중 봉 포함 (하단 모드용)
        "bb_up_last": mid_completed * 1.05,
        "bb_lo_last": mid_completed * 0.95,
    }, mid_completed


def _a15(close, mid):
    """`_entry_plan` 만 직접 시험할 때 쓰는 최소 스냅샷."""
    return {
        "closes": [close],
        "bb_mid_last": mid,
        "bb_up_last": mid * 1.05,
        "bb_lo_last": mid * 0.95,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Fix 212 — 추세 판정에서 현재 봉을 뺀다
# ═══════════════════════════════════════════════════════════════════════════
def test_uptrend_pullback_is_a_trend():
    """상승 추세 중 **완료봉** 눌림 = 사장님이 사겠다고 한 바로 그 자리."""
    # 진행 중 봉은 일부러 한참 위(130)에 둔다 — 판정에 끼면 안 된다.
    a15, mid = _uptrend_then_dip(120.0, live=130.0)
    long_trend, why = _is_long_trend(a15, "LONG")
    assert long_trend, f"직전 6봉이 전부 중단선 위인데 추세로 안 본다: {why}"

    base, why2, _ = _entry_plan(a15, "LONG", long_trend, SPLIT_STEP_PCT)
    assert base is not None, f"긴 추세 모드인데 진입 불가: {why2}"
    assert abs(float(base) - mid) < 1e-6, "긴 추세면 기준선은 **완료봉** 중단선이어야 한다"


def test_in_progress_bar_alone_must_not_trigger_entry():
    """🚨 Fix 216 음성 대조군 — 진행 중 봉만 이탈하면 **진입하지 않는다**.

    chart_analyzer:274 가 klines 를 자르지 않아 closes[-1] 은 아직 안 끝난 봉이다.
    중단 모드는 여유가 0(이탈 즉시)이라, 이걸 믿으면 봉 안의 틱 하나로 시장가가
    나가고 그 봉이 되돌리면 「없던 이탈」 위에 2·3차와 손절이 앵커된다.
    """
    # 완료봉은 중단선 **위**(130), 진행 중 봉만 아래로 100 까지 찍었다.
    a15, _ = _uptrend_then_dip(130.0, live=100.0)
    long_trend, _ = _is_long_trend(a15, "LONG")
    assert long_trend, "대조군 전제(긴 추세)가 안 만들어졌다"
    base, why, _ = _entry_plan(a15, "LONG", long_trend, SPLIT_STEP_PCT)
    assert base is None, f"진행 중 봉만으로 진입했다 = Fix 216 이 안 먹는다: {why}"


def test_short_side_is_symmetric():
    """SHORT = 지속 하락 중 중단선 되돌림 (사장님 「지속 하락 할때도 중단으로」)."""
    n = 62
    body = [200.0 - 0.5 * k for k in range(n - 2)]
    bump = 180.0                                   # 완료봉이 중단선 위로 튕김
    closes = body + [bump, 170.0]                  # 마지막은 진행 중 봉
    mid = sum(closes[-21:-1]) / 20.0
    a15 = {
        "closes": closes,
        "bb_mid_last": mid,
        "bb_up_last": mid * 1.05,
        "bb_lo_last": mid * 0.95,
    }
    long_trend, why = _is_long_trend(a15, "SHORT")
    assert long_trend, f"직전 {LONG_TREND_BARS}봉이 전부 중단선 아래인데: {why}"
    base, why2, _ = _entry_plan(a15, "SHORT", long_trend, SPLIT_STEP_PCT)
    assert base is not None, f"긴 하락 추세인데 진입 불가: {why2}"


def test_insufficient_bars_is_refused_not_crashed():
    """봉이 모자라면 조용히 False — 인덱스 예외로 워커가 죽으면 안 된다."""
    ok, why = _is_long_trend(_a15(100.0, 100.0), "LONG")
    assert ok is False
    assert "부족" in why


# ═══════════════════════════════════════════════════════════════════════════
# Fix 215 — 중단은 「이탈」, 하단/상단은 그대로 「-3%」
# ═══════════════════════════════════════════════════════════════════════════
def test_mid_steps_keeps_spacing_and_zeroes_the_first():
    """3/5/7 → 0/2/4. 시작점만 0(이탈), 간격은 그대로 2%p 씩."""
    assert mid_steps(SPLIT_STEP_PCT) == [Decimal("0"), Decimal("2"), Decimal("4")]
    # 사장님이 트리거를 바꾸면 중단도 따라간다
    assert mid_steps([Decimal("3"), Decimal("6"), Decimal("9")]) == [
        Decimal("0"), Decimal("3"), Decimal("6"),
    ]


def test_mid_mode_enters_on_break_not_minus_3pct():
    """중단선을 아래로 통과하면 **즉시** 1차 진입 (이탈).

    실측 근거 — 2026-08-29 16:19 ZKPUSDT: close 0.047830 / 중단 0.047927.
    이미 중단선 아래인데 옛 조건(-3% = 0.046489)이라 진입 못 했다.
    """
    mid, close = 0.047927, 0.047830
    base, why, steps = _entry_plan(_a15(close, mid), "LONG", True, SPLIT_STEP_PCT)
    assert base is not None, f"중단선 아래인데 진입 불가: {why}"
    assert steps == mid_steps(SPLIT_STEP_PCT)
    # 옛 조건이었다면 못 들어갔다는 것도 같이 고정한다 (대조군)
    assert close > mid * 0.97, "대조군 무효 — 옛 조건으로도 들어갈 값이다"


def test_mid_mode_does_not_enter_above_the_line():
    """중단선 **위**면 진입하지 않는다 — 이탈이 아니다.

    실측 PROMUSDT: close 6.155 / 중단 5.3872 (중단보다 14.2% 위) = 진입 대상 아님.
    """
    base, why, _ = _entry_plan(_a15(6.155, 5.3872), "LONG", True, SPLIT_STEP_PCT)
    assert base is None
    assert "이탈 미도달" in why, why


def test_short_mid_mode_enters_on_upward_break():
    """SHORT 중단 모드는 **위로** 통과할 때 진입."""
    base, _, steps = _entry_plan(_a15(100.5, 100.0), "SHORT", True, SPLIT_STEP_PCT)
    assert base is not None
    assert steps == mid_steps(SPLIT_STEP_PCT)
    assert _entry_plan(_a15(99.5, 100.0), "SHORT", True, SPLIT_STEP_PCT)[0] is None


def test_band_mode_still_requires_minus_3pct():
    """🚨 하단/상단 모드는 **바뀌면 안 된다** (사장님 원문 "하단 -3%일때 100 진입")."""
    mid = 100.0
    lo = mid * 0.95            # _a15 의 하단
    # 하단 바로 아래 = 아직 -3% 미달 → 진입 X
    base, why, steps = _entry_plan(_a15(lo - 0.01, mid), "LONG", False, SPLIT_STEP_PCT)
    assert base is None, f"하단 모드가 이탈만으로 진입했다 = Fix 215 가 새어나갔다: {why}"
    assert steps == SPLIT_STEP_PCT
    # 하단 -3% 도달 → 진입 O
    base2, _, _ = _entry_plan(_a15(lo * 0.97 - 0.01, mid), "LONG", False, SPLIT_STEP_PCT)
    assert base2 is not None


def test_mid_steps_have_no_dead_stage():
    """0/2/4 조합에서도 어느 차수든 손절보다 **먼저** 도달해야 한다 (헌법 130).

    1차가 0% 라 평단이 기준선과 같고, 그만큼 손절선이 가깝다 — 여기서 죽으면
    「중단 3차가 조용히 미진입」이 된다. 운영 설정(100/200/500, SL 10%)으로 고정.
    """
    caps = [Decimal("100"), Decimal("200"), Decimal("500")]
    ok, why = check_no_dead_stage(caps, mid_steps(SPLIT_STEP_PCT), Decimal("10"), LEV)
    assert ok, why


def test_dead_stage_detector_still_bites_on_mid_steps():
    """음성 대조군 — 손절을 조이면 중단 단계가 실제로 죽는가."""
    caps = [Decimal("100"), Decimal("200"), Decimal("500")]
    ok, _ = check_no_dead_stage(caps, mid_steps(SPLIT_STEP_PCT), Decimal("2"), LEV)
    assert not ok, "SL -2% 면 1차 평단 손절이 2차 트리거보다 먼저 와야 한다"
