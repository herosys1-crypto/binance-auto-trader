from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict

class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    strategy_instance_id: int
    stage_no: int | None = None
    purpose: str
    symbol: str
    side: str
    position_side: str
    order_type: str
    client_order_id: str
    exchange_order_id: int | None = None
    trigger_price: Decimal | None = None
    price: Decimal | None = None
    orig_qty: Decimal | None = None
    executed_qty: Decimal
    avg_price: Decimal | None = None
    status: str
    created_at: datetime
    updated_at: datetime
    # ─── EXIT 주문 손익 표시용 (2026-05-03 추가) ───
    # ENTRY 는 0/None. EXIT (TP/SL/수동청산) 는 실현 손익 + ROI %.
    realized_pnl: Decimal | None = None
    pnl_pct: Decimal | None = None
    avg_entry_price: Decimal | None = None  # 청산 시점의 strategy 평균 진입가 (참고)
