"""🗾 IchikijunLabTrade = 일목 기준선 변형 실험실 가상 거래 한 건 (Fix 465, 2026-10-18).

사장님: 「가상매매로 이 전략을 수정해서 승률이 제일 높은 방법을 지속적으로 찾아서 업데이트」.
주문 없음. 한 행 = (kind, 변형, 방향, 심볼, 진입봉) 하나. kind = sig(신호) | rand(같은 시각 무작위 짝 — pair_symbol 이 신호 심볼).
paper_trades 와 분리한 이유: 가상 엔진이 열린 행을 source 와 무관하게 공통 청산으로 관리한다(이 전략 청산을 잴 수 없음).
서비스: app/services/ichimoku_kijun.py · app/services/ichikijun_lab.py / 워커: app/workers/ichikijun_lab_worker.py
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IchikijunLabTrade(Base):
    __tablename__ = "ichikijun_lab_trades"
    __table_args__ = (
        UniqueConstraint("kind", "variant", "side", "symbol", "entry_bar_ts", name="uq_ichilab_entry"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(4), nullable=False)                     # sig / rand
    variant: Mapped[str] = mapped_column(String(24), nullable=False, index=True)     # 예 4h_src_now_r2kj
    side: Mapped[str] = mapped_column(String(5), nullable=False)
    interval: Mapped[str] = mapped_column(String(4), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    pair_symbol: Mapped[str | None] = mapped_column(String(30), nullable=True)       # rand 행: 짝인 신호 심볼
    signal_bar_ts: Mapped[int] = mapped_column(BigInteger, nullable=False)           # 신호 봉(되돌림 진입이면 진입보다 앞)
    entry_bar_ts: Mapped[int] = mapped_column(BigInteger, nullable=False)            # 진입 봉 open time(ms) · 진입 = 이 봉 종가
    entry_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    stop_pct: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)          # 손절폭 % (클램프 뒤)
    clamped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    btc_up: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    status: Mapped[str] = mapped_column(String(6), nullable=False, default="OPEN", index=True)   # OPEN / CLOSED
    exit_reason: Mapped[str | None] = mapped_column(String(4), nullable=True)        # SL / TP / KJ / TIME
    r_gross: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    r_net: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    bars_held: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
                                                 nullable=False)
