from datetime import datetime, timezone
from sqlalchemy import select
from app.models.account_kill_switch import AccountKillSwitch

class AccountKillSwitchService:
    def __init__(self, db) -> None:
        self.db = db

    def is_enabled(self, exchange_account_id: int) -> bool:
        row = self.db.execute(select(AccountKillSwitch).where(AccountKillSwitch.exchange_account_id == exchange_account_id)).scalar_one_or_none()
        return bool(row and row.is_enabled)

    def trigger(self, exchange_account_id: int, reason_code: str, reason_message: str) -> None:
        row = self.db.execute(select(AccountKillSwitch).where(AccountKillSwitch.exchange_account_id == exchange_account_id)).scalar_one_or_none()
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

    def clear(self, exchange_account_id: int) -> None:
        row = self.db.execute(select(AccountKillSwitch).where(AccountKillSwitch.exchange_account_id == exchange_account_id)).scalar_one_or_none()
        if row:
            row.is_enabled = False
            row.cleared_at = datetime.now(timezone.utc)
            self.db.commit()
