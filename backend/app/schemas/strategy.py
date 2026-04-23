from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

StrategySide = Literal["LONG", "SHORT"]

class StagePlanPreview(BaseModel):
    stage_no: int
    trigger_mode: str
    trigger_percent: Decimal | None = None
    trigger_price: Decimal | None = None
    planned_capital: Decimal
    planned_qty: Decimal | None = None

class StrategyCalculateRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=30)
    side: StrategySide
    start_price: Decimal = Field(..., gt=0)
    strategy_template_id: int
    total_capital: Decimal = Field(..., gt=0)

class StrategyCalculateResponse(BaseModel):
    symbol: str
    side: StrategySide
    leverage: int
    stages: list[StagePlanPreview]
    tp1_percent: Decimal
    tp2_percent: Decimal
    tp3_percent: Decimal
    stop_loss_amount: Decimal

class StrategyCreateRequest(BaseModel):
    exchange_account_id: int
    strategy_template_id: int
    symbol: str
    side: StrategySide
    start_price: Decimal = Field(..., gt=0)

class StrategyStopRequest(BaseModel):
    mode: Literal["cancel_only", "close_position_market", "emergency_stop"]
    reason: str | None = None

class StrategyActionResponse(BaseModel):
    strategy_id: int
    status: str
    message: str

class StrategyInstanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    symbol: str
    side: StrategySide
    status: str
    reentry_ready: bool

class StrategyDetailResponse(StrategyInstanceResponse):
    leverage: int
    current_stage: int
    avg_entry_price: Decimal | None = None
    current_position_qty: Decimal
    invested_capital: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    liquidation_price: Decimal | None = None
