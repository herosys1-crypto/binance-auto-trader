from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, func, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class StrategyInstance(Base):
    __tablename__ = "strategy_instances"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    exchange_account_id: Mapped[int] = mapped_column(ForeignKey("exchange_accounts.id"), nullable=False, index=True)
    strategy_template_id: Mapped[int] = mapped_column(ForeignKey("strategy_templates.id"), nullable=False, index=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    start_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    leverage: Mapped[int] = mapped_column(Integer, nullable=False)
    total_capital: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    current_stage: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_entry_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    current_position_qty: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    invested_capital: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    liquidation_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="WAITING", nullable=False, index=True)
    reentry_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", back_populates="strategy_instances")
    exchange_account = relationship("ExchangeAccount", back_populates="strategy_instances")
    strategy_template = relationship("StrategyTemplate", back_populates="strategy_instances")
    symbol_ref = relationship("Symbol", back_populates="strategy_instances")
    stage_plans = relationship("StrategyStagePlan", back_populates="strategy_instance", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="strategy_instance", cascade="all, delete-orphan")
    positions = relationship("Position", back_populates="strategy_instance", cascade="all, delete-orphan")
    risk_events = relationship("RiskEvent", back_populates="strategy_instance", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="strategy_instance")
