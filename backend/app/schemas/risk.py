from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict

class RiskEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    strategy_instance_id: int
    event_type: str
    severity: str
    title: str
    message: str | None = None
    event_payload: dict[str, Any] | None = None
    created_at: datetime
