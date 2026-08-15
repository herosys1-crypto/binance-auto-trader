"""ChartPattern 모델 = 4H 차트 패턴 학습 저장! (v152!)

배경 (사장님 요청 2026-08-16):
- 1달 4H 캔들 분석!
- v149/v150/v151 패턴 자동 감지 → 저장!
- outcome 자동 tracking!
- 성공률 = predictor 개선!
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ChartPattern(Base):
    __tablename__ = "chart_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    pattern_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # bb4h_bounce_failure / bb4h_bottom_reversal / bb4h_top_reversal 등!
    side: Mapped[str] = mapped_column(String(10), nullable=False)   # SHORT/LONG
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)

    pattern_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 상세: peak/trough/bounce_peak/first_up_pct/pullback_pct/rsi/macd 등!

    outcome_price_24h: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    outcome_price_48h: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    outcome_price_7d: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    outcome_max_favorable_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    outcome_max_adverse_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)

    outcome_status: Mapped[str] = mapped_column(
        String(20), default="PENDING", nullable=False, index=True,
    )
    # PENDING / SUCCESS / FAIL / EXPIRED
    outcome_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
