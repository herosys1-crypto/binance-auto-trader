from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict

class RiskEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    # 2026-05-04 audit fix: 모델은 nullable=True (alembic 0008) — listenKeyExpired 등
    # 시스템 레벨 이벤트는 strategy_instance_id NULL. 이전엔 schema 가 required 라
    # 시스템 이벤트 직렬화 시 ValidationError 트랩. Optional 로 정렬.
    strategy_instance_id: int | None = None
    event_type: str
    severity: str
    title: str
    message: str | None = None
    event_payload: dict[str, Any] | None = None
    created_at: datetime
