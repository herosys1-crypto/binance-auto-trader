from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class AccountKillSwitch(Base):
    __tablename__ = "account_kill_switches"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exchange_account_id: Mapped[int] = mapped_column(ForeignKey("exchange_accounts.id"), nullable=False, unique=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    reason_message: Mapped[str | None] = mapped_column(nullable=True)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
