from decimal import Decimal

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


def _enrich_orders_with_pnl(rows: list[Order], db: Session) -> list[OrderResponse]:
    """EXIT 주문에 대해 손익 + ROI 계산해서 응답에 채움 (2026-05-03 추가).

    EXIT 시점의 평균진입가는 그 시점 이전까지의 ENTRY orders 의 가중평균.
    leverage 는 strategy 의 leverage 사용.
    """
    # strategy 별 ENTRY orders + leverage batch fetch (N+1 방지)
    strategy_ids = {r.strategy_instance_id for r in rows}
    strategies = {
        s.id: s for s in db.execute(select(StrategyInstance).where(StrategyInstance.id.in_(strategy_ids))).scalars().all()
    } if strategy_ids else {}
    # 각 strategy 의 ENTRY FILLED orders 시간순
    entry_orders = {}
    if strategy_ids:
        for o in db.execute(
            select(Order)
            .where(Order.strategy_instance_id.in_(strategy_ids))
            .where(Order.purpose == "ENTRY")
            .where(Order.status == "FILLED")
            .order_by(Order.created_at)
        ).scalars().all():
            entry_orders.setdefault(o.strategy_instance_id, []).append(o)

    out = []
    for r in rows:
        resp = OrderResponse.model_validate(r)
        if r.purpose in ("EXIT", "TAKE_PROFIT", "STOP_LOSS", "EMERGENCY_CLOSE") and r.status == "FILLED":
            try:
                strategy = strategies.get(r.strategy_instance_id)
                if not strategy:
                    raise ValueError("no strategy")
                # EXIT 시점 이전까지 ENTRY 들의 가중평균
                entries = [e for e in entry_orders.get(r.strategy_instance_id, []) if e.created_at < r.created_at]
                if not entries:
                    raise ValueError("no entries before exit")
                cum_qty = Decimal("0")
                cum_notional = Decimal("0")
                for e in entries:
                    q = Decimal(str(e.executed_qty or 0))
                    p = Decimal(str(e.avg_price or e.price or 0))
                    if q > 0 and p > 0:
                        cum_qty += q
                        cum_notional += q * p
                if cum_qty <= 0:
                    raise ValueError("zero entry qty")
                avg_entry = cum_notional / cum_qty
                exit_qty = Decimal(str(r.executed_qty or 0))
                exit_px = Decimal(str(r.avg_price or r.price or 0))
                if exit_qty <= 0 or exit_px <= 0:
                    raise ValueError("invalid exit price/qty")
                if strategy.side == "LONG":
                    pnl = (exit_qty * (exit_px - avg_entry)).quantize(Decimal("0.01"))
                    raw_pct = (exit_px - avg_entry) / avg_entry * Decimal("100")
                else:
                    pnl = (exit_qty * (avg_entry - exit_px)).quantize(Decimal("0.01"))
                    raw_pct = (avg_entry - exit_px) / avg_entry * Decimal("100")
                lev = Decimal(str(strategy.leverage or 1))
                resp.realized_pnl = pnl
                resp.pnl_pct = (raw_pct * lev).quantize(Decimal("0.01"))
                resp.avg_entry_price = avg_entry.quantize(Decimal("0.00000001"))
            except Exception:
                # 계산 불가 (예: ENTRY 없음, 가격 0) — 그대로 None 유지
                pass
        out.append(resp)
    return out


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
    return _enrich_orders_with_pnl(rows, db)


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
    return _enrich_orders_with_pnl(rows, db)
