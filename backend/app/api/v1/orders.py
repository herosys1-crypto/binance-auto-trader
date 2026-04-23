from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.repositories.order_repository import OrderRepository
from app.repositories.strategy_repository import StrategyRepository
from app.schemas.order import OrderResponse

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("/by-strategy/{strategy_id}", response_model=list[OrderResponse])
def list_orders_by_strategy(
    strategy_id: int,
    status_filter: str | None = None,
    purpose: str | None = None,
    stage_no: int | None = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[OrderResponse]:
    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")
    rows = OrderRepository(db).list_by_strategy(
        strategy_instance_id=strategy_id,
        status=status_filter,
        purpose=purpose,
        stage_no=stage_no,
    )
    return [OrderResponse.model_validate(r) for r in rows]
