"""StrategySuggestion 모델 = 자동 생성 전략 제안!

v132 신 팀 = Strategy Suggestion Team!
사장님 요구 = 매일 자동 제안 → 수동/자동 실행!

관련:
- alembic 0027: strategy_suggestions 테이블!
- spec: docs/STRATEGY_SUGGESTION_SPEC_v132.html
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StrategySuggestion(Base):
    __tablename__ = "strategy_suggestions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # LONG/SHORT
    suggestion_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # pump_expected / dump_continuation / reversal_up / pump_end

    strategy_config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # 사장님 신 default (자본, 트리거, TP/SL 등!)

    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    # 0.000 ~ 1.000
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), default="PENDING", nullable=False, index=True,
    )
    # PENDING / EXECUTED / DISMISSED / EXPIRED

    execution_mode: Mapped[str] = mapped_column(
        String(10), default="MANUAL", nullable=False,
    )
    # MANUAL (기본 - 사장님!) / AUTO (옵션)

    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_strategy_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ⭐ 사장님 요구 = 만들어진 시간 표기!
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
