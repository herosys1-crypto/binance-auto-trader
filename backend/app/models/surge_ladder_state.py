"""🎯 급등 정점 사다리의 심볼별 상태 (Fix 267, alembic 0034).

🚨 **Redis 가 아니라 DB 인 이유**

`docker-compose.yml` 의 redis 서비스에는 volume 도 `--appendonly yes` 도 **없다**.
재기동 한 번이면 카운터가 0 이 된다. 시도 횟수·누적 손실을 Redis 에 두면
**이미 크게 잃은 심볼에 다시 자본이 나간다** — 사장님이 직접 인정하신
"큰손실 후 무리한 투자로 손실 반복"(사상 ⑦)을 시스템이 자동 재현하는 경로다.

기획서: docs/spec/SURGE_TOP10_PEAK_LADDER_SPEC_2026-09-01.md
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime, Integer, Numeric, String, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SurgeLadderState(Base):
    __tablename__ = "surge_ladder_state"
    __table_args__ = (
        UniqueConstraint("symbol", "side", name="uq_surge_ladder_symbol_side"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False, default="SHORT")

    # WATCH | IN_POSITION | WAITING | COOLDOWN | DONE
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="WATCH")
    # 몇 번째 시도인가 (0 = 아직 진입 전). 자본을 좌우하므로 반드시 영속화한다.
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 이번 시도에서 「이익 구간 추가」를 몇 번 했는가 (상한 MAX_ADDS)
    adds_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 신고점 추적 — SHORT 이므로 **고가**가 불리 방향 극값이다
    peak_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    peak_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    base_capital: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    current_capital: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    # 이번 사이클에서 이미 확정된 손실 (양수 = 손실). 상한 검사에 쓴다.
    cycle_loss_usdt: Mapped[Decimal] = mapped_column(
        Numeric(20, 8), nullable=False, default=0, server_default="0",
    )

    last_strategy_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_stop_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cycle_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
