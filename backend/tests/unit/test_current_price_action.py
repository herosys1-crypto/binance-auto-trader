"""사장님 「현재가」 클릭 액션 통합 테스트.

= edit_mode_service + stage_calculator + current_price_action 통합 검증!
spec: docs/spec/current_price_action_spec_2026-06-11.md
"""
from decimal import Decimal
from app.services.current_price_action import calculate_stages_after_current_price_click
from app.services.edit_mode_service import (
    get_old_start_price,
    is_start_price_changed,
    should_preserve_old_avg,
)


# ===== get_old_start_price =====


def test_get_old_start_price_from_start_price():
    """bp.start_price 있음 = 사용"""
    bp = {"start_price": "4.20", "avg_entry_price": "6.00"}
    assert get_old_start_price(bp) == "4.20"


def test_get_old_start_price_fallback_avg_entry():
    """bp.start_price NULL = avg_entry_price fallback (v41!)"""
    bp = {"start_price": None, "avg_entry_price": "6.00"}
    assert get_old_start_price(bp) == "6.00"


def test_get_old_start_price_both_null():
    """둘 다 NULL = 빈 문자열"""
    bp = {"start_price": None, "avg_entry_price": None}
    assert get_old_start_price(bp) == ""


# ===== is_start_price_changed =====


def test_is_start_price_changed_yes():
    """사장님 = 신 가격 입력 = 변경 감지!"""
    bp = {"start_price": "4.20"}
    assert is_start_price_changed(bp, "7.43") is True


def test_is_start_price_changed_no_small_diff():
    """차이 < 0.1% = 변경 X"""
    bp = {"start_price": "4.20"}
    assert is_start_price_changed(bp, "4.20") is False


# ===== should_preserve_old_avg =====


def test_should_preserve_yes_edit_mode_with_avg():
    """수정 모드 + 시작가 변경 + 옛 평단 있음 = 보존!"""
    bp = {"start_price": "4.20", "avg_entry_price": "6.00"}
    assert should_preserve_old_avg(bp, "7.43", editing_strategy_id=110) is True


def test_should_preserve_no_not_editing():
    """신 strategy = 보존 X"""
    bp = {"start_price": "4.20", "avg_entry_price": "6.00"}
    assert should_preserve_old_avg(bp, "7.43", editing_strategy_id=None) is False


def test_should_preserve_no_same_price():
    """시작가 변경 X = 보존 X (= 옛 그대로 사용 = OK)"""
    bp = {"start_price": "4.20", "avg_entry_price": "6.00"}
    assert should_preserve_old_avg(bp, "4.20", editing_strategy_id=110) is False


# ===== calculate_stages_after_current_price_click =====


def test_current_price_click_edit_mode_sajangnim_beatusdt():
    """사장님 BEATUSDT 시나리오 = 핵심 통합 테스트!"""
    bp = {
        "start_price": "4.20",
        "avg_entry_price": "6.31",
    }
    result = calculate_stages_after_current_price_click(
        blueprint=bp,
        new_start_price="7.94",
        triggers=[0, 10, 20, 20, 20, 20],
        side="SHORT",
        editing_strategy_id=110,
    )
    assert len(result) == 6
    # 1단계 = 옛 평단 보존!
    assert result[0] == Decimal("6.31")
    # 2단계 = 신 startPrice × 1.10
    assert abs(result[1] - Decimal("8.734")) < Decimal("0.001")
    # 6단계 = 5단계 × 1.20 (= v43 silent bug 차단!)
    assert abs(result[5] - Decimal("18.1108224")) < Decimal("0.001")


def test_current_price_click_new_strategy():
    """신 strategy = 1단계 = 신 시작가!"""
    result = calculate_stages_after_current_price_click(
        blueprint=None,
        new_start_price="100",
        triggers=[0, 10, 20],
        side="SHORT",
        editing_strategy_id=None,
    )
    assert result[0] == Decimal("100")
    assert result[1] == Decimal("110")
    assert result[2] == Decimal("132")
