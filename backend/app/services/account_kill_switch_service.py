import logging
from datetime import datetime, timezone
from sqlalchemy import select
from app.models.account_kill_switch import AccountKillSwitch

logger = logging.getLogger(__name__)


class AccountKillSwitchService:
    def __init__(self, db) -> None:
        self.db = db

    def is_enabled(self, exchange_account_id: int) -> bool:
        row = self.db.execute(select(AccountKillSwitch).where(AccountKillSwitch.exchange_account_id == exchange_account_id)).scalar_one_or_none()
        return bool(row and row.is_enabled)

    def trigger(self, exchange_account_id: int, reason_code: str, reason_message: str) -> None:
        """Kill-switch 발동 + 텔레그램 알림 발송.

        2026-05-07 wire-up (audit 발견): 이전엔 DB row 만 변경하고 알림 누락 →
        사용자가 자금 보호 신호를 못 받음 (MAINNET-CHECKLIST 4-1 위반).
        edge detection 으로 이미 enabled 인 상태 재호출 시 알림 안 보냄 (스팸 방지).
        """
        row = self.db.execute(select(AccountKillSwitch).where(AccountKillSwitch.exchange_account_id == exchange_account_id)).scalar_one_or_none()
        was_enabled = bool(row and row.is_enabled)
        if row is None:
            row = AccountKillSwitch(exchange_account_id=exchange_account_id)
            self.db.add(row)
            self.db.flush()
        row.is_enabled = True
        row.reason_code = reason_code
        row.reason_message = reason_message
        row.triggered_at = datetime.now(timezone.utc)
        row.cleared_at = None
        self.db.commit()

        # Edge: disabled → enabled 일 때만 알림 (재호출 시 스팸 방지).
        if not was_enabled:
            try:
                from app.services.notification_service import NotificationService
                NotificationService(self.db).send_kill_switch_alert(
                    exchange_account_id=exchange_account_id,
                    reason_code=reason_code,
                    reason_message=reason_message,
                )
            except Exception as e:
                # 알림 실패는 kill-switch 발동 자체에 영향 X — DB row 는 이미 commit 됨.
                logger.warning("Kill-switch alert failed for account %s: %s", exchange_account_id, e)

    def clear(self, exchange_account_id: int) -> None:
        row = self.db.execute(select(AccountKillSwitch).where(AccountKillSwitch.exchange_account_id == exchange_account_id)).scalar_one_or_none()
        if row:
            row.is_enabled = False
            row.cleared_at = datetime.now(timezone.utc)
            self.db.commit()
