"""v2 — realized_pnl 일일 누적 + EOD aggregator integration.

audit v1 (016b678) 한계: daily_loss_aggregator 가 unrealized 만 합산.
realized 는 account_daily_risk_limit row 값 그대로 (누적 안 됨) → 청산된 손실
가 일일 한도 계산에 빠짐.

v2 fix:
- AccountDailyLossLimiterService.add_realized_delta — 오늘 row 의 realized_pnl
  에 incremental delta 추가
- stream_service.handle_order_trade_update 의 EXIT FILLED 핸들링 후 호출

이 테스트는:
1. add_realized_delta 자체 동작 (없으면 row 생성, 있으면 누적)
2. 여러 EXIT 가 같은 날에 누적되는 것
3. aggregator 가 누적된 realized 를 보고 breach 판정 (realized + unrealized)
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.account_daily_risk_limit import AccountDailyRiskLimit
from app.models.account_kill_switch import AccountKillSwitch
from app.services.account_daily_loss_limiter import AccountDailyLossLimiterService
from app.workers import daily_loss_aggregator as agg


@pytest.fixture
def patched_agg_session(monkeypatch, engine):
    from sqlalchemy.orm import sessionmaker
    test_session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    monkeypatch.setattr("app.workers.daily_loss_aggregator.SessionLocal", test_session_factory)
    return test_session_factory


@pytest.fixture
def with_limit_50(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.daily_loss_limit_usdt", 50.0, raising=False)


# ============================================================================
# add_realized_delta 단위 동작
# ============================================================================
class TestAddRealizedDelta:
    def test_first_call_creates_row_with_delta(
        self,
        db_session,
        make_exchange_account,
    ) -> None:
        ea = make_exchange_account()
        svc = AccountDailyLossLimiterService(db_session)

        svc.add_realized_delta(
            exchange_account_id=ea.id,
            realized_delta=Decimal("-15.5"),
        )
        db_session.commit()

        row = db_session.execute(
            select(AccountDailyRiskLimit).where(
                AccountDailyRiskLimit.exchange_account_id == ea.id
            )
        ).scalar_one()
        assert row.realized_pnl == Decimal("-15.50000000")
        assert row.trading_date == date.today()
        # 한도는 placeholder 0 (aggregator 가 sync 함)
        assert row.daily_loss_limit_amount == Decimal("0")

    def test_subsequent_calls_accumulate(
        self,
        db_session,
        make_exchange_account,
    ) -> None:
        ea = make_exchange_account()
        svc = AccountDailyLossLimiterService(db_session)

        svc.add_realized_delta(exchange_account_id=ea.id, realized_delta=Decimal("-10"))
        svc.add_realized_delta(exchange_account_id=ea.id, realized_delta=Decimal("-5.5"))
        svc.add_realized_delta(exchange_account_id=ea.id, realized_delta=Decimal("+3"))
        db_session.commit()

        row = db_session.execute(
            select(AccountDailyRiskLimit).where(
                AccountDailyRiskLimit.exchange_account_id == ea.id
            )
        ).scalar_one()
        assert row.realized_pnl == Decimal("-12.50000000")  # -10 + -5.5 + 3

    def test_separate_accounts_separate_rows(
        self,
        db_session,
        make_user,
        make_exchange_account,
    ) -> None:
        u = make_user()
        ea1 = make_exchange_account(user=u)
        ea2 = make_exchange_account(user=u, api_key_enc="enc2")
        svc = AccountDailyLossLimiterService(db_session)

        svc.add_realized_delta(exchange_account_id=ea1.id, realized_delta=Decimal("-10"))
        svc.add_realized_delta(exchange_account_id=ea2.id, realized_delta=Decimal("-20"))
        db_session.commit()

        rows = db_session.execute(select(AccountDailyRiskLimit).order_by(AccountDailyRiskLimit.exchange_account_id)).scalars().all()
        assert len(rows) == 2
        assert {r.exchange_account_id: r.realized_pnl for r in rows} == {
            ea1.id: Decimal("-10"),
            ea2.id: Decimal("-20"),
        }


# ============================================================================
# get_or_create_today_limit 의 한도 sync
# ============================================================================
class TestGetOrCreateLimitSyncs:
    def test_existing_row_with_diff_limit_gets_updated(
        self,
        db_session,
        make_exchange_account,
    ) -> None:
        """stream_service 가 placeholder 0 으로 row 만든 후 aggregator 가 50 으로 sync."""
        ea = make_exchange_account()
        svc = AccountDailyLossLimiterService(db_session)
        # stream_service 시나리오 — placeholder 0
        svc.add_realized_delta(exchange_account_id=ea.id, realized_delta=Decimal("-5"))
        db_session.commit()

        # aggregator 가 limit=50 으로 호출
        row = svc.get_or_create_today_limit(
            exchange_account_id=ea.id,
            daily_loss_limit_amount=Decimal("50"),
        )
        assert row.daily_loss_limit_amount == Decimal("50")
        # realized 는 보존
        assert row.realized_pnl == Decimal("-5.00000000")


# ============================================================================
# aggregator + realized 누적 → breach 통합
# ============================================================================
class TestAggregatorWithRealizedAccumulated:
    def test_breach_via_realized_alone(
        self,
        db_session,
        make_strategy,
        make_exchange_account,
        with_limit_50,
        patched_agg_session,
    ) -> None:
        """unrealized 0 인데 누적된 realized 만으로 한도 초과 → kill-switch."""
        # 활성 strategy 없이 ExchangeAccount 만 있고 realized 누적된 케이스
        # (예: 오늘 손실 -60 청산 후 새 진입 안 함)
        ea = make_exchange_account()
        svc = AccountDailyLossLimiterService(db_session)
        svc.add_realized_delta(exchange_account_id=ea.id, realized_delta=Decimal("-60"))
        db_session.commit()

        agg.run_daily_loss_check_once()

        ks = db_session.execute(
            select(AccountKillSwitch).where(AccountKillSwitch.exchange_account_id == ea.id)
        ).scalar_one_or_none()
        assert ks is not None and ks.is_enabled
        assert ks.reason_code == "DAILY_LOSS_LIMIT"

    def test_breach_via_realized_plus_unrealized(
        self,
        db_session,
        make_strategy,
        with_limit_50,
        patched_agg_session,
    ) -> None:
        """realized -30 + unrealized -25 = -55 < -50 한도 → 발동."""
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
            unrealized_pnl=Decimal("-25"),
        )
        # realized 누적 시뮬 (실제로는 stream_service 가 한 것)
        svc = AccountDailyLossLimiterService(db_session)
        svc.add_realized_delta(
            exchange_account_id=strategy.exchange_account_id,
            realized_delta=Decimal("-30"),
        )
        db_session.commit()

        agg.run_daily_loss_check_once()

        ks = db_session.execute(
            select(AccountKillSwitch).where(
                AccountKillSwitch.exchange_account_id == strategy.exchange_account_id
            )
        ).scalar_one_or_none()
        assert ks is not None and ks.is_enabled

    def test_realized_minus_unrealized_below_limit_no_breach(
        self,
        db_session,
        make_strategy,
        with_limit_50,
        patched_agg_session,
    ) -> None:
        """realized -30 + unrealized -10 = -40 → no breach (kill-switch 미발동).

        2026-05-07 wire-up: 80% (= -40) 에 정확히 도달 → row.status='WARNED' 로 전환
        + 텔레그램 경고 발송 (kill-switch 발동 X). "no breach" 의 의미는 kill-switch
        가 발동 안 된다는 것 — WARNED 도 그 조건 만족.
        """
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
            unrealized_pnl=Decimal("-10"),
        )
        svc = AccountDailyLossLimiterService(db_session)
        svc.add_realized_delta(
            exchange_account_id=strategy.exchange_account_id,
            realized_delta=Decimal("-30"),
        )
        db_session.commit()

        agg.run_daily_loss_check_once()

        ks = db_session.execute(select(AccountKillSwitch)).scalar_one_or_none()
        assert ks is None  # kill-switch 미발동 (breach X)
        row = db_session.execute(select(AccountDailyRiskLimit)).scalar_one()
        assert row.status == "WARNED"  # 80% 임계 도달 → 경고 (2026-05-07)
        # realized 는 -30 으로 보존, unrealized 는 갱신
        assert row.realized_pnl == Decimal("-30.00000000")
        assert row.unrealized_pnl_snapshot == Decimal("-10")


# ============================================================================
# 회귀 보장 — 기존 update_pnl_and_check 기능
# ============================================================================
class TestBackwardCompatibility:
    def test_update_pnl_and_check_still_works(
        self,
        db_session,
        make_exchange_account,
    ) -> None:
        """v1 시그니처 유지 — 기존 호출자 (없지만) 안 깨짐."""
        ea = make_exchange_account()
        svc = AccountDailyLossLimiterService(db_session)

        breached = svc.update_pnl_and_check(
            exchange_account_id=ea.id,
            realized_pnl=Decimal("-30"),
            unrealized_pnl_snapshot=Decimal("-25"),
            daily_loss_limit_amount=Decimal("50"),
        )
        assert breached is True

        row = db_session.execute(select(AccountDailyRiskLimit)).scalar_one()
        assert row.status == "TRIGGERED"
        assert row.realized_pnl == Decimal("-30")
        assert row.unrealized_pnl_snapshot == Decimal("-25")
