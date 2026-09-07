"""🧪 PaperTrade = 가상 매매 학습 한 건 (Fix 361, 2026-09-08).

사장님: "가상으로 포지션 진입해서 성공과 실패를 기록저장 학습해서 다시 실시간 운영시작 하면
        그때 적용할 수 있게 학습해줘 … 롱과숏 포지션 진입하고 익절중에 포지션 추가해서
        수익을 만들 자리를 찾아줘"

실주문은 한 건도 내지 않는다(엔진은 klines/ticker 만 읽는다). 워커가 규칙(rule)별로 진입점을
"가상"으로 잡고, 매 사이클 재계산(stateless)해서 청산까지 기록한다. 한 행 = (심볼, 규칙, 진입봉) 하나.
엔진: app/services/paper_trading.py / 워커: app/workers/paper_trading_worker.py
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PaperTrade(Base):
    __tablename__ = "paper_trades"
    # status / opened_at / rule 은 아래 컬럼의 index=True 로 이미 인덱스가 생긴다(중복 정의 금지 — 마이그레이션 충돌).
    __table_args__ = (
        UniqueConstraint("symbol", "rule", "entry_bar_ts", name="uq_paper_trade_entry"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="live", index=True)  # live / backfill
    symbol: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(5), nullable=False)  # LONG / SHORT
    rule: Mapped[str] = mapped_column(String(40), nullable=False, index=True)

    entry_bar_ts: Mapped[int] = mapped_column(BigInteger, nullable=False)  # 진입봉 open time(ms)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)  # 진입봉 종가
    tp1_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)  # 진입봉 마감시각
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(String(8), nullable=False, default="OPEN", index=True)  # OPEN / CLOSED
    close_reason: Mapped[str | None] = mapped_column(String(60), nullable=True)

    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    chg_24h: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    chg_3d: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    chg_5d: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)   # 진입 시점 지표
    engines: Mapped[dict | None] = mapped_column(JSONB, nullable=True)    # {"house": {...}, "live": {...}}
    adds: Mapped[dict | None] = mapped_column(JSONB, nullable=True)       # 변형별 추가매수(피라미딩) 로트

    bars_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mfe: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    mae: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
