"""크라이시스 안전망 — 「💉 포지션 추가」 (ad-hoc) 사용 시 stage 조건 완화 (사용자 요청 2026-05-14).

배경:
사용자가 「💉 포지션 추가」 로 큰 자본 추가했지만 strategy.current_stage 는 안 늘어남
(stage_no=None ad-hoc 표시). 결과: 「모든 단계 진입 완료」 조건 미충족 → Crisis 영원히 미발동.
큰 손실 났는데도 빠른 회복 익절 (Crisis +5%) 기회 없음.

Fix (v4):
ad-hoc ENTRY (stage_no=NULL, purpose=ENTRY, status=FILLED) 가 있으면 stage 조건 완화.
즉 stage 미완료라도 ad-hoc 사용 흔적 + max_loss 임계 도달 → Crisis 발동.

검증:
1. ad-hoc 없음 + stage 미완료 → Crisis 미발동 (기존 동작 유지)
2. ad-hoc 있음 + stage 미완료 + max_loss 도달 → Crisis 발동 (신규 안전망)
3. ad-hoc 있음 + stage 미완료 + max_loss 미달 → Crisis 미발동 (임계 조건은 그대로)
4. 모든 단계 진입 + ad-hoc 무관 + max_loss 도달 → Crisis 발동 (기존)
"""
from __future__ import annotations

from decimal import Decimal

from app.models.order import Order


def _add_adhoc_order(db_session, strategy_id: int, status: str = "FILLED") -> Order:
    """ad-hoc ENTRY 주문 추가 (stage_no=NULL)."""
    o = Order(
        strategy_instance_id=strategy_id,
        stage_no=None,
        purpose="ENTRY",
        symbol="BTCUSDT",
        side="SELL",
        position_side="SHORT",
        order_type="MARKET",
        client_order_id=f"ADHOC_{strategy_id}_test",
        orig_qty=Decimal("100"),
        executed_qty=Decimal("100") if status == "FILLED" else Decimal("0"),
        status=status,
    )
    db_session.add(o)
    db_session.commit()
    return o


class TestAdhocSafetyNet:
    def test_no_adhoc_partial_stage_no_crisis(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy
    ):
        """기존 동작: ad-hoc 없음 + stage 미완료 → Crisis 미발동."""
        from app.services.risk_service import RiskService
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(stages_config={"capitals": ["100"] * 5})
        s = make_strategy(
            user=u, exchange_account=ea, template=tpl,
            current_stage=2, max_loss_pct=Decimal("-60"),
        )
        rs = RiskService(db_session)
        assert rs._should_trigger_crisis_mode(s, Decimal("0")) is False, (
            "ad-hoc 없고 stage 2/5 → Crisis 미발동"
        )

    def test_adhoc_partial_stage_max_loss_reached_triggers_crisis(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy
    ):
        """v4 신규: ad-hoc 사용 + stage 미완료 + max_loss 도달 → Crisis 발동."""
        from app.services.risk_service import RiskService
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(stages_config={"capitals": ["100"] * 5})
        s = make_strategy(
            user=u, exchange_account=ea, template=tpl,
            current_stage=1, max_loss_pct=Decimal("-55"),
        )
        # 「💉 포지션 추가」 흔적 추가
        _add_adhoc_order(db_session, s.id)
        rs = RiskService(db_session)
        assert rs._should_trigger_crisis_mode(s, Decimal("0")) is True, (
            "v4 안전망: ad-hoc 사용 시 stage 조건 완화 → max_loss -55 ≤ -50 면 Crisis 발동"
        )

    def test_adhoc_partial_stage_max_loss_not_reached_no_crisis(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy
    ):
        """v4: ad-hoc 사용해도 max_loss 임계 미달이면 Crisis 미발동 (임계는 그대로)."""
        from app.services.risk_service import RiskService
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(stages_config={"capitals": ["100"] * 5})
        s = make_strategy(
            user=u, exchange_account=ea, template=tpl,
            current_stage=1, max_loss_pct=Decimal("-30"),  # -50 미달
        )
        _add_adhoc_order(db_session, s.id)
        rs = RiskService(db_session)
        assert rs._should_trigger_crisis_mode(s, Decimal("0")) is False, (
            "ad-hoc 있어도 max_loss -30 > -50 면 미달 → Crisis 미발동"
        )

    def test_adhoc_pending_does_not_count(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy
    ):
        """체결되지 않은 ad-hoc (status != FILLED) 은 안전망 trigger 안 함."""
        from app.services.risk_service import RiskService
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(stages_config={"capitals": ["100"] * 5})
        s = make_strategy(
            user=u, exchange_account=ea, template=tpl,
            current_stage=1, max_loss_pct=Decimal("-60"),
        )
        # ad-hoc 주문 PENDING (체결 X)
        _add_adhoc_order(db_session, s.id, status="NEW")
        rs = RiskService(db_session)
        assert rs._should_trigger_crisis_mode(s, Decimal("0")) is False, (
            "ad-hoc 미체결이면 안전망 X — stage 미완료라 Crisis 미발동"
        )

    def test_all_stages_entered_works_without_adhoc(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy
    ):
        """기존 동작 유지: 모든 단계 진입 완료 + max_loss 도달 → Crisis 발동 (ad-hoc 무관)."""
        from app.services.risk_service import RiskService
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(stages_config={"capitals": ["100"] * 3})
        s = make_strategy(
            user=u, exchange_account=ea, template=tpl,
            current_stage=3, max_loss_pct=Decimal("-55"),
        )
        # ad-hoc 추가 안 함
        rs = RiskService(db_session)
        assert rs._should_trigger_crisis_mode(s, Decimal("0")) is True

    def test_adhoc_with_custom_threshold(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy
    ):
        """v4 + v3 조합: ad-hoc 사용 + template 임계 -70 + max_loss -65 → 임계 미달 → 미발동."""
        from app.services.risk_service import RiskService
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(
            stages_config={"capitals": ["100"] * 5},
            crisis_max_loss_threshold=Decimal("-70"),
        )
        s = make_strategy(
            user=u, exchange_account=ea, template=tpl,
            current_stage=1, max_loss_pct=Decimal("-65"),
        )
        _add_adhoc_order(db_session, s.id)
        rs = RiskService(db_session)
        assert rs._should_trigger_crisis_mode(s, Decimal("0")) is False, (
            "ad-hoc 있어도 template 임계 -70 > max_loss -65 → 미달"
        )
        # max_loss -75 면 -70 도달 → 발동
        s.max_loss_pct = Decimal("-75")
        db_session.commit()
        assert rs._should_trigger_crisis_mode(s, Decimal("0")) is True
