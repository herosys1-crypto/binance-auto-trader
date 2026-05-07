"""StrategyService 의 청산가 안전 거리 가드 (MAINNET-CHECKLIST 3-5).

배경 (2026-05-07): mainnet 진입 시 청산가까지의 거리가 너무 가까우면 작은 가격
변동에도 강제 청산 → 손실 확대. settings.min_liquidation_distance_pct 양수면
거리 부족 시 거부.

추정 공식 (Isolated, 보수적): distance% ≈ (1 - mmr) / leverage × 100, mmr=0.5%.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.strategy_service import StrategyService


def _patch_binance(monkeypatch):
    class _FakeClient:
        def __init__(self, **kwargs): pass
        def get_account(self):
            return {"availableBalance": "10000", "totalMarginBalance": "10000", "totalMaintMargin": "0", "positions": []}
    monkeypatch.setattr("app.integrations.binance.client.BinanceClient", _FakeClient)
    monkeypatch.setattr("app.core.crypto.decrypt_text", lambda s: s)


class TestLiquidationDistanceGuard:
    def test_high_leverage_close_liq_rejected(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, monkeypatch
    ) -> None:
        """leverage=20 → 거리 ≈ 4.97%. min=5% 면 거부."""
        monkeypatch.setattr("app.core.config.settings.min_liquidation_distance_pct", 5.0, raising=False)
        monkeypatch.setattr("app.core.config.settings.max_leverage", None, raising=False)
        _patch_binance(monkeypatch)
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(leverage=20)

        with pytest.raises(ValueError, match=r"청산가 안전 거리 부족"):
            StrategyService(db_session).create_strategy_instance(
                user_id=u.id, exchange_account_id=ea.id,
                strategy_template_id=tpl.id, symbol="BTCUSDT",
                side="SHORT", start_price=Decimal("5000"),
            )

    def test_low_leverage_safe_distance_passes(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, monkeypatch
    ) -> None:
        """leverage=5 → 거리 ≈ 19.9%. min=5% 통과."""
        monkeypatch.setattr("app.core.config.settings.min_liquidation_distance_pct", 5.0, raising=False)
        monkeypatch.setattr("app.core.config.settings.max_leverage", None, raising=False)
        _patch_binance(monkeypatch)
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(leverage=5)

        instance = StrategyService(db_session).create_strategy_instance(
            user_id=u.id, exchange_account_id=ea.id,
            strategy_template_id=tpl.id, symbol="BTCUSDT",
            side="SHORT", start_price=Decimal("5000"),
        )
        assert instance.id > 0

    def test_none_setting_disables_guard(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, monkeypatch
    ) -> None:
        """min_liquidation_distance_pct=None → 가드 비활성. leverage=50 도 통과."""
        monkeypatch.setattr("app.core.config.settings.min_liquidation_distance_pct", None, raising=False)
        monkeypatch.setattr("app.core.config.settings.max_leverage", None, raising=False)
        _patch_binance(monkeypatch)
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(leverage=50)

        instance = StrategyService(db_session).create_strategy_instance(
            user_id=u.id, exchange_account_id=ea.id,
            strategy_template_id=tpl.id, symbol="BTCUSDT",
            side="SHORT", start_price=Decimal("5000"),
        )
        assert instance.id > 0

    def test_long_side_same_formula(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, monkeypatch
    ) -> None:
        """LONG 도 동일 거리 공식 — leverage=10 에서 거리 ≈ 9.95%, min=10% 면 거부."""
        monkeypatch.setattr("app.core.config.settings.min_liquidation_distance_pct", 10.0, raising=False)
        monkeypatch.setattr("app.core.config.settings.max_leverage", None, raising=False)
        _patch_binance(monkeypatch)
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(leverage=10, side="LONG")

        with pytest.raises(ValueError, match=r"청산가 안전 거리 부족"):
            StrategyService(db_session).create_strategy_instance(
                user_id=u.id, exchange_account_id=ea.id,
                strategy_template_id=tpl.id, symbol="BTCUSDT",
                side="LONG", start_price=Decimal("5000"),
            )
