from sqlalchemy import select
from app.models.position import Position

class PositionRepository:
    def __init__(self, db) -> None:
        self.db = db

    def latest_by_strategy(self, strategy_instance_id: int) -> Position | None:
        # reconcile/account_update 가 매번 새 Position 스냅샷을 추가하므로 여러 row 가 존재함.
        # .scalar_one_or_none() 은 결과가 여러 개면 예외를 던지므로 .limit(1) + scalars().first() 사용.
        stmt = (
            select(Position)
            .where(Position.strategy_instance_id == strategy_instance_id)
            .order_by(Position.snapshot_time.desc(), Position.id.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalars().first()
