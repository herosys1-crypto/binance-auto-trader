"""손실 한도 강제 청산 (Force Stop-Loss) ROI 판정 단위 테스트.

FORCE_SL_LOSS_LIMIT_SPEC 2026-06-24 의 검증 시나리오 1:1 매칭.
순수 함수 force_sl_should_trigger 로 ROI 계산/임계 판정을 DB 무관하게 검증.
"""
from decimal import Decimal

from app.services.risk_service import force_sl_should_trigger


def test_force_sl_long_default_on_triggers_at_minus10():
    """사장님 기본: 롱 ON, -10%. 평단 100 → 95, 2x → ROI -10% → 발동."""
    assert force_sl_should_trigger(
        side="LONG", avg_entry=100, mark_price=95, leverage=2,
        enabled=True, threshold=10,
    ) is True


def test_force_sl_long_not_triggered_above_threshold():
    """롱 ON -10%: 평단 100 → 97, 2x → ROI -6% (한도 미달) → 유지."""
    assert force_sl_should_trigger(
        side="LONG", avg_entry=100, mark_price=97, leverage=2,
        enabled=True, threshold=10,
    ) is False


def test_force_sl_short_default_off_never_triggers():
    """사장님 기본: 숏 OFF → ROI -25% 여도 발동 X (enabled=False)."""
    assert force_sl_should_trigger(
        side="SHORT", avg_entry=Decimal("0.5"), mark_price=Decimal("0.5625"), leverage=2,
        enabled=False, threshold=10,
    ) is False


def test_force_sl_short_on_minus15_triggers():
    """숏 ON -15%: 평단 0.50 → 0.5375 = 숏 손실 -7.5% × 2 = ROI -15% → 발동."""
    assert force_sl_should_trigger(
        side="SHORT", avg_entry=Decimal("0.50"), mark_price=Decimal("0.5375"), leverage=2,
        enabled=True, threshold=15,
    ) is True


def test_force_sl_boundary_is_inclusive():
    """경계 포함: ROI == -한도 면 발동 (roi <= -threshold)."""
    # 평단 100 → 90, 1x → ROI -10% == 한도 -10% → True
    assert force_sl_should_trigger(
        side="LONG", avg_entry=100, mark_price=90, leverage=1,
        enabled=True, threshold=10,
    ) is True


def test_force_sl_no_markprice_never_closes():
    """가격 없음 → 절대 청산 X (안전 최우선, 시나리오 E)."""
    assert force_sl_should_trigger(
        side="LONG", avg_entry=100, mark_price=None, leverage=2,
        enabled=True, threshold=10,
    ) is False


def test_force_sl_threshold_zero_or_negative_never_closes():
    """한도 0/음수 = 비정상 설정 → 발동 X (안전)."""
    assert force_sl_should_trigger(
        side="LONG", avg_entry=100, mark_price=50, leverage=2,
        enabled=True, threshold=0,
    ) is False


def test_force_sl_long_profit_never_triggers():
    """롱 이익 구간(가격 상승) → 손절 발동 X."""
    assert force_sl_should_trigger(
        side="LONG", avg_entry=100, mark_price=110, leverage=2,
        enabled=True, threshold=10,
    ) is False
