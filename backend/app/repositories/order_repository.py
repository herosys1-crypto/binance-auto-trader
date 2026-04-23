from sqlalchemy import select
from app.models.order import Order

class OrderRepository:
    def __init__(self, db) -> None:
        self.db = db

    def create(self, order: Order) -> Order:
        self.db.add(order)
        self.db.flush()
        return order

    def list_by_strategy(self, strategy_instance_id: int, status: str | None = None, purpose: str | None = None, stage_no: int | None = None) -> list[Order]:
        stmt = select(Order).where(Order.strategy_instance_id == strategy_instance_id)
        if status:
            stmt = stmt.where(Order.status == status)
        if purpose:
            stmt = stmt.where(Order.purpose == purpose)
        if stage_no is not None:
            stmt = stmt.where(Order.stage_no == stage_no)
        stmt = stmt.order_by(Order.id.desc())
        return list(self.db.execute(stmt).scalars().all())
