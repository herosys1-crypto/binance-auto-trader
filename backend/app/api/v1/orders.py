from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.models.order import Order
from app.models.strategy_instance import StrategyInstance
from app.repositories.order_repository import OrderRepository
from app.repositories.strategy_repository import StrategyRepository
from app.schemas.order import OrderResponse

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", response_model=list[OrderResponse])
def list_orders(
    limit: int = 500,
    status_filter: str | None = None,
    purpose: str | None = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[OrderResponse]:
    """현재 사용자의 모든 주문을 최신순으로 조회. 거래 실적 모달용."""
    stmt = (
        select(Order)
        .join(StrategyInstance, Order.strategy_instance_id == StrategyInstance.id)
        .where(StrategyInstance.user_id == user_id)
        .order_by(desc(Order.created_at))
        .limit(limit)
    )
    if status_filter:
        stmt = stmt.where(Order.status == status_filter)
    if purpose:
        stmt = stmt.where(Order.purpose == purpose)
    rows = db.execute(stmt).scalars().all()
    return [OrderResponse.model_validate(r) for r in rows]


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
