from datetime import datetime
from sqlalchemy import Index, String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class RiskEvent(Base):
    __tablename__ = "risk_events"
    # 2026-05-14 Phase 5: composite index (severity, created_at DESC).
    # 사용처: admin/system-status 가 WHERE severity='CRITICAL' AND created_at >= cutoff
    # ORDER BY id DESC LIMIT 20 — CRITICAL 이벤트가 드물어도 risk_events 자체는 누적됨.
    # 추가: (created_at DESC) — recent-activity / health/dashboard 가 시간 정렬 사용.
    __table_args__ = (
        Index("ix_risk_events_severity_created_at", "severity", "created_at"),
        Index("ix_risk_events_created_at", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # NULL 허용: listenKeyExpired, ORDER_TRADE_UPDATE 미매칭 등 특정 strategy 에 속하지 않는 시스템 이벤트용.
    strategy_instance_id: Mapped[int | None] = mapped_column(ForeignKey("strategy_instances.id", ondelete="CASCADE"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str | None] = mapped_column(nullable=True)
    event_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    strategy_instance = relationship("StrategyInstance", back_populates="risk_events")
