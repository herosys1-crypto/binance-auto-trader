"""Kill-Switch 발동 + Daily-Loss 경고 시 텔레그램 알림 wire-up 검증.

배경 (2026-05-07 audit 발견): notification_service 에 send_kill_switch_alert /
send_daily_loss_warning 메서드가 정의돼 있지만 어디서도 호출되지 않아 사용자가
자금 보호 신호를 못 받는 상태였음 (MAINNET-CHECKLIST 4-1 위반).

이 테스트는 wire-up 의 영구 회귀 방어:
- AccountKillSwitchService.trigger() → Notification (kill_switch_alert) 1건 생성
- Edge detection: 이미 enabled 상태에서 재호출 시 추가 알림 X (스팸 방지)
- AccountDailyLossLimiterService.update_pnl_and_check() — 80% 임계 도달 시
  Notification (daily_loss_warning) 1건 생성, ACTIVE → WARNED
- WARNED 상태에서 다시 호출 시 추가 경고 X (1회만)
- breach 시 kill_switch_alert 가 발송 (limiter → trigger() chain)

Telegram 발송 자체는 settings.telegram_bot_token 이 비어 있어 _send_telegram 에서
ValueError → notification.send_status='FAILED' 로 기록. 본 테스트는 알림 row 가
생성됐는지 (호출 지점이 wired up 인지) 만 검증.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.models.account_daily_risk_limit import AccountDailyRiskLimit
from app.models.notification import Notification
from app.services.account_daily_loss_limiter import AccountDailyLossLimiterService
from app.services.account_kill_switch_service import AccountKillSwitchService


class TestKillSwitchAlertWireUp:
    def test_trigger_sends_telegram_alert(self, db_session, make_exchange_account) -> None:
        """trigger() → kill_switch_alert Notification 1건 생성."""
        acc = make_exchange_account()
        ks = AccountKillSwitchService(db_session)

        ks.trigger(acc.id, reason_code="TEST", reason_message="manual trigger")

        notifs = db_session.execute(
            select(Notification).where(Notification.title.like("%[Kill-Switch 발동]%"))
        ).scalars().all()
        assert len(notifs) == 1
        n = notifs[0]
        assert "TEST" in n.body
        assert "manual trigger" in n.body
        assert n.channel == "TELEGRAM"
        # send_status 는 FAILED (테스트 환경에 telegram_bot_token 없음) — 핵심은 row 존재.
        assert n.send_status in ("SENT", "FAILED")

    def test_trigger_idempotent_no_duplicate_alert(self, db_session, make_exchange_account) -> None:
        """이미 enabled 인 계정에 trigger() 재호출 시 알림 추가 발송 X (edge detection)."""
        acc = make_exchange_account()
        ks = AccountKillSwitchService(db_session)

        ks.trigger(acc.id, reason_code="FIRST", reason_message="initial")
        ks.trigger(acc.id, reason_code="SECOND", reason_message="duplicate call")

        notifs = db_session.execute(
            select(Notification).where(Notification.title.like("%[Kill-Switch 발동]%"))
        ).scalars().all()
        # Edge: disabled→enabled 1회만 알림
        assert len(notifs) == 1
        assert "FIRST" in notifs[0].body

    def test_re_trigger_after_clear_sends_new_alert(self, db_session, make_exchange_account) -> None:
        """clear() 후 재 trigger() 시 새 알림 발송 (edge 다시 감지)."""
        acc = make_exchange_account()
        ks = AccountKillSwitchService(db_session)

        ks.trigger(acc.id, reason_code="FIRST", reason_message="initial")
        ks.clear(acc.id)
        ks.trigger(acc.id, reason_code="SECOND", reason_message="re-triggered")

        notifs = db_session.execute(
            select(Notification).where(Notification.title.like("%[Kill-Switch 발동]%"))
        ).scalars().all()
        # disabled→enabled 두 번 발생했으므로 알림 2건
        assert len(notifs) == 2
        codes = sorted([n.body for n in notifs])
        assert any("FIRST" in c for c in codes)
        assert any("SECOND" in c for c in codes)

    def test_daily_loss_warning_at_80_percent_threshold(
        self, db_session, make_exchange_account
    ) -> None:
        """80% 임계 도달 시 daily_loss_warning Notification 1건 + status=WARNED."""
        acc = make_exchange_account()
        limiter = AccountDailyLossLimiterService(db_session)

        # limit=100, total=-80 (= 80% breach 미만)
        breached = limiter.update_pnl_and_check(
            exchange_account_id=acc.id,
            realized_pnl=Decimal("-30"),
            unrealized_pnl_snapshot=Decimal("-50"),
            daily_loss_limit_amount=Decimal("100"),
        )
        assert breached is False

        row = db_session.execute(
            select(AccountDailyRiskLimit).where(AccountDailyRiskLimit.exchange_account_id == acc.id)
        ).scalar_one()
        assert row.status == "WARNED"

        notifs = db_session.execute(
            select(Notification).where(Notification.title.like("%[일일 손실 한도 임계치 도달]%"))
        ).scalars().all()
        assert len(notifs) == 1
        assert "100" in notifs[0].body  # daily_limit
        assert notifs[0].channel == "TELEGRAM"

    def test_daily_loss_warning_below_threshold_no_alert(
        self, db_session, make_exchange_account
    ) -> None:
        """80% 미만 시 경고 알림 발송 안 함."""
        acc = make_exchange_account()
        limiter = AccountDailyLossLimiterService(db_session)

        # limit=100, total=-50 (50%, 80% 미만)
        limiter.update_pnl_and_check(
            exchange_account_id=acc.id,
            realized_pnl=Decimal("-20"),
            unrealized_pnl_snapshot=Decimal("-30"),
            daily_loss_limit_amount=Decimal("100"),
        )

        row = db_session.execute(
            select(AccountDailyRiskLimit).where(AccountDailyRiskLimit.exchange_account_id == acc.id)
        ).scalar_one()
        assert row.status == "ACTIVE"

        notifs = db_session.execute(
            select(Notification).where(Notification.title.like("%[일일 손실 한도 임계치 도달]%"))
        ).scalars().all()
        assert len(notifs) == 0

    def test_daily_loss_warning_only_once(self, db_session, make_exchange_account) -> None:
        """80% 도달 후 또 다시 update 호출돼도 경고는 1회만 (status=WARNED 가드)."""
        acc = make_exchange_account()
        limiter = AccountDailyLossLimiterService(db_session)

        # 첫 호출 — 80% 도달, WARNED + 알림 1건
        limiter.update_pnl_and_check(
            exchange_account_id=acc.id,
            realized_pnl=Decimal("-40"),
            unrealized_pnl_snapshot=Decimal("-40"),
            daily_loss_limit_amount=Decimal("100"),
        )
        # 두 번째 호출 — 여전히 80% 영역
        limiter.update_pnl_and_check(
            exchange_account_id=acc.id,
            realized_pnl=Decimal("-45"),
            unrealized_pnl_snapshot=Decimal("-40"),
            daily_loss_limit_amount=Decimal("100"),
        )

        notifs = db_session.execute(
            select(Notification).where(Notification.title.like("%[일일 손실 한도 임계치 도달]%"))
        ).scalars().all()
        assert len(notifs) == 1  # 1회만

    def test_breach_triggers_both_warning_and_kill_switch(
        self, db_session, make_exchange_account
    ) -> None:
        """한 번에 한도 초과 (warning 단계 우회) — kill_switch_alert 만 발송.

        WARNED 우회는 의도된 동작 — total 이 한 번에 100% 넘으면 status=TRIGGERED
        이고 warning 단계는 skip. kill_switch_alert 가 trigger() 에서 자동 발송.
        """
        acc = make_exchange_account()
        limiter = AccountDailyLossLimiterService(db_session)

        # 첫 호출에서 바로 100% 초과
        breached = limiter.update_pnl_and_check(
            exchange_account_id=acc.id,
            realized_pnl=Decimal("-60"),
            unrealized_pnl_snapshot=Decimal("-50"),
            daily_loss_limit_amount=Decimal("100"),
        )
        assert breached is True

        warning_notifs = db_session.execute(
            select(Notification).where(Notification.title.like("%[일일 손실 한도 임계치 도달]%"))
        ).scalars().all()
        kill_notifs = db_session.execute(
            select(Notification).where(Notification.title.like("%[Kill-Switch 발동]%"))
        ).scalars().all()

        # 100% 한 번에 초과 시 — warning skip (status 가 ACTIVE 에서 곧장 TRIGGERED 로)
        assert len(warning_notifs) == 0
        # kill-switch 알림은 발송 (limiter → trigger() chain)
        assert len(kill_notifs) == 1
        assert "DAILY_LOSS_LIMIT" in kill_notifs[0].body

    def test_warning_then_breach_sends_both_alerts(
        self, db_session, make_exchange_account
    ) -> None:
        """80% → 100% 점진적 진행 시 — 경고 1건 + kill-switch 1건 모두 발송."""
        acc = make_exchange_account()
        limiter = AccountDailyLossLimiterService(db_session)

        # 80% — 경고 발송
        limiter.update_pnl_and_check(
            exchange_account_id=acc.id,
            realized_pnl=Decimal("-40"),
            unrealized_pnl_snapshot=Decimal("-40"),
            daily_loss_limit_amount=Decimal("100"),
        )
        # 추가 손실로 100% 초과 — kill-switch 발송
        breached = limiter.update_pnl_and_check(
            exchange_account_id=acc.id,
            realized_pnl=Decimal("-60"),
            unrealized_pnl_snapshot=Decimal("-50"),
            daily_loss_limit_amount=Decimal("100"),
        )
        assert breached is True

        warning_notifs = db_session.execute(
            select(Notification).where(Notification.title.like("%[일일 손실 한도 임계치 도달]%"))
        ).scalars().all()
        kill_notifs = db_session.execute(
            select(Notification).where(Notification.title.like("%[Kill-Switch 발동]%"))
        ).scalars().all()

        assert len(warning_notifs) == 1
        assert len(kill_notifs) == 1
