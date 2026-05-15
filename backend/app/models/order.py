from datetime import datetime
from decimal import Decimal
from sqlalchemy import Index, String, Integer, BigInteger, DateTime, ForeignKey, func, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class Order(Base):
    __tablename__ = "orders"
    # 2026-05-14 Phase 5: composite index (strategy_instance_id, stage_no, purpose, status).
    # 사용처:
    #   - control.trigger_next_stage_manually: WHERE strategy_id AND stage_no AND purpose='ENTRY' AND status='NEW'
    #   - risk_service crisis 검사: WHERE strategy_id AND stage_no IS NULL AND purpose='ENTRY' AND status='FILLED'
    #   - reconcile / zombie_guardian 의 stage 관련 query 들
    # 단일 strategy_instance_id 인덱스로는 stage/purpose/status 추가 필터 시 row 너무 많이 fetch.
    __table_args__ = (
        Index("ix_orders_strategy_stage_purpose_status", "strategy_instance_id", "stage_no", "purpose", "status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    strategy_instance_id: Mapped[int] = mapped_column(ForeignKey("strategy_instances.id", ondelete="CASCADE"), nullable=False, index=True)
    stage_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    position_side: Mapped[str] = mapped_column(String(10), nullable=False)
    order_type: Mapped[str] = mapped_column(String(30), nullable=False)
    time_in_force: Mapped[str | None] = mapped_column(String(10), nullable=True)
    client_order_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    exchange_order_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trigger_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    orig_qty: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    executed_qty: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    avg_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    raw_request: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    raw_response: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    strategy_instance = relationship("StrategyInstance", back_populates="orders")
