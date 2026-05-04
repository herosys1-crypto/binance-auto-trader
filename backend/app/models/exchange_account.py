from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Numeric, func
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

    # ---- 계정별 일일 손실 한도 override (alembic 0010, 2026-05-04) ----
    # NULL = settings.daily_loss_limit_usdt (global) 사용. NULL/0/없음 모두 비활성 의미.
    # 양수 = 이 계정 전용 한도 (USDT). global 보다 우선.
    daily_loss_limit_usdt: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", back_populates="exchange_accounts")
    stream_sessions = relationship("StreamSession", back_populates="exchange_account")
    strategy_instances = relationship("StrategyInstance", back_populates="exchange_account")
