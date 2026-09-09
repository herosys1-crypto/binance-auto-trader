"""🧭 ManagedSymbol = 「심볼 관리 재진입」 명부 한 행 (Fix 365, 2026-09-09).

사장님: "첫 진입에 실패하면 청산하고 재진입 모니터링으로 특별 관리해서 우선 포지션 진입할 심볼로 관리를 하고
        재진입 모니터링 후 다시 10usdt로 진입해서 성공하면 포지션추가로 가는걸로 해줘 10usdt로 성공할때까지
        10번까지 반복해줘 … 롱이든 숏이든 실패하면 재진입 모니터링관리와 모니터링후 포지션 진입 …
        한번 선택한 종목을 지속적으로 분석하면서 관리 재진입하는거야"

한 행 = 심볼 하나. 사장님이 OBV 자동 모달로 만든 인스턴스가 종료되는 순간 등록되고, 워커가 1분마다 롱·숏 신호를 본다.
로직: app/services/managed_symbols.py / 워커: app/workers/managed_symbol_worker.py
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ManagedSymbol(Base):
    __tablename__ = "managed_symbols"
    __table_args__ = (UniqueConstraint("symbol", name="uq_managed_symbol"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exchange_account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    strategy_template_id: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 기준 템플릿(10/300/600/600)
    templates: Mapped[dict | None] = mapped_column(JSONB, nullable=True)               # {"LONG": tpl_id, "SHORT": tpl_id}

    status: Mapped[str] = mapped_column(String(12), nullable=False, default="WATCHING", index=True)  # WATCHING / EXHAUSTED / RELEASED
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)       # 연속 실패(첫 실패 포함)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=10)  # 사장님 「10번까지」
    successes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_entries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 워커가 낸 재진입 수

    origin_instance_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_instance_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 마지막으로 집계한 종료 인스턴스
    last_side: Mapped[str | None] = mapped_column(String(5), nullable=True)
    last_pnl: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    last_exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_entry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_signal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_reasons: Mapped[dict | None] = mapped_column(JSONB, nullable=True)         # {"LONG": "...", "SHORT": "...", "state": "..."}
    counted_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)          # 집계한 종료 인스턴스 id 목록 (워터마크 대신, Fix 365b)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
