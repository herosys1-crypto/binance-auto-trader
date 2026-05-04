"""daily_loss_aggregator — 일일 손실 한도 발동 통합 테스트.

audit 발견 (2026-05-04): AccountDailyLossLimiterService.update_pnl_and_check 가
호출되는 곳 0건 → 일일 손실 한도 안전장치 무력 상태.
이번 fix: daily_loss_aggregator worker 추가, 매 1분 스케줄.

이 테스트는 다음을 보장:
- settings.daily_loss_limit_usdt 미설정 시 no-op
- unrealized 합산이 한도 초과하면 kill-switch 발동 + Sentry capture
- 한도 미달 시 동작 안 함
- 이미 kill-switch 활성인 계정은 skip
- PENDING (포지션 없음) strategy 는 합산에서 제외
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.account_daily_risk_limit import AccountDailyRiskLimit
from app.models.account_kill_switch import AccountKillSwitch
from app.workers import daily_loss_aggregator as agg


@pytest.fixture
def patched_agg_session(monkeypatch, engine):
    """daily_loss_aggregator 가 만드는 SessionLocal 도 test engine 사용."""
    from sqlalchemy.orm import sessionmaker
    test_session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    monkeypatch.setattr("app.workers.daily_loss_aggregator.SessionLocal", test_session_factory)
    return test_session_factory


@pytest.fixture
def with_limit_50(monkeypatch):
    """settings.daily_loss_limit_usdt = 50 으로 설정."""
    monkeypatch.setattr("app.core.config.settings.daily_loss_limit_usdt", 50.0, raising=False)


# ============================================================================
# 기능 비활성 (settings 미설정)
# ============================================================================
class TestFeatureDisabledByDefault:
    def test_no_setting_means_noop(
        self,
        db_session,
        make_strategy,
        patched_agg_session,
        monkeypatch,
    ) -> None:
        """settings.daily_loss_limit_usdt = None → 한도 row / kill-switch 둘 다 미생성."""
        monkeypatch.setattr("app.core.config.settings.daily_loss_limit_usdt", None, raising=False)
        # 큰 unrealized 손실 strategy 가 있어도 무시
        make_strategy(
            symbol_str="BTCUSDT", side="SHORT",
            status="STAGE2_OPEN", current_position_qty=Decimal("-0.5"),
            unrealized_pnl=Decimal("-1000"),  # 큰 손실
        )

        agg.run_daily_loss_check_once()

        # account_daily_risk_limits 미생성
        rows = db_session.execute(select(AccountDailyRiskLimit)).scalars().all()
        assert len(rows) == 0
        # kill-switch 미발동
        ks = db_session.execute(select(AccountKillSwitch)).scalar_one_or_none()
        assert ks is None

    def test_zero_setting_means_noop(
        self,
        db_session,
        make_strategy,
        patched_agg_session,
        monkeypatch,
    ) -> None:
        """settings.daily_loss_limit_usdt = 0 도 비활성 (방어적)."""
        monkeypatch.setattr("app.core.config.settings.daily_loss_limit_usdt", 0.0, raising=False)
        make_strategy(
            symbol_str="BTCUSDT", side="SHORT",
            status="STAGE2_OPEN", current_position_qty=Decimal("-0.5"),
            unrealized_pnl=Decimal("-1000"),
        )

        agg.run_daily_loss_check_once()

        rows = db_session.execute(select(AccountDailyRiskLimit)).scalars().all()
        assert len(rows) == 0


# ============================================================================
# 한도 초과 시 kill-switch 발동
# ============================================================================
class TestBreachTriggersKillSwitch:
    def test_unrealized_exceeds_limit_triggers_kill_switch(
        self,
        db_session,
        make_strategy,
        with_limit_50,
        patched_agg_session,
    ) -> None:
        """unrealized 합산이 -50 USDT 초과 → kill-switch 자동 발동."""
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT",
            status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
            unrealized_pnl=Decimal("-60"),  # -60 < -50 한도
        )

        agg.run_daily_loss_check_once()

        # kill-switch 자동 발동
        ks = db_session.execute(
            select(AccountKillSwitch).where(
                AccountKillSwitch.exchange_account_id == strategy.exchange_account_id
            )
        ).scalar_one_or_none()
        assert ks is not None
        assert ks.is_enabled is True
        assert ks.reason_code == "DAILY_LOSS_LIMIT"

        # account_daily_risk_limit row 생성 + status TRIGGERED
        limit_row = db_session.execute(
            select(AccountDailyRiskLimit).where(
                AccountDailyRiskLimit.exchange_account_id == strategy.exchange_account_id
            )
        ).scalar_one_or_none()
        assert limit_row is not None
        assert limit_row.status == "TRIGGERED"
        assert limit_row.unrealized_pnl_snapshot == Decimal("-60")

    def test_unrealized_summed_across_multiple_strategies(
        self,
        db_session,
        make_user,
        make_exchange_account,
        make_symbol,
        make_template,
        make_strategy,
        with_limit_50,
        patched_agg_session,
    ) -> None:
        """같은 계정의 여러 strategy 의 unrealized 합산 → 합산이 한도 초과 시 발동."""
        u = make_user()
        ea = make_exchange_account(user=u)
        tpl = make_template()

        # 각각 -25 → 합 -50, 한도 -50 = 정확히 경계
        s1 = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN",
            current_position_qty=Decimal("-0.5"), unrealized_pnl=Decimal("-25"),
            user=u, exchange_account=ea, template=tpl,
        )
        # 다른 심볼이라 add 할 수 있음
        sym2 = make_symbol("ETHUSDT")
        s2 = make_strategy(
            symbol_str="ETHUSDT", side="LONG", status="STAGE1_OPEN",
            current_position_qty=Decimal("0.5"), unrealized_pnl=Decimal("-30"),
            user=u, exchange_account=ea, symbol_obj=sym2, template=tpl,
        )

        agg.run_daily_loss_check_once()

        # 합 -55 < -50 → 발동
        ks = db_session.execute(
            select(AccountKillSwitch).where(
                AccountKillSwitch.exchange_account_id == ea.id
            )
        ).scalar_one_or_none()
        assert ks is not None and ks.is_enabled


# ============================================================================
# 한도 미달 — 발동 안 함
# ============================================================================
class TestNoBreachLeavesKillSwitchOff:
    def test_under_limit_no_trigger(
        self,
        db_session,
        make_strategy,
        with_limit_50,
        patched_agg_session,
    ) -> None:
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
            unrealized_pnl=Decimal("-30"),  # 한도 미달
        )

        agg.run_daily_loss_check_once()

        ks = db_session.execute(
            select(AccountKillSwitch).where(
                AccountKillSwitch.exchange_account_id == strategy.exchange_account_id
            )
        ).scalar_one_or_none()
        assert ks is None

        # row 는 만들어짐 (한도 추적용) 하지만 status=ACTIVE
        limit_row = db_session.execute(select(AccountDailyRiskLimit)).scalar_one_or_none()
        assert limit_row is not None
        assert limit_row.status == "ACTIVE"

    def test_positive_pnl_no_trigger(
        self,
        db_session,
        make_strategy,
        with_limit_50,
        patched_agg_session,
    ) -> None:
        """unrealized 가 양수 (이익) 면 당연히 발동 안 함."""
        make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
            unrealized_pnl=Decimal("+100"),
        )

        agg.run_daily_loss_check_once()

        ks = db_session.execute(select(AccountKillSwitch)).scalar_one_or_none()
        assert ks is None


# ============================================================================
# 이미 kill-switch 활성인 계정은 skip (중복 alert 방지)
# ============================================================================
class TestSkipsIfKillSwitchAlreadyEnabled:
    def test_existing_kill_switch_skipped(
        self,
        db_session,
        make_strategy,
        with_limit_50,
        patched_agg_session,
    ) -> None:
        """수동으로 kill-switch 활성화한 계정은 daily check 가 skip — 새 row 안 만듦."""
        from datetime import datetime, timezone
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
            unrealized_pnl=Decimal("-100"),
        )
        # 미리 kill-switch 활성화
        ks = AccountKillSwitch(
            exchange_account_id=strategy.exchange_account_id,
            is_enabled=True, reason_code="MANUAL", reason_message="manual test",
            triggered_at=datetime.now(timezone.utc),
        )
        db_session.add(ks)
        db_session.commit()

        agg.run_daily_loss_check_once()

        # account_daily_risk_limit row 안 만들어짐 (skip 됨)
        rows = db_session.execute(select(AccountDailyRiskLimit)).scalars().all()
        assert len(rows) == 0


# ============================================================================
# PENDING / 종료 status 는 합산 제외
# ============================================================================
class TestExcludesNonPositionStatuses:
    def test_pending_strategies_not_in_sum(
        self,
        db_session,
        make_user,
        make_exchange_account,
        make_template,
        make_strategy,
        with_limit_50,
        patched_agg_session,
    ) -> None:
        """STAGE1_OPEN_PENDING (LIMIT 미체결, 포지션 0) 은 합산 제외."""
        u = make_user()
        ea = make_exchange_account(user=u)
        tpl = make_template()
        # PENDING 전략 — unrealized -100 라고 잘못 기록됐어도 합산 제외돼야 함
        make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN_PENDING",
            current_position_qty=Decimal("0"),  # 미체결
            unrealized_pnl=Decimal("-100"),
            user=u, exchange_account=ea, template=tpl,
        )

        agg.run_daily_loss_check_once()

        # kill-switch 미발동 (PENDING 은 합산 제외)
        ks = db_session.execute(select(AccountKillSwitch)).scalar_one_or_none()
        assert ks is None

    def test_completed_strategies_not_in_sum(
        self,
        db_session,
        make_strategy,
        with_limit_50,
        patched_agg_session,
    ) -> None:
        """COMPLETED 도 합산 제외 (이미 종료, 미실현 잔재 무관)."""
        make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="COMPLETED",
            current_position_qty=Decimal("0"),
            unrealized_pnl=Decimal("-100"),
        )

        agg.run_daily_loss_check_once()

        ks = db_session.execute(select(AccountKillSwitch)).scalar_one_or_none()
        assert ks is None


# ============================================================================
# Sentry capture 검증
# ============================================================================
class TestSentryCaptureOnBreach:
    def test_breach_calls_sentry_capture_with_fatal_level(
        self,
        db_session,
        make_strategy,
        with_limit_50,
        patched_agg_session,
        monkeypatch,
    ) -> None:
        captured: list[dict] = []

        def _spy(message, **kwargs):
            captured.append({"message": message, **kwargs})

        monkeypatch.setattr(agg, "capture_strategy_event", _spy)

        make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
            unrealized_pnl=Decimal("-60"),
        )
        agg.run_daily_loss_check_once()

        assert len(captured) == 1
        evt = captured[0]
        assert "Daily loss limit breached" in evt["message"]
        assert evt.get("level") == "fatal"
        assert evt.get("tags", {}).get("event_type") == "DAILY_LOSS_LIMIT_BREACHED"
        assert "limit" in evt.get("extras", {})
