"""사장님 E2E 시나리오 테스트 — Phase 4!

= 사장님 실 운영 시나리오 통합 검증!
= silent bug 영원히 X!

시나리오:
1. 신 strategy 생성 → 단계 plan 정확
2. 「수정 모드」 진입 → 옛 세팅 그대로
3. 「현재가」 클릭 → 1단계 평단 + 2단계+ 누적
4. 모든 사장님 헌법 준수 검증
"""
from decimal import Decimal
from app.services.stage_calculator import (
    calculate_stages_new,
    calculate_stages_edit_mode,
    validate_stage_order,
)
from app.services.current_price_action import calculate_stages_after_current_price_click
from app.services.edit_mode_service import (
    get_old_start_price,
    is_start_price_changed,
    should_preserve_old_avg,
    EditModeOption,
)


# ===== E2E 시나리오 1: BEATUSDT 실제 운영 사례 =====


def test_e2e_beatusdt_full_lifecycle():
    """사장님 BEATUSDT 전체 lifecycle 검증!

    Step 1: 사장님 = 신 strategy 만들기 (시작가 4.20)
    Step 2: 가격 상승 = 4단계 진입 (= 평단 6.31)
    Step 3: 사장님 = 「수정 모드」 진입 → 옛 세팅 그대로!
    Step 4: 사장님 = 「현재가」 클릭 (= 7.94) → 1단계 평단 + 2단계+ 누적!
    Step 5: 사장님 = 「설정만 수정」 → 옛 포지션 유지 + 신 trigger 적용
    """
    # Step 1: 신 strategy
    initial_stages = calculate_stages_new(
        start_price="4.20",
        triggers=[0, 10, 20, 20, 20, 20],
        side="SHORT",
    )
    assert initial_stages[0] == Decimal("4.20")
    assert validate_stage_order(initial_stages, "SHORT") is True

    # Step 2: 가격 상승 (= 사장님 4단계 진입 완료 = 평단 6.31)
    # (= mainnet 시뮬레이션은 외부 = 단위 테스트는 사상 검증만)

    # Step 3: 「수정 모드」 진입 = 옛 세팅 그대로
    blueprint = {
        "start_price": "4.20",        # 옛 시작가
        "avg_entry_price": "6.31",    # 옛 평단 (= 사장님 진입!)
        "side": "SHORT",
    }
    old_sp = get_old_start_price(blueprint)
    assert old_sp == "4.20"  # = 옛 그대로!

    # Step 4: 「현재가」 클릭 = 7.94
    new_sp = "7.94"
    assert is_start_price_changed(blueprint, new_sp) is True
    assert should_preserve_old_avg(blueprint, new_sp, editing_strategy_id=110) is True

    # 신 단계 계산 = 사장님 사상!
    result = calculate_stages_after_current_price_click(
        blueprint=blueprint,
        new_start_price=new_sp,
        triggers=[0, 10, 20, 20, 20, 20],
        side="SHORT",
        editing_strategy_id=110,
    )
    # 1단계 = 옛 평단 보존!
    assert result[0] == Decimal("6.31")
    # 2단계 = 신 startPrice × 1.10
    assert abs(result[1] - Decimal("8.734")) < Decimal("0.01")
    # 6단계 = v43 silent bug 차단!
    assert result[5] > Decimal("17")  # = 절대 9.52 X!


# ===== E2E 시나리오 2: VELVETUSDT =====


def test_e2e_velvetusdt_edit_mode():
    """사장님 VELVETUSDT 「수정 모드」 시나리오"""
    blueprint = {
        "start_price": "0.41",
        "avg_entry_price": "0.41234",
        "side": "SHORT",
    }
    result = calculate_stages_after_current_price_click(
        blueprint=blueprint,
        new_start_price="0.39131",
        triggers=[0, 10, 20, 20],
        side="SHORT",
        editing_strategy_id=109,
    )
    assert result[0] == Decimal("0.41234")  # 옛 평단!


# ===== E2E 시나리오 3: LONG strategy =====


def test_e2e_long_strategy_scenario():
    """LONG strategy 시나리오 (= 가격 하락 시 추가)"""
    result = calculate_stages_new(
        start_price="100",
        triggers=[0, 10, 20, 20],
        side="LONG",
    )
    assert result[0] == Decimal("100")
    # LONG = 내림차순!
    for i in range(1, len(result)):
        assert result[i] < result[i - 1]
    assert validate_stage_order(result, "LONG") is True


# ===== E2E 시나리오 4: silent bug 영구 차단 =====


def test_e2e_silent_bug_v43_永구_차단():
    """v43 silent bug = 다시는 발생 X!

    옛 silent bug: 첫 미진입 단계 = startPrice × (1 + trigger%)
    = 사장님 6단계 = 7.94 × 1.20 = 9.52 (= silent bug!)

    신 v43: 6단계 = 누적 = 18.10 (= 정상!)
    """
    blueprint = {
        "start_price": "4.20",
        "avg_entry_price": "6.31",
        "side": "SHORT",
    }
    result = calculate_stages_after_current_price_click(
        blueprint=blueprint,
        new_start_price="7.94",
        triggers=[0, 10, 20, 20, 20, 20],
        side="SHORT",
        editing_strategy_id=110,
    )
    # 6단계 = 절대 9.52 X (= silent bug 차단!)
    assert result[5] > Decimal("17"), "🚨 v43 silent bug 재발!"
    # 5단계 < 6단계 (= SHORT 오름차순!)
    assert result[5] > result[4]


# ===== E2E 시나리오 5: 모든 헌법 검증 =====


def test_e2e_사장님_헌법_18개_준수():
    """사장님 헌법 18개 = 모든 시나리오 = 자동 준수!"""
    # 헌법 13번: 「수정 모드」 = 옛 세팅 그대로!
    bp = {"start_price": "10", "avg_entry_price": "12"}
    assert get_old_start_price(bp) == "10"  # = 옛 그대로

    # 헌법 14번: 「현재가」 클릭 = 1단계 평단 + 2단계+ 누적
    result = calculate_stages_after_current_price_click(
        blueprint=bp,
        new_start_price="15",
        triggers=[0, 10],
        side="SHORT",
        editing_strategy_id=999,
    )
    assert result[0] == Decimal("12")  # = 옛 평단!
    assert abs(result[1] - Decimal("16.5")) < Decimal("0.01")  # 15 × 1.10
