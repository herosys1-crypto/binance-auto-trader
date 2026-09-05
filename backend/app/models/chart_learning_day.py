"""📚 ChartLearningDay = 차트 학습 일지 한 행 = (날짜, 심볼) (Fix 353, 2026-09-05).

사장님: "상승 50위 하락 50위 심볼을 차트를 … 매일 매일 나눠서 학습을 해줘"

한 행 = 어느 날 스냅샷 시각에 감시 대상(당일·3·5일 순위)이던 심볼 하나.
  - `klines`  : 스냅샷 **전** 15m 200봉 + 4h 61봉, 라벨링 때 **후** 15m 144봉(36h) 추가. 45일 뒤 비움(설정).
  - `outcome` : 라벨 (자리의 값 + 규칙별 첫 충족 결과). **영구**.
서비스: app/services/chart_learning.py / 워커: app/workers/chart_learning_worker.py
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ChartLearningDay(Base):
    __tablename__ = "chart_learning_days"
    __table_args__ = (UniqueConstraint("snap_date", "symbol", name="uq_chart_learning_day_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snap_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="live")   # live / backfill

    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)     # ["UP", "UP5D", ...]
    ranks: Mapped[dict | None] = mapped_column(JSONB, nullable=True)    # {"UP": 3, "UP5D": 12}
    chg_24h: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    chg_3d: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    chg_5d: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    quote_volume: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)

    snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)   # 스냅샷 시점 지표
    klines: Mapped[dict | None] = mapped_column(JSONB, nullable=True)     # {"15m": [...], "4h": [...], "15m_fwd": [...]}
    outcome: Mapped[dict | None] = mapped_column(JSONB, nullable=True)    # label_row() 결과
    outcome_status: Mapped[str] = mapped_column(String(12), nullable=False, default="PENDING", index=True)
    # PENDING / DONE / EXPIRED(결과 봉을 못 받음)
    labeled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
