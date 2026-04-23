from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Integer, DateTime, func, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class Symbol(Base):
    __tablename__ = "symbols"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    base_asset: Mapped[str] = mapped_column(String(20), nullable=False)
    quote_asset: Mapped[str] = mapped_column(String(20), nullable=False)
    contract_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    price_precision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity_precision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tick_size: Mapped[Decimal | None] = mapped_column(Numeric(30, 12), nullable=True)
    step_size: Mapped[Decimal | None] = mapped_column(Numeric(30, 12), nullable=True)
    min_qty: Mapped[Decimal | None] = mapped_column(Numeric(30, 12), nullable=True)
    min_notional: Mapped[Decimal | None] = mapped_column(Numeric(30, 12), nullable=True)
    raw_exchange_info: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    strategy_instances = relationship("StrategyInstance", back_populates="symbol_ref")
