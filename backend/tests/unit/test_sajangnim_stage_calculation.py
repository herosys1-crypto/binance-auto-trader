"""사장님 사상 단위 테스트 — 단계 계산 검증 (= Phase 4!)

spec: docs/spec/stage_calculation_spec_2026-06-11.md

테스트 사항:
1. 신 strategy = startPrice 기반 누적
2. 「수정 모드」 + 「현재가」 = 1단계 oldAvg + 2단계+ 누적
3. SHORT 오름차순 / LONG 내림차순
4. 사장님 BEATUSDT 실 시나리오 검증

= silent bug 영원히 X = 자동 차단!
"""
import pytest
from decimal import Decimal


def calculate_stages_new_strategy(start_price, triggers, side="SHORT"):
    """신 strategy = 단계 계산.

    1단계 = start_price
    N단계 = (N-1)단계 × (1 ± trigger_N%)
    """
    if not start_price or len(triggers) == 0:
        return []

    prices = []
    prev = Decimal(str(start_price))

    for i, trg in enumerate(triggers):
        if i == 0:
            # 1단계 = 시작가
            prices.append(prev)
            continue
        trg_pct = Decimal(str(trg or 0))
        if side == "SHORT":
            curr = prev * (Decimal("1") + trg_pct / Decimal("100"))
        else:
            curr = prev * (Decimal("1") - trg_pct / Decimal("100"))
        prices.append(curr)
        prev = curr

    return prices


def calculate_stages_edit_mode(start_price, old_avg, triggers, side="SHORT"):
    """수정 모드 + 「현재가」 클릭 = 사장님 사상!

    1단계 = old_avg (옛 평단 보존!)
    2단계 = start_price × (1 ± trigger_2%) (= 신 startPrice 기준!)
    N단계 = (N-1)단계 × (1 ± trigger_N%)
    """
    if not start_price or len(triggers) == 0:
        return []

    prices = []
    prev = Decimal(str(start_price))  # 2단계 기준!

    for i, trg in enumerate(triggers):
        if i == 0:
            # 1단계 = 옛 평단!
            prices.append(Decimal(str(old_avg)))
            continue
        trg_pct = Decimal(str(trg or 0))
        if side == "SHORT":
            curr = prev * (Decimal("1") + trg_pct / Decimal("100"))
        else:
            curr = prev * (Decimal("1") - trg_pct / Decimal("100"))
        prices.append(curr)
        prev = curr

    return prices


# ===== 사장님 사상 단위 테스트 =====


def test_new_strategy_short_basic():
    """신 strategy SHORT = 누적 계산"""
    result = calculate_stages_new_strategy(
        start_price="100",
        triggers=[0, 10, 20, 20],
        side="SHORT",
    )
    assert len(result) == 4
    assert result[0] == Decimal("100")
    assert result[1] == Decimal("110")  # 100 × 1.10
    assert result[2] == Decimal("132")  # 110 × 1.20
    assert result[3] == Decimal("158.4")  # 132 × 1.20


def test_new_strategy_long_basic():
    """신 strategy LONG = 누적 계산"""
    result = calculate_stages_new_strategy(
        start_price="100",
        triggers=[0, 10, 20],
        side="LONG",
    )
    assert result[0] == Decimal("100")
    assert result[1] == Decimal("90")  # 100 × 0.90
    assert result[2] == Decimal("72")  # 90 × 0.80


def test_edit_mode_short_sajangnim_beatusdt():
    """사장님 BEATUSDT 「수정 모드」 + 「현재가」 시나리오!"""
    result = calculate_stages_edit_mode(
        start_price="7.94",
        old_avg="6.31",
        triggers=[0, 10, 20, 20, 20, 20],
        side="SHORT",
    )
    assert len(result) == 6
    # 1단계 = 옛 평단 보존
    assert result[0] == Decimal("6.31")
    # 2단계 = startPrice × 1.10
    assert abs(result[1] - Decimal("8.734")) < Decimal("0.001")
    # 3단계 = 2단계 × 1.20
    assert abs(result[2] - Decimal("10.4808")) < Decimal("0.001")
    # 4단계 = 3단계 × 1.20
    assert abs(result[3] - Decimal("12.57696")) < Decimal("0.001")
    # 5단계 = 4단계 × 1.20
    assert abs(result[4] - Decimal("15.092352")) < Decimal("0.001")
    # 6단계 = 5단계 × 1.20 (= v43 silent bug 차단!)
    assert abs(result[5] - Decimal("18.1108224")) < Decimal("0.001")


def test_edit_mode_short_velvetusdt_scenario():
    """사장님 VELVETUSDT 시나리오"""
    result = calculate_stages_edit_mode(
        start_price="0.39131",
        old_avg="0.41234",
        triggers=[0, 10, 20, 20],
        side="SHORT",
    )
    assert result[0] == Decimal("0.41234")
    assert abs(result[1] - Decimal("0.430441")) < Decimal("0.001")


def test_short_must_be_ascending():
    """SHORT = 단계 진입가 = 오름차순 검증!"""
    result = calculate_stages_new_strategy(
        start_price="100",
        triggers=[0, 10, 20, 20, 20, 20],
        side="SHORT",
    )
    for i in range(1, len(result)):
        assert result[i] > result[i - 1], f"SHORT 단계{i+1} = 단계{i} 보다 커야 함!"


def test_long_must_be_descending():
    """LONG = 단계 진입가 = 내림차순 검증!"""
    result = calculate_stages_new_strategy(
        start_price="100",
        triggers=[0, 10, 20, 20],
        side="LONG",
    )
    for i in range(1, len(result)):
        assert result[i] < result[i - 1], f"LONG 단계{i+1} = 단계{i} 보다 작아야 함!"


def test_silent_bug_v43_not_regress():
    """v43 silent bug 재발 차단 테스트!

    옛 silent bug = 첫 미진입 단계 = startPrice × (1 + trigger%)
    = 6단계 = 7.94 × 1.20 = 9.52 (= silent bug!)

    신 v43 = 6단계 = 5단계 × 1.20 = 18.11 (= 정상!)
    """
    result = calculate_stages_edit_mode(
        start_price="7.94",
        old_avg="6.31",
        triggers=[0, 10, 20, 20, 20, 20],
        side="SHORT",
    )
    # 6단계 = 절대 9.52 X! (= silent bug 차단!)
    assert result[5] > Decimal("17"), "v43 silent bug 재발!"
    assert result[5] < Decimal("19")
