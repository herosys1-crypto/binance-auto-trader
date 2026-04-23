from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.repositories.position_repository import PositionRepository
from app.repositories.strategy_repository import StrategyRepository
from app.schemas.position import PositionResponse

router = APIRouter(prefix="/positions", tags=["positions"])


@router.get("/by-strategy/{strategy_id}/latest", response_model=PositionResponse)
def get_latest_position(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> PositionResponse:
    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")
    position = PositionRepository(db).latest_by_strategy(strategy_id)
    if not position:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position snapshot not found")
    return PositionResponse.model_validate(position)
