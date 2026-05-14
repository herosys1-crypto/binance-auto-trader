"""SL 임계 사용자 정의 검증 — template.stop_loss_percent_of_capital 적용 (2026-05-14 fix).

배경 (사용자 발견 버그 2026-05-14):
사용자가 「🛑 손절: 90」 (총 자본 대비 90% 손실 한도) 입력해도 코드는 hardcoded
Decimal("0.50") 사용 → 50% 만 적용. 사용자 의도 위배.

Fix:
risk_service.evaluate_stop_loss 가 template.stop_loss_percent_of_capital 우선 사용.
NULL 또는 0 이하면 default 50%.
"""
from __future__ import annotations

from decimal import Decimal


class TestSLPercentPerTemplate:
    def _make_strategy_loss(self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy, sl_pct=None, current_pnl_usd=Decimal("-50"), capital=Decimal("100"), leverage=2):
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        kwargs = {"stages_config": {"capitals": [str(capital)] * 3}}
        if sl_pct is not None:
            kwargs["stop_loss_percent_of_capital"] = sl_pct
        else:
            kwargs["stop_loss_percent_of_capital"] = Decimal("50")  # default
        tpl = make_template(**kwargs)
        s = make_strategy(
            user=u, exchange_account=ea, template=tpl,
            current_stage=3,  # 모든 단계 진입 완료 (SL 발동 가능)
            total_capital=capital,
            leverage=leverage,
            realized_pnl=current_pnl_usd,
            unrealized_pnl=Decimal("0"),
        )
        return s

    def test_default_50_pct(self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy):
        """Default 50%: capital=100, leverage=2 → threshold = 100*0.5/2 = 25 USD 손실."""
        from app.services.risk_service import RiskService
        # 손실 -25 USD = 임계 정확 도달
        s_at = self._make_strategy_loss(
            db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy,
            sl_pct=Decimal("50"), current_pnl_usd=Decimal("-25"), capital=Decimal("100"), leverage=2,
        )
        rs = RiskService(db_session)
        assert rs.evaluate_stop_loss(s_at.id) is True, "임계 정확 도달 → SL 발동"

        # 손실 -24 USD = 임계 미달
        s_below = self._make_strategy_loss(
            db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy,
            sl_pct=Decimal("50"), current_pnl_usd=Decimal("-24"), capital=Decimal("100"), leverage=2,
        )
        assert rs.evaluate_stop_loss(s_below.id) is False, "임계 미달 → 미발동"

    def test_user_set_90_pct(self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy):
        """사용자 입력 90%: capital=100, leverage=2 → threshold = 100*0.9/2 = 45 USD 손실."""
        from app.services.risk_service import RiskService
        # 손실 -25 USD: 50% default 라면 발동했겠지만, 90% 면 미달
        s_25 = self._make_strategy_loss(
            db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy,
            sl_pct=Decimal("90"), current_pnl_usd=Decimal("-25"), capital=Decimal("100"), leverage=2,
        )
        rs = RiskService(db_session)
        assert rs.evaluate_stop_loss(s_25.id) is False, (
            "사용자 90% 설정 → -25 USD 손실은 임계 -45 미달 → 미발동 "
            "(이전 버그면 50% 사용해서 -25 == -25 발동했을 것)"
        )

        # 손실 -45 USD = 90% 임계 정확 도달
        s_45 = self._make_strategy_loss(
            db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy,
            sl_pct=Decimal("90"), current_pnl_usd=Decimal("-45"), capital=Decimal("100"), leverage=2,
        )
        assert rs.evaluate_stop_loss(s_45.id) is True

    def test_user_set_30_pct_more_aggressive(self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy):
        """사용자 입력 30% (더 보수적): threshold = 100*0.3/2 = 15 USD."""
        from app.services.risk_service import RiskService
        s = self._make_strategy_loss(
            db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy,
            sl_pct=Decimal("30"), current_pnl_usd=Decimal("-15"), capital=Decimal("100"), leverage=2,
        )
        rs = RiskService(db_session)
        assert rs.evaluate_stop_loss(s.id) is True, "30% 설정 → -15 USD 손실 = 임계 도달 → 발동"

        # -14 면 미달
        s2 = self._make_strategy_loss(
            db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy,
            sl_pct=Decimal("30"), current_pnl_usd=Decimal("-14"), capital=Decimal("100"), leverage=2,
        )
        assert rs.evaluate_stop_loss(s2.id) is False

    def test_template_null_falls_back_to_50(self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy):
        """template.stop_loss_percent_of_capital = 0 (이전 마이그레이션 잘못된 데이터 가능성) → default 50%."""
        from app.services.risk_service import RiskService
        # 0 = invalid → default 50%
        s = self._make_strategy_loss(
            db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy,
            sl_pct=Decimal("0"), current_pnl_usd=Decimal("-25"), capital=Decimal("100"), leverage=2,
        )
        rs = RiskService(db_session)
        assert rs.evaluate_stop_loss(s.id) is True, "sl_pct=0 → default 50% → -25 도달"

    def test_partial_stage_no_sl_regardless(self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy):
        """current_stage < total_stages 면 SL 미발동 (사용자 sl_pct 와 무관 — 기존 정책 유지)."""
        from app.services.risk_service import RiskService
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(
            stages_config={"capitals": ["100"] * 5},
            stop_loss_percent_of_capital=Decimal("30"),
        )
        s = make_strategy(
            user=u, exchange_account=ea, template=tpl,
            current_stage=2,  # 2/5 만 진입 — 모든 단계 미진입
            total_capital=Decimal("100"), leverage=2,
            realized_pnl=Decimal("-100"),  # 매우 큰 손실이지만
            unrealized_pnl=Decimal("0"),
        )
        rs = RiskService(db_session)
        assert rs.evaluate_stop_loss(s.id) is False, (
            "stage 미완료 → SL 미발동 (sl_pct 30% 무관 — 기존 정책 유지)"
        )
