from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class ExchangeAccount(Base):
    __tablename__ = "exchange_accounts"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    exchange_name: Mapped[str] = mapped_column(String(30), default="binance", nullable=False)
    market_type: Mapped[str] = mapped_column(String(30), default="usds_m_futures", nullable=False)
    api_key_enc: Mapped[str] = mapped_column(nullable=False)
    api_secret_enc: Mapped[str] = mapped_column(nullable=False)
    passphrase_enc: Mapped[str | None] = mapped_column(nullable=True)
    hedge_mode_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_testnet: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", back_populates="exchange_accounts")
    stream_sessions = relationship("StreamSession", back_populates="exchange_account")
    strategy_instances = relationship("StrategyInstance", back_populates="exchange_account")
