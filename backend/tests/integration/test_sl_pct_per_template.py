"""SL 임계 사용자 정의 검증 — template.stop_loss_percent_of_capital 적용.

2026-05-14: 사용자 「🛑 손절: 90」 입력이 hardcoded 50% 로 무시되던 버그 → 템플릿 값 우선, NULL/0 이하면 default 50%.
2026-06-11 v4 (9113381, 사장님 「포지션 진입가에서 손실 -80%」): 판정 기준이 「자본 대비 USD 손실」에서
  **평단 대비 ROI = (평단↔현재가)% × 레버리지 <= -sl_pct** 로 바뀌었다 (Fix 417: 테스트를 현재 사양으로 갱신).
  현재가 = Redis mark price 우선 → 여기서는 get_mark_price 를 고정값으로 바꿔 준다.
"""
from __future__ import annotations

from decimal import Decimal

import pytest


@pytest.fixture
def mark(monkeypatch):
    """get_mark_price(symbol) 가 돌려줄 값을 테스트마다 정한다."""
    box = {"price": None}
    import app.services.mark_price_cache as M
    monkeypatch.setattr(M, "get_mark_price", lambda _sym: box["price"])
    return box


class TestSLPercentPerTemplate:
    def _make(self, make_user, make_exchange_account, make_symbol, make_template, make_strategy,
              sl_pct, *, stages=3, current_stage=3, leverage=2, side="LONG", entry=Decimal("100")):
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(stages_config={"capitals": ["100"] * stages}, stop_loss_percent_of_capital=sl_pct)
        return make_strategy(
            user=u, exchange_account=ea, template=tpl, side=side,
            current_stage=current_stage, total_capital=Decimal("100"), leverage=leverage,
            avg_entry_price=entry, realized_pnl=Decimal("0"), unrealized_pnl=Decimal("0"),
        )

    def _check(self, db_session, mark, s, price):
        from app.services.risk_service import RiskService
        mark["price"] = price
        return RiskService(db_session).evaluate_stop_loss(s.id)

    def test_default_50_pct(self, db_session, mark, make_user, make_exchange_account, make_symbol, make_template, make_strategy):
        """50%, 레버 2, LONG 평단 100 → 75 에서 ROI -50% = 발동, 75.5 (-49%) = 미발동."""
        s = self._make(make_user, make_exchange_account, make_symbol, make_template, make_strategy, Decimal("50"))
        assert self._check(db_session, mark, s, 75) is True, "임계 정확 도달 → SL 발동"
        assert self._check(db_session, mark, s, 75.5) is False, "임계 미달 → 미발동"

    def test_user_set_90_pct(self, db_session, mark, make_user, make_exchange_account, make_symbol, make_template, make_strategy):
        """사용자 90%: ROI -50% 는 미발동(옛 버그면 50% 로 발동), -90% (55) 에서 발동."""
        s = self._make(make_user, make_exchange_account, make_symbol, make_template, make_strategy, Decimal("90"))
        assert self._check(db_session, mark, s, 75) is False, "90% 설정 → ROI -50% 는 미발동"
        assert self._check(db_session, mark, s, 55) is True

    def test_user_set_30_pct_more_aggressive(self, db_session, mark, make_user, make_exchange_account, make_symbol, make_template, make_strategy):
        """사용자 30%: 85 (ROI -30%) 발동, 85.5 (-29%) 미발동."""
        s = self._make(make_user, make_exchange_account, make_symbol, make_template, make_strategy, Decimal("30"))
        assert self._check(db_session, mark, s, 85) is True, "30% 설정 → ROI -30% 도달 → 발동"
        assert self._check(db_session, mark, s, 85.5) is False

    def test_short_side_uses_price_rise(self, db_session, mark, make_user, make_exchange_account, make_symbol, make_template, make_strategy):
        """SHORT 는 가격 상승이 손실: 평단 100, 50% → 125 발동, 124.5 미발동."""
        s = self._make(make_user, make_exchange_account, make_symbol, make_template, make_strategy, Decimal("50"), side="SHORT")
        assert self._check(db_session, mark, s, 125) is True
        assert self._check(db_session, mark, s, 124.5) is False

    def test_template_null_falls_back_to_50(self, db_session, mark, make_user, make_exchange_account, make_symbol, make_template, make_strategy):
        """template.stop_loss_percent_of_capital = 0 (잘못된 데이터) → default 50%."""
        s = self._make(make_user, make_exchange_account, make_symbol, make_template, make_strategy, Decimal("0"))
        assert self._check(db_session, mark, s, 75) is True, "sl_pct=0 → default 50% → ROI -50% 도달"
        assert self._check(db_session, mark, s, 75.5) is False

    def test_no_mark_price_cannot_judge(self, db_session, mark, make_user, make_exchange_account, make_symbol, make_template, make_strategy):
        """현재가를 모르면 판정 불가 = False (강제 손절 경로가 따로 받친다)."""
        s = self._make(make_user, make_exchange_account, make_symbol, make_template, make_strategy, Decimal("50"))
        assert self._check(db_session, mark, s, None) is False

    def test_partial_stage_no_sl_regardless(self, db_session, mark, make_user, make_exchange_account, make_symbol, make_template, make_strategy):
        """v130 사장님: 다음 단계가 남아 있으면 손절 임계를 넘어도 미발동 — 현재가를 임계 **아래로** 둬서 단계 게이트 자체를 검증."""
        s = self._make(make_user, make_exchange_account, make_symbol, make_template, make_strategy, Decimal("30"),
                       stages=5, current_stage=2)
        assert self._check(db_session, mark, s, 50) is False, "2/5 단계 → ROI -100% 여도 미발동"
        full = self._make(make_user, make_exchange_account, make_symbol, make_template, make_strategy, Decimal("30"),
                          stages=5, current_stage=5)
        assert self._check(db_session, mark, full, 50) is True, "대조: 5/5 단계면 같은 가격에서 발동 = 위 False 는 단계 게이트 때문"
