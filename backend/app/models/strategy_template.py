from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import String, Integer, Boolean, DateTime, func, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class StrategyTemplate(Base):
    """전략 템플릿.

    stages_config 가 신규 동적 N단계 (1~10) 정의를 담는다. 형식:
        {
          "capitals": [100, 200, 350],
          "trigger_percents": [null, 10, null],         # 선택 — None 이면 기본 10%
          "last_stage_trigger_mode": "LIQUIDATION_BUFFER",  # SHORT 기본
          "last_stage_trigger_percent": 5
        }
    stages_config 가 없는 (구) 템플릿은 stage1~4_capital 컬럼을 사용.
    """

    __tablename__ = "strategy_templates"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    strategy_type: Mapped[str] = mapped_column(String(40), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    leverage: Mapped[int] = mapped_column(Integer, nullable=False)
    total_capital: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)

    # ---- 신규 동적 단계 ----
    stages_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # ---- 구 4단계 컬럼 (호환성 유지) ----
    stage1_capital: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    stage2_capital: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    stage3_capital: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    stage4_capital: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    stage2_trigger_percent: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    stage3_trigger_percent: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    stage4_trigger_mode: Mapped[str | None] = mapped_column(String(30), nullable=True)
    stage4_trigger_percent: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)

    # ---- TP/SL ----
    # TP1~3 은 항상 채움(필수). TP4/5 는 선택적 — NULL 이면 미사용.
    tp1_percent: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    tp2_percent: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    tp3_percent: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    tp4_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    tp5_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    tp1_qty_ratio: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    tp2_qty_ratio: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    tp3_qty_ratio: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    tp4_qty_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    tp5_qty_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    stop_loss_percent_of_capital: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)

    reentry_policy: Mapped[str] = mapped_column(String(30), default="manual_ready", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    strategy_instances = relationship("StrategyInstance", back_populates="strategy_template")
