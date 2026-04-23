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
