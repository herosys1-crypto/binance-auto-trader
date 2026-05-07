"""화이트리스트 운영자 런타임 토글 — DB 영속 (사용자 요청 2026-05-07).

배경: env 의 ALLOWED_SYMBOLS_CSV 가 있어도 운영자가 UI 체크박스로 .env 재시작
없이 on/off 할 수 있어야 함. system_settings.whitelist_enabled 가 false 면
strategy 진입 시 화이트리스트 가드 skip.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.api.v1.admin import (
    WhitelistSettingUpdate,
    get_whitelist_setting,
    update_whitelist_setting,
)
from app.services.strategy_service import StrategyService
from app.services.system_settings_service import SystemSettingsService


def _patch_binance(monkeypatch):
    class _FakeClient:
        def __init__(self, **kwargs): pass
        def get_account(self):
            return {"availableBalance": "10000", "totalMarginBalance": "10000",
                    "totalMaintMargin": "0", "positions": []}
    monkeypatch.setattr("app.integrations.binance.client.BinanceClient", _FakeClient)
    monkeypatch.setattr("app.core.crypto.decrypt_text", lambda s: s)


class TestSystemSettingsService:
    def test_get_bool_default_when_no_row(self, db_session):
        svc = SystemSettingsService(db_session)
        assert svc.get_bool("nonexistent_key", default=True) is True
        assert svc.get_bool("nonexistent_key", default=False) is False

    def test_set_and_get_bool_true(self, db_session):
        svc = SystemSettingsService(db_session)
        svc.set("test_flag", True)
        assert svc.get_bool("test_flag", default=False) is True

    def test_set_and_get_bool_false(self, db_session):
        svc = SystemSettingsService(db_session)
        svc.set("test_flag", False)
        assert svc.get_bool("test_flag", default=True) is False

    def test_set_overwrites_previous(self, db_session):
        svc = SystemSettingsService(db_session)
        svc.set("test_flag", True)
        svc.set("test_flag", False)
        assert svc.get_bool("test_flag", default=True) is False

    def test_is_whitelist_enabled_uses_default_when_no_row(self, db_session):
        svc = SystemSettingsService(db_session)
        assert svc.is_whitelist_enabled(default_from_env=True) is True
        assert svc.is_whitelist_enabled(default_from_env=False) is False


class TestWhitelistRuntimeToggle:
    def test_toggle_off_bypasses_guard(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, monkeypatch
    ):
        """env 에 BTCUSDT,ETHUSDT 만 허용이지만 DB toggle OFF → SOLUSDT 진입 가능."""
        monkeypatch.setattr(
            "app.core.config.settings.allowed_symbols_csv", "BTCUSDT,ETHUSDT", raising=False
        )
        # 토글 OFF
        SystemSettingsService(db_session).set("whitelist_enabled", False)
        _patch_binance(monkeypatch)

        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("SOLUSDT")
        tpl = make_template()

        # 화이트리스트 OFF — SOLUSDT 도 통과
        instance = StrategyService(db_session).create_strategy_instance(
            user_id=u.id, exchange_account_id=ea.id,
            strategy_template_id=tpl.id, symbol="SOLUSDT",
            side="SHORT", start_price=Decimal("5000"),
        )
        assert instance.id > 0

    def test_toggle_on_enforces_guard(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, monkeypatch
    ):
        """env 에 BTCUSDT,ETHUSDT + DB toggle ON → SOLUSDT 거부."""
        monkeypatch.setattr(
            "app.core.config.settings.allowed_symbols_csv", "BTCUSDT,ETHUSDT", raising=False
        )
        SystemSettingsService(db_session).set("whitelist_enabled", True)
        _patch_binance(monkeypatch)

        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("SOLUSDT")
        tpl = make_template()

        with pytest.raises(ValueError, match="허용 목록에 없음"):
            StrategyService(db_session).create_strategy_instance(
                user_id=u.id, exchange_account_id=ea.id,
                strategy_template_id=tpl.id, symbol="SOLUSDT",
                side="SHORT", start_price=Decimal("5000"),
            )

    def test_default_on_when_env_set_no_db_row(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, monkeypatch
    ):
        """DB toggle row 없으면 default = (env 에 값 있음 = True). SOLUSDT 거부."""
        monkeypatch.setattr(
            "app.core.config.settings.allowed_symbols_csv", "BTCUSDT,ETHUSDT", raising=False
        )
        # DB 에 row 없음 (default ON)
        _patch_binance(monkeypatch)

        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("SOLUSDT")
        tpl = make_template()

        with pytest.raises(ValueError, match="허용 목록에 없음"):
            StrategyService(db_session).create_strategy_instance(
                user_id=u.id, exchange_account_id=ea.id,
                strategy_template_id=tpl.id, symbol="SOLUSDT",
                side="SHORT", start_price=Decimal("5000"),
            )

    def test_env_empty_no_guard_regardless_of_toggle(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, monkeypatch
    ):
        """env 가 비어있으면 toggle ON 이어도 가드 무의미 (allowed_symbols_set is None)."""
        monkeypatch.setattr(
            "app.core.config.settings.allowed_symbols_csv", None, raising=False
        )
        SystemSettingsService(db_session).set("whitelist_enabled", True)
        _patch_binance(monkeypatch)

        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("DOGEUSDT")
        tpl = make_template()

        instance = StrategyService(db_session).create_strategy_instance(
            user_id=u.id, exchange_account_id=ea.id,
            strategy_template_id=tpl.id, symbol="DOGEUSDT",
            side="SHORT", start_price=Decimal("5000"),
        )
        assert instance.id > 0


class TestAdminEndpoint:
    def test_get_whitelist_default_state(self, db_session, make_user, monkeypatch):
        """env 미설정 + DB 없음 → enabled=False, env_configured=False."""
        monkeypatch.setattr("app.core.config.settings.allowed_symbols_csv", None, raising=False)
        u = make_user()
        resp = get_whitelist_setting(db=db_session, user_id=u.id)
        assert resp.enabled is False
        assert resp.env_configured is False
        assert resp.allowed_symbols == []

    def test_get_whitelist_env_configured_default_on(self, db_session, make_user, monkeypatch):
        """env 설정 + DB 없음 → enabled=True (default ON), allowed 표시."""
        monkeypatch.setattr(
            "app.core.config.settings.allowed_symbols_csv", "BTCUSDT,ETHUSDT", raising=False
        )
        u = make_user()
        resp = get_whitelist_setting(db=db_session, user_id=u.id)
        assert resp.enabled is True
        assert resp.env_configured is True
        assert resp.allowed_symbols == ["BTCUSDT", "ETHUSDT"]

    def test_patch_whitelist_to_off(self, db_session, make_user, monkeypatch):
        monkeypatch.setattr(
            "app.core.config.settings.allowed_symbols_csv", "BTCUSDT", raising=False
        )
        u = make_user()
        resp = update_whitelist_setting(
            payload=WhitelistSettingUpdate(enabled=False),
            db=db_session, user_id=u.id,
        )
        assert resp.enabled is False
        # DB row 영속 확인
        assert SystemSettingsService(db_session).get_bool("whitelist_enabled", default=True) is False

    def test_patch_whitelist_to_on_then_off(self, db_session, make_user, monkeypatch):
        monkeypatch.setattr(
            "app.core.config.settings.allowed_symbols_csv", "BTCUSDT", raising=False
        )
        u = make_user()
        update_whitelist_setting(
            payload=WhitelistSettingUpdate(enabled=True), db=db_session, user_id=u.id,
        )
        assert SystemSettingsService(db_session).get_bool("whitelist_enabled", default=False) is True

        update_whitelist_setting(
            payload=WhitelistSettingUpdate(enabled=False), db=db_session, user_id=u.id,
        )
        assert SystemSettingsService(db_session).get_bool("whitelist_enabled", default=True) is False
