"""v3 — 계정별 일일 손실 한도 회귀.

배경: v1/v2 가 global env (settings.daily_loss_limit_usdt) 만 지원.
v3 추가: ExchangeAccount.daily_loss_limit_usdt 컬럼 (alembic 0010) 우선 적용.

해석 우선순위:
1. acc.daily_loss_limit_usdt > 0 → 계정 override
2. settings.daily_loss_limit_usdt > 0 → global
3. 둘 다 None/0 → 비활성 (해당 계정 skip)
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.account_kill_switch import AccountKillSwitch
from app.workers import daily_loss_aggregator as agg
from app.workers.daily_loss_aggregator import _resolve_account_limit


@pytest.fixture
def patched_agg_session(monkeypatch, engine):
    from sqlalchemy.orm import sessionmaker
    test_session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    monkeypatch.setattr("app.workers.daily_loss_aggregator.SessionLocal", test_session_factory)
    return test_session_factory


@pytest.fixture
def with_global_50(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.daily_loss_limit_usdt", 50.0, raising=False)


@pytest.fixture
def no_global_limit(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.daily_loss_limit_usdt", None, raising=False)


# ============================================================================
# _resolve_account_limit 단위
# ============================================================================
class TestResolveAccountLimit:
    def test_account_override_wins(
        self, monkeypatch, make_exchange_account
    ) -> None:
        monkeypatch.setattr("app.core.config.settings.daily_loss_limit_usdt", 50.0, raising=False)
        acc = make_exchange_account(daily_loss_limit_usdt=Decimal("100"))
        assert _resolve_account_limit(acc) == Decimal("100")

    def test_falls_back_to_global_when_account_none(
        self, monkeypatch, make_exchange_account
    ) -> None:
        monkeypatch.setattr("app.core.config.settings.daily_loss_limit_usdt", 50.0, raising=False)
        acc = make_exchange_account(daily_loss_limit_usdt=None)
        assert _resolve_account_limit(acc) == Decimal("50.0")

    def test_falls_back_to_global_when_account_zero(
        self, monkeypatch, make_exchange_account
    ) -> None:
        monkeypatch.setattr("app.core.config.settings.daily_loss_limit_usdt", 50.0, raising=False)
        acc = make_exchange_account(daily_loss_limit_usdt=Decimal("0"))
        assert _resolve_account_limit(acc) == Decimal("50.0")

    def test_falls_back_to_global_when_account_negative(
        self, monkeypatch, make_exchange_account
    ) -> None:
        """음수는 비정상 → global 폴백."""
        monkeypatch.setattr("app.core.config.settings.daily_loss_limit_usdt", 50.0, raising=False)
        acc = make_exchange_account(daily_loss_limit_usdt=Decimal("-10"))
        assert _resolve_account_limit(acc) == Decimal("50.0")

    def test_returns_none_when_both_unset(
        self, monkeypatch, make_exchange_account
    ) -> None:
        monkeypatch.setattr("app.core.config.settings.daily_loss_limit_usdt", None, raising=False)
        acc = make_exchange_account(daily_loss_limit_usdt=None)
        assert _resolve_account_limit(acc) is None

    def test_returns_none_when_both_zero(
        self, monkeypatch, make_exchange_account
    ) -> None:
        monkeypatch.setattr("app.core.config.settings.daily_loss_limit_usdt", 0.0, raising=False)
        acc = make_exchange_account(daily_loss_limit_usdt=Decimal("0"))
        assert _resolve_account_limit(acc) is None

    def test_account_only_when_no_global(
        self, monkeypatch, make_exchange_account
    ) -> None:
        """global 없어도 계정 한도만 있으면 동작."""
        monkeypatch.setattr("app.core.config.settings.daily_loss_limit_usdt", None, raising=False)
        acc = make_exchange_account(daily_loss_limit_usdt=Decimal("75"))
        assert _resolve_account_limit(acc) == Decimal("75")


# ============================================================================
# aggregator 통합 — 계정별 다른 한도 적용
# ============================================================================
class TestAggregatorPerAccountLimit:
    def test_account_override_triggers_at_lower_threshold(
        self,
        db_session,
        make_user,
        make_exchange_account,
        make_strategy,
        with_global_50,
        patched_agg_session,
    ) -> None:
        """global=50, 계정 override=20 → unrealized -25 만으로도 발동."""
        u = make_user()
        ea = make_exchange_account(user=u, daily_loss_limit_usdt=Decimal("20"))
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
            unrealized_pnl=Decimal("-25"),  # global 50 미달, 계정 20 초과
            user=u, exchange_account=ea,
        )

        agg.run_daily_loss_check_once()

        ks = db_session.execute(
            select(AccountKillSwitch).where(AccountKillSwitch.exchange_account_id == ea.id)
        ).scalar_one_or_none()
        assert ks is not None and ks.is_enabled

    def test_account_override_higher_than_global_no_trigger(
        self,
        db_session,
        make_user,
        make_exchange_account,
        make_strategy,
        with_global_50,
        patched_agg_session,
    ) -> None:
        """global=50, 계정 override=200 → unrealized -100 도 한도 미달."""
        u = make_user()
        ea = make_exchange_account(user=u, daily_loss_limit_usdt=Decimal("200"))
        make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
            unrealized_pnl=Decimal("-100"),  # global 50 초과지만 계정 200 미달
            user=u, exchange_account=ea,
        )

        agg.run_daily_loss_check_once()

        ks = db_session.execute(
            select(AccountKillSwitch).where(AccountKillSwitch.exchange_account_id == ea.id)
        ).scalar_one_or_none()
        assert ks is None  # 계정 한도가 우선이라 발동 안 함

    def test_no_global_no_account_skips_completely(
        self,
        db_session,
        make_user,
        make_exchange_account,
        make_strategy,
        no_global_limit,
        patched_agg_session,
    ) -> None:
        """global None + 계정 None → 그 계정 skip (row 미생성, kill-switch 미발동)."""
        u = make_user()
        ea = make_exchange_account(user=u, daily_loss_limit_usdt=None)
        make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
            unrealized_pnl=Decimal("-1000"),  # 큰 손실이어도 한도 없으면 무시
            user=u, exchange_account=ea,
        )

        agg.run_daily_loss_check_once()

        ks = db_session.execute(select(AccountKillSwitch)).scalar_one_or_none()
        assert ks is None

    def test_per_account_isolation(
        self,
        db_session,
        make_user,
        make_exchange_account,
        make_symbol,
        make_template,
        make_strategy,
        with_global_50,
        patched_agg_session,
    ) -> None:
        """계정 A (override=10) + 계정 B (override=200) — 각자 다른 한도 적용."""
        u = make_user()
        ea_a = make_exchange_account(user=u, daily_loss_limit_usdt=Decimal("10"))
        ea_b = make_exchange_account(user=u, daily_loss_limit_usdt=Decimal("200"), api_key_enc="enc2")
        sym = make_symbol("BTCUSDT")
        tpl = make_template()

        # 계정 A: -15 unrealized → 한도 10 초과 → 발동
        make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"), unrealized_pnl=Decimal("-15"),
            user=u, exchange_account=ea_a, symbol_obj=sym, template=tpl,
        )
        # 계정 B: -100 unrealized → 한도 200 미달 → 미발동
        make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"), unrealized_pnl=Decimal("-100"),
            user=u, exchange_account=ea_b, symbol_obj=sym, template=tpl,
        )

        agg.run_daily_loss_check_once()

        ks_a = db_session.execute(
            select(AccountKillSwitch).where(AccountKillSwitch.exchange_account_id == ea_a.id)
        ).scalar_one_or_none()
        ks_b = db_session.execute(
            select(AccountKillSwitch).where(AccountKillSwitch.exchange_account_id == ea_b.id)
        ).scalar_one_or_none()
        assert ks_a is not None and ks_a.is_enabled
        assert ks_b is None

    def test_only_account_limit_works_without_global(
        self,
        db_session,
        make_user,
        make_exchange_account,
        make_strategy,
        no_global_limit,
        patched_agg_session,
    ) -> None:
        """global 없어도 계정 한도만 있으면 정상 작동."""
        u = make_user()
        ea = make_exchange_account(user=u, daily_loss_limit_usdt=Decimal("30"))
        make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
            unrealized_pnl=Decimal("-40"),
            user=u, exchange_account=ea,
        )

        agg.run_daily_loss_check_once()

        ks = db_session.execute(
            select(AccountKillSwitch).where(AccountKillSwitch.exchange_account_id == ea.id)
        ).scalar_one_or_none()
        assert ks is not None and ks.is_enabled
