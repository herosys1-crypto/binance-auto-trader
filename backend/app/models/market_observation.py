"""MarketObservation 모델 = 진입 X 심볼도 관찰! (v136 사장님!)

배경: 사장님이 진입한 심볼만 학습 X → 모든 상위 심볼 학습!
= 다음 예측 = 훨씬 정교!

관련: alembic 0030, market_observation_worker.py
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MarketObservation(Base):
    __tablename__ = "market_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    price_at_obs: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    price_1h_later: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    price_4h_later: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    price_24h_later: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)

    change_1h: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    change_4h: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    change_24h_later: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)

    rank_by_pump: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rank_by_dump: Mapped[int | None] = mapped_column(Integer, nullable=True)

    side_would_have: Mapped[str | None] = mapped_column(String(10), nullable=True)  # 사후 판단!
    market_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
