from datetime import date
from decimal import Decimal
from sqlalchemy import select
from app.models.account_daily_risk_limit import AccountDailyRiskLimit
from app.observability.metrics import kill_switch_trigger_total, kill_switch_enabled
from app.services.account_kill_switch_service import AccountKillSwitchService

class AccountDailyLossLimiterService:
    def __init__(self, db) -> None:
        self.db = db
        self.kill_switch_service = AccountKillSwitchService(db)

    def get_or_create_today_limit(self, *, exchange_account_id: int, daily_loss_limit_amount: Decimal) -> AccountDailyRiskLimit:
        today = date.today()
        row = self.db.execute(select(AccountDailyRiskLimit).where(AccountDailyRiskLimit.exchange_account_id == exchange_account_id, AccountDailyRiskLimit.trading_date == today)).scalar_one_or_none()
        if row:
            return row
        row = AccountDailyRiskLimit(exchange_account_id=exchange_account_id, trading_date=today, daily_loss_limit_amount=daily_loss_limit_amount, realized_pnl=Decimal("0"), unrealized_pnl_snapshot=Decimal("0"), status="ACTIVE")
        self.db.add(row)
        self.db.flush()
        return row

    def update_pnl_and_check(self, *, exchange_account_id: int, realized_pnl: Decimal, unrealized_pnl_snapshot: Decimal, daily_loss_limit_amount: Decimal) -> bool:
        row = self.get_or_create_today_limit(exchange_account_id=exchange_account_id, daily_loss_limit_amount=daily_loss_limit_amount)
        row.realized_pnl = realized_pnl
        row.unrealized_pnl_snapshot = unrealized_pnl_snapshot
        total_today_pnl = realized_pnl + unrealized_pnl_snapshot
        breached = total_today_pnl <= (-daily_loss_limit_amount)
        if breached and row.status != "TRIGGERED":
            row.status = "TRIGGERED"
            self.kill_switch_service.trigger(exchange_account_id=exchange_account_id, reason_code="DAILY_LOSS_LIMIT", reason_message=f"Daily loss limit breached: {total_today_pnl}")
            kill_switch_trigger_total.labels(exchange_account_id=str(exchange_account_id), reason_code="DAILY_LOSS_LIMIT").inc()
            kill_switch_enabled.labels(exchange_account_id=str(exchange_account_id)).set(1)
        self.db.commit()
        return breached
