"""disable_kill_switch endpoint 가 daily_risk_limit row 도 ACTIVE 로 리셋.

배경 (2026-05-07 사용자 VPS testnet 운영 발견):
update_pnl_and_check 의 가드 `if breached and row.status != "TRIGGERED"` 때문에,
KS 만 clear 하고 row.status 가 TRIGGERED 로 남아있으면 손실이 더 커져도
KS 가 재발동하지 않는 latent 버그가 있었음.

이 테스트는 disable_kill_switch endpoint 가 row 도 함께 리셋해서
다음 aggregator 사이클이 정상 검사 가능한지 보장.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.api.v1.admin import disable_kill_switch
from app.models.account_daily_risk_limit import AccountDailyRiskLimit
from app.models.account_kill_switch import AccountKillSwitch


class TestDisableResetsRow:
    def test_disable_resets_triggered_row_to_active(
        self, db_session, make_user, make_exchange_account
    ) -> None:
        """KS 활성 + row.status=TRIGGERED → disable 시 row.status=ACTIVE."""
        u = make_user()
        ea = make_exchange_account(user=u)

        ks = AccountKillSwitch(
            exchange_account_id=ea.id, is_enabled=True,
            reason_code="DAILY_LOSS_LIMIT", reason_message="test",
            triggered_at=datetime.now(timezone.utc),
        )
        row = AccountDailyRiskLimit(
            exchange_account_id=ea.id, trading_date=date.today(),
            daily_loss_limit_amount=Decimal("100"),
            realized_pnl=Decimal("0"), unrealized_pnl_snapshot=Decimal("-200"),
            status="TRIGGERED",
        )
        db_session.add_all([ks, row])
        db_session.commit()

        disable_kill_switch(exchange_account_id=ea.id, db=db_session, user_id=u.id)

        db_session.refresh(ks)
        db_session.refresh(row)
        assert ks.is_enabled is False
        assert row.status == "ACTIVE"  # 리셋됨

    def test_disable_preserves_warned_status(
        self, db_session, make_user, make_exchange_account
    ) -> None:
        """row.status='WARNED' (80% 임계) 상태는 그대로 보존 — TRIGGERED 만 ACTIVE 로."""
        u = make_user()
        ea = make_exchange_account(user=u)

        ks = AccountKillSwitch(
            exchange_account_id=ea.id, is_enabled=True,
            reason_code="MANUAL", reason_message="manual",
            triggered_at=datetime.now(timezone.utc),
        )
        row = AccountDailyRiskLimit(
            exchange_account_id=ea.id, trading_date=date.today(),
            daily_loss_limit_amount=Decimal("100"),
            realized_pnl=Decimal("0"), unrealized_pnl_snapshot=Decimal("-85"),
            status="WARNED",
        )
        db_session.add_all([ks, row])
        db_session.commit()

        disable_kill_switch(exchange_account_id=ea.id, db=db_session, user_id=u.id)

        db_session.refresh(row)
        # WARNED 는 보존 — 사용자가 인지한 임계 상태이므로 ACTIVE 로 강등 X
        assert row.status == "WARNED"

    def test_disable_no_row_today_no_error(
        self, db_session, make_user, make_exchange_account
    ) -> None:
        """오늘 row 가 없어도 KS clear 정상 — row 없으면 skip."""
        u = make_user()
        ea = make_exchange_account(user=u)
        ks = AccountKillSwitch(
            exchange_account_id=ea.id, is_enabled=True,
            reason_code="MANUAL", reason_message="early-day",
            triggered_at=datetime.now(timezone.utc),
        )
        db_session.add(ks)
        db_session.commit()

        # row 없는 상태에서도 에러 없이 처리
        disable_kill_switch(exchange_account_id=ea.id, db=db_session, user_id=u.id)
        db_session.refresh(ks)
        assert ks.is_enabled is False

    def test_disable_then_aggregator_reevaluates(
        self, db_session, make_user, make_exchange_account
    ) -> None:
        """disable 후 limiter.update_pnl_and_check 재호출 시 정상 재평가.

        이전 버그: row.status=TRIGGERED 라 재평가 시 trigger 가드에 걸려 KS 재발동 X.
        Fix 후: row.status=ACTIVE 로 리셋되므로 breach 시 다시 트리거 가능.
        """
        from app.services.account_daily_loss_limiter import AccountDailyLossLimiterService

        u = make_user()
        ea = make_exchange_account(user=u)
        ks = AccountKillSwitch(
            exchange_account_id=ea.id, is_enabled=True,
            reason_code="DAILY_LOSS_LIMIT", reason_message="prev-breach",
            triggered_at=datetime.now(timezone.utc),
        )
        row = AccountDailyRiskLimit(
            exchange_account_id=ea.id, trading_date=date.today(),
            daily_loss_limit_amount=Decimal("100"),
            realized_pnl=Decimal("0"), unrealized_pnl_snapshot=Decimal("-200"),
            status="TRIGGERED",
        )
        db_session.add_all([ks, row])
        db_session.commit()

        disable_kill_switch(exchange_account_id=ea.id, db=db_session, user_id=u.id)
        db_session.refresh(row)
        assert row.status == "ACTIVE"  # 핵심 — 재평가 가능 상태

        # 다시 손실로 breach 시 정상 재발동
        limiter = AccountDailyLossLimiterService(db_session)
        breached = limiter.update_pnl_and_check(
            exchange_account_id=ea.id,
            realized_pnl=Decimal("0"),
            unrealized_pnl_snapshot=Decimal("-150"),
            daily_loss_limit_amount=Decimal("100"),
        )
        assert breached is True

        # KS 다시 활성화
        ks_after = db_session.execute(
            select(AccountKillSwitch).where(
                AccountKillSwitch.exchange_account_id == ea.id
            )
        ).scalar_one()
        assert ks_after.is_enabled is True
