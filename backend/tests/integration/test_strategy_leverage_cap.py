"""StrategyService.create_strategy_instance 의 레버리지 상한 가드 (MAINNET-CHECKLIST 3-4).

배경 (2026-05-07): mainnet 진입 시 레버리지 정책 강화 — Binance API 는 최대 125x 까지
허용하지만 청산 위험 큼. settings.max_leverage 양수면 그 한도 초과 시 거부.

template.leverage 와 leverage_override 둘 다 검사. 둘 중 큰 쪽 (실효 leverage) 이 한도 초과 시 차단.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.strategy_service import StrategyService


def _patch_binance(monkeypatch, available: str = "10000"):
    class _FakeClient:
        def __init__(self, **kwargs): pass
        def get_account(self):
            return {"availableBalance": available, "totalMarginBalance": available, "totalMaintMargin": "0", "positions": []}
    monkeypatch.setattr("app.integrations.binance.client.BinanceClient", _FakeClient)
    monkeypatch.setattr("app.core.crypto.decrypt_text", lambda s: s)


class TestLeverageCapGuard:
    def test_template_leverage_above_cap_rejected(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, monkeypatch
    ) -> None:
        """template.leverage=10, max_leverage=5 → 거부."""
        monkeypatch.setattr("app.core.config.settings.max_leverage", 5, raising=False)
        _patch_binance(monkeypatch)
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(leverage=10)

        with pytest.raises(ValueError, match=r"레버리지 10x > 한도 5x"):
            StrategyService(db_session).create_strategy_instance(
                user_id=u.id, exchange_account_id=ea.id,
                strategy_template_id=tpl.id, symbol="BTCUSDT",
                side="SHORT", start_price=Decimal("5000"),
            )

    def test_override_above_cap_rejected(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, monkeypatch
    ) -> None:
        """template=2x 이지만 override=10x 시 → 거부 (override 가 effective)."""
        monkeypatch.setattr("app.core.config.settings.max_leverage", 5, raising=False)
        _patch_binance(monkeypatch)
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(leverage=2)

        with pytest.raises(ValueError, match=r"레버리지 10x > 한도 5x"):
            StrategyService(db_session).create_strategy_instance(
                user_id=u.id, exchange_account_id=ea.id,
                strategy_template_id=tpl.id, symbol="BTCUSDT",
                side="SHORT", start_price=Decimal("5000"),
                leverage_override=10,
            )

    def test_at_cap_passes(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, monkeypatch
    ) -> None:
        """leverage == max_leverage → 허용 (=가드, > 만 차단)."""
        monkeypatch.setattr("app.core.config.settings.max_leverage", 5, raising=False)
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

    def test_none_setting_disables_cap(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, monkeypatch
    ) -> None:
        """max_leverage=None → 비활성 (Binance API 한도까지 허용)."""
        monkeypatch.setattr("app.core.config.settings.max_leverage", None, raising=False)
        _patch_binance(monkeypatch)
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(leverage=50)  # 매우 높은 레버리지

        instance = StrategyService(db_session).create_strategy_instance(
            user_id=u.id, exchange_account_id=ea.id,
            strategy_template_id=tpl.id, symbol="BTCUSDT",
            side="SHORT", start_price=Decimal("5000"),
        )
        assert instance.id > 0  # 정상 통과

    def test_zero_setting_disables_cap(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, monkeypatch
    ) -> None:
        """max_leverage=0 도 비활성 (deploy-safe: 0 으로 모든 거래 막히는 사고 방어)."""
        monkeypatch.setattr("app.core.config.settings.max_leverage", 0, raising=False)
        _patch_binance(monkeypatch)
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(leverage=20)

        instance = StrategyService(db_session).create_strategy_instance(
            user_id=u.id, exchange_account_id=ea.id,
            strategy_template_id=tpl.id, symbol="BTCUSDT",
            side="SHORT", start_price=Decimal("5000"),
        )
        assert instance.id > 0
