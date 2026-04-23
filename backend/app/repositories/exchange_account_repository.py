from sqlalchemy import select
from app.models.exchange_account import ExchangeAccount

class ExchangeAccountRepository:
    def __init__(self, db) -> None:
        self.db = db

    def get(self, account_id: int) -> ExchangeAccount | None:
        return self.db.get(ExchangeAccount, account_id)

    def get_first_active_binance(self) -> ExchangeAccount | None:
        stmt = select(ExchangeAccount).where(
            ExchangeAccount.exchange_name == "binance",
            ExchangeAccount.is_active.is_(True),
        )
        return self.db.execute(stmt).scalar_one_or_none()
