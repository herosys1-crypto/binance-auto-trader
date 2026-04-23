from sqlalchemy import select
from app.models.symbol import Symbol

class SymbolRepository:
    def __init__(self, db) -> None:
        self.db = db

    def get_by_symbol(self, symbol: str) -> Symbol | None:
        return self.db.execute(select(Symbol).where(Symbol.symbol == symbol)).scalar_one_or_none()
