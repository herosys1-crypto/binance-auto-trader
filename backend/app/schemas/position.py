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


class ExternalPositionResponse(BaseModel):
    """거래소에 있지만 도구가 추적 안 하는 외부 포지션 (수동 진입 등).

    2026-05-21 사장님 요구: PHB/RONIN 사례처럼 도구 밖에서 사장님이 직접 진입한 포지션도
    대시보드에 표시. 도구의 자동 청산/관리 대상은 아님 — 단순 가시성용.
    """
    account_id: int
    account_label: str         # 사용자 식별용 (testnet/mainnet 등)
    symbol: str
    side: str                  # LONG / SHORT (positionSide 그대로)
    position_amt: Decimal      # signed (음수=SHORT)
    entry_price: Decimal | None = None
    mark_price: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    leverage: int | None = None
    liquidation_price: Decimal | None = None
    margin_type: str | None = None  # cross / isolated
