from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict

class PositionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    strategy_instance_id: int
    symbol: str
    side: str
    position_side: str
    entry_price: Decimal | None = None
    mark_price: Decimal | None = None
    liquidation_price: Decimal | None = None
    position_amt: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    leverage: int | None = None
    snapshot_time: datetime
