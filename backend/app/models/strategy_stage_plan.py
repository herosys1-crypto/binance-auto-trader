from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint, func, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class StrategyStagePlan(Base):
    __tablename__ = "strategy_stage_plans"
    __table_args__ = (UniqueConstraint("strategy_instance_id", "stage_no", name="uq_strategy_stage"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    strategy_instance_id: Mapped[int] = mapped_column(ForeignKey("strategy_instances.id", ondelete="CASCADE"), nullable=False, index=True)
    stage_no: Mapped[int] = mapped_column(Integer, nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    trigger_mode: Mapped[str] = mapped_column(String(30), nullable=False)
    trigger_percent: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    trigger_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    planned_capital: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    planned_qty: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    # 2026-05-11 (사용자 요청): 단계 진입 시 추가 isolated 증거금 (USDT).
    # NULL/0 = 추가 안 함 (기존 동작). 양수 = stage_trigger_worker 가 entry 주문
    # 체결 후 add_position_margin API 호출. 청산가를 멀리 밀어 안전 마진 확보.
    additional_margin_usdt: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_triggered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    strategy_instance = relationship("StrategyInstance", back_populates="stage_plans")
