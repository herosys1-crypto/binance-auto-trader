from sqlalchemy import select
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_stage_plan import StrategyStagePlan
from app.models.strategy_template import StrategyTemplate
from app.models.symbol import Symbol

class StrategyRepository:
    def __init__(self, db) -> None:
        self.db = db

    def get_template(self, template_id: int) -> StrategyTemplate | None:
        return self.db.get(StrategyTemplate, template_id)

    def get_symbol(self, symbol: str) -> Symbol | None:
        stmt = select(Symbol).where(Symbol.symbol == symbol)
        return self.db.execute(stmt).scalar_one_or_none()

    def create_strategy_instance(self, instance: StrategyInstance) -> StrategyInstance:
        self.db.add(instance)
        self.db.flush()
        return instance

    def create_stage_plans(self, plans: list[StrategyStagePlan]) -> None:
        self.db.add_all(plans)
        self.db.flush()

    def get_strategy(self, strategy_id: int) -> StrategyInstance | None:
        return self.db.get(StrategyInstance, strategy_id)

    def list_strategies(
        self,
        user_id: int,
        status: str | None = None,
        symbol: str | None = None,
        include_archived: bool = False,
    ) -> list[StrategyInstance]:
        """사용자의 strategy 목록.

        2026-05-06 (PR #7 후속): default 로 archived 제외 (UI 깔끔). ?include_archived=true
        쿼리 파라미터로 archived 도 포함 가능 (운영 통계 / restore UI 용).
        """
        stmt = select(StrategyInstance).where(StrategyInstance.user_id == user_id)
        if not include_archived:
            stmt = stmt.where(StrategyInstance.is_archived.is_(False))
        if status:
            stmt = stmt.where(StrategyInstance.status == status)
        if symbol:
            stmt = stmt.where(StrategyInstance.symbol == symbol)
        stmt = stmt.order_by(StrategyInstance.id.desc())
        return list(self.db.execute(stmt).scalars().all())
