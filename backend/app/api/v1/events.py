from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.models.risk_event import RiskEvent
from app.repositories.strategy_repository import StrategyRepository
from app.schemas.risk import RiskEventResponse

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/by-strategy/{strategy_id}", response_model=list[RiskEventResponse])
def list_events_by_strategy(
    strategy_id: int,
    severity: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[RiskEventResponse]:
    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")
    stmt = select(RiskEvent).where(RiskEvent.strategy_instance_id == strategy_id)
    if severity:
        stmt = stmt.where(RiskEvent.severity == severity)
    stmt = stmt.order_by(RiskEvent.id.desc()).limit(max(1, min(limit, 500)))
    rows = db.execute(stmt).scalars().all()
    return [RiskEventResponse.model_validate(r) for r in rows]
