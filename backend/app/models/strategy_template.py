from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Integer, Boolean, DateTime, func, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class StrategyTemplate(Base):
    __tablename__ = "strategy_templates"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    strategy_type: Mapped[str] = mapped_column(String(40), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    leverage: Mapped[int] = mapped_column(Integer, nullable=False)
    total_capital: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    stage1_capital: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    stage2_capital: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    stage3_capital: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    stage4_capital: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    stage2_trigger_percent: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    stage3_trigger_percent: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    stage4_trigger_mode: Mapped[str] = mapped_column(String(30), nullable=False)
    stage4_trigger_percent: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    tp1_percent: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    tp2_percent: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    tp3_percent: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    tp1_qty_ratio: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    tp2_qty_ratio: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    tp3_qty_ratio: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    stop_loss_percent_of_capital: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    reentry_policy: Mapped[str] = mapped_column(String(30), default="manual_ready", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    strategy_instances = relationship("StrategyInstance", back_populates="strategy_template")
