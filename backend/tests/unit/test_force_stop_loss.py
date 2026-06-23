"""손실 한도 강제 청산 (Force Stop-Loss) ROI 판정 단위 테스트.

FORCE_SL_LOSS_LIMIT_SPEC 2026-06-24 의 검증 시나리오 1:1 매칭.
순수 함수 force_sl_should_trigger 로 ROI 계산/임계 판정을 DB 무관하게 검증.
"""
from decimal import Decimal

from app.services.risk_service import force_sl_should_trigger, resolve_force_sl


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


# ───────────── 전략별 override → 전역 우선순위 (2026-06-24) ─────────────

def test_resolve_inherits_global_when_override_none():
    """override 둘 다 None → 전역 그대로 상속."""
    enabled, thr = resolve_force_sl(
        override_enabled=None, override_roi=None,
        global_enabled=True, global_roi=Decimal("10"),
    )
    assert enabled is True and thr == Decimal("10")


def test_resolve_strategy_off_overrides_global_on():
    """전역 ON 이어도 전략 override=False 면 → 꺼짐 (전략 우선)."""
    enabled, thr = resolve_force_sl(
        override_enabled=False, override_roi=None,
        global_enabled=True, global_roi=Decimal("10"),
    )
    assert enabled is False


def test_resolve_strategy_on_overrides_global_off():
    """전역 OFF(숏 기본) 여도 전략 override=True+roi 면 → 켜짐 (전략 우선)."""
    enabled, thr = resolve_force_sl(
        override_enabled=True, override_roi=15,
        global_enabled=False, global_roi=Decimal("10"),
    )
    assert enabled is True and thr == Decimal("15")


def test_resolve_strategy_roi_overrides_global_roi():
    """전략 roi override 가 전역 roi 보다 우선."""
    _, thr = resolve_force_sl(
        override_enabled=None, override_roi=20,
        global_enabled=True, global_roi=Decimal("10"),
    )
    assert thr == Decimal("20")


def test_resolve_then_trigger_short_strategy_on_global_off():
    """통합: 숏 전역 OFF + 전략 ON -15% → ROI -15% 도달 시 발동."""
    enabled, thr = resolve_force_sl(
        override_enabled=True, override_roi=15,
        global_enabled=False, global_roi=Decimal("10"),
    )
    assert force_sl_should_trigger(
        side="SHORT", avg_entry=Decimal("0.50"), mark_price=Decimal("0.5375"),
        leverage=2, enabled=enabled, threshold=thr,
    ) is True
