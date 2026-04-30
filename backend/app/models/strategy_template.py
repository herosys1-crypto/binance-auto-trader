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
          "trigger_percents": [null, 10, null],         # 선택 — None 이면 단계별 기본값
          "last_stage_trigger_mode": "PRICE_UP_PCT",    # SHORT/LONG 기본 (PRICE_UP_PCT/PRICE_DOWN_PCT)
                                                          # "LIQUIDATION_BUFFER" 로 명시 시 청산가 기반
          "last_stage_trigger_percent": 20              # 미지정 시 기본 20%
        }
    사용자 기획 변경 (2026-04-30): SHORT 마지막 단계 default 가
    LIQUIDATION_BUFFER → PRICE_UP_PCT (사용자 입력값 사용) 로 변경됨.
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
    # auto 정책 — SL 후 자동 재시작 대기 시간 (초). 기본 600 (10분).
    reentry_delay_seconds: Mapped[int] = mapped_column(Integer, default=600, nullable=False)
    # auto 정책 — 새 start_price 계산 오프셋 % (현재가에서 SHORT 위 / LONG 아래 방향).
    reentry_offset_pct: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal("1.0"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    strategy_instances = relationship("StrategyInstance", back_populates="strategy_template")
