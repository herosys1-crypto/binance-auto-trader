from sqlalchemy import select
from app.models.position import Position

class PositionRepository:
    def __init__(self, db) -> None:
        self.db = db

    def latest_by_strategy(self, strategy_instance_id: int) -> Position | None:
        stmt = (
            select(Position)
            .where(Position.strategy_instance_id == strategy_instance_id)
            .order_by(Position.snapshot_time.desc(), Position.id.desc())
        )
        return self.db.execute(stmt).scalar_one_or_none()
