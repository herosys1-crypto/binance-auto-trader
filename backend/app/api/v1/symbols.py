"""심볼(거래쌍) 조회 API.

전략 생성 화면에서 심볼 자동완성/선택용으로 사용한다.
거래소 거래 가능한 심볼 목록(`/admin/symbol-sync` 으로 동기화된 것)을 노출.
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.models.symbol import Symbol

router = APIRouter(prefix="/symbols", tags=["symbols"])


class SymbolResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    symbol: str
    base_asset: str
    quote_asset: str
    status: str
    price_precision: int | None = None
    quantity_precision: int | None = None


@router.get("", response_model=list[SymbolResponse])
def list_symbols(
    q: str | None = Query(default=None, description="심볼 검색어 (예: BTC)"),
    only_trading: bool = Query(default=True, description="True 면 status='TRADING' 만 반환"),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[SymbolResponse]:
    """거래 가능 심볼 목록을 반환한다."""
    stmt = select(Symbol)
    if only_trading:
        stmt = stmt.where(Symbol.status == "TRADING")
    if q:
        stmt = stmt.where(Symbol.symbol.ilike(f"%{q.upper()}%"))
    stmt = stmt.order_by(Symbol.symbol).limit(limit)
    rows = db.execute(stmt).scalars().all()
    return [SymbolResponse.model_validate(r) for r in rows]
