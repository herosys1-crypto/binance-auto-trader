from sqlalchemy import select
from app.models.exchange_account import ExchangeAccount

class ExchangeAccountRepository:
    def __init__(self, db) -> None:
        self.db = db

    def get(self, account_id: int) -> ExchangeAccount | None:
        return self.db.get(ExchangeAccount, account_id)

    def get_first_active_binance(self, user_id: int | None = None) -> ExchangeAccount | None:
        """첫 active Binance 계정 반환.

        2026-05-04 audit fix: user_id 파라미터 추가. 호출자가 None 으로 두면 모든 user
        의 첫 active 계정 (legacy single-user 호환). user_id 지정 시 그 사람의 계정만.
        admin/symbol-sync 등 호출자는 user_id 를 반드시 전달해야 multi-user 프라이버시
        보장.
        """
        stmt = select(ExchangeAccount).where(
            ExchangeAccount.exchange_name == "binance",
            ExchangeAccount.is_active.is_(True),
        )
        if user_id is not None:
            stmt = stmt.where(ExchangeAccount.user_id == user_id)
        return self.db.execute(stmt).scalar_one_or_none()
