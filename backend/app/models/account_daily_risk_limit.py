from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class AccountDailyRiskLimit(Base):
    __tablename__ = "account_daily_risk_limits"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exchange_account_id: Mapped[int] = mapped_column(ForeignKey("exchange_accounts.id"), nullable=False, index=True)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    unrealized_pnl_snapshot: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    daily_loss_limit_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
