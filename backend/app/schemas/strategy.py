from datetime import datetime
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
    # UX #18 (2026-04-29): 사용자가 템플릿 기본 레버리지를 override 할 수 있게 지원.
    # None 이면 템플릿 leverage 사용. 1~125 범위.
    leverage_override: int | None = Field(default=None, ge=1, le=125)

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
    start_price: Decimal | None = None      # 운영자가 입력한 1단계 LIMIT 진입요청가
    avg_entry_price: Decimal | None = None
    current_position_qty: Decimal
    invested_capital: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    liquidation_price: Decimal | None = None
    # ─── 크라이시스 복구 모드 + PnL 추적 (Phase D) ───
    max_loss_pct: Decimal | None = None
    max_profit_pct: Decimal | None = None
    crisis_mode_triggered_at: datetime | None = None
    crisis_first_tp_done_at: datetime | None = None
    peak_pnl_pct_after_first_tp: Decimal | None = None
