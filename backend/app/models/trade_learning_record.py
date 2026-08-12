"""TradeLearningRecord 모델 = 모든 거래 학습 저장! (v134 사장님 신!)

배경 (사장님 요청 2026-08-13):
"지금 매매가 성공이든 실패이든 모든 거래를 학습해서 저장하고
 [...]자동화했을때도 항상 진행과정과 종료된거래를 학습해서 다음에 더 잘 활용할수 있게 저장해줘"

= 모든 거래 자동 학습!
= 진입 시 record 생성!
= 종료 시 update + insights!
= 진행 중 스냅샷 (5분 단위!)

관련:
- alembic 0028: trade_learning_records 테이블!
- service: app/services/trade_learning_service.py
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TradeLearningRecord(Base):
    __tablename__ = "trade_learning_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_instance_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True, unique=True,
    )
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # LONG/SHORT
    status: Mapped[str] = mapped_column(
        String(30), default="OPEN", nullable=False, index=True,
    )
    # OPEN (진입~진행 중!) / CLOSED (종료!)

    # 가격/시간!
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    entry_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # PnL!
    pnl_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    pnl_usdt: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    max_profit_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    max_loss_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)

    # 종료 이유!
    close_reason: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    # TP1/TP2/... /FORCE_SL/USER_STOP/CRISIS 등!

    # JSONB (풍부한 학습 데이터!)
    entry_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 진입 시 설정 (leverage, capitals, tp/sl, trigger_pct 등!)

    entry_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 진입 시 시장 상황 (RSI, BB, 24h change, 5m change 등!)

    exit_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 종료 시 시장 상황!

    progression: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 진행 중 스냅샷 리스트 = [{time, price, pnl, rsi, bb}, ...]

    insights: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 자동 인사이트 = {win_lose, hold_duration_min, best_stage, lessons: [...]}

    # 타임!
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
