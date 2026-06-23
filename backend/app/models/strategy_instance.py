from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, func, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

class StrategyInstance(Base):
    __tablename__ = "strategy_instances"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    exchange_account_id: Mapped[int] = mapped_column(ForeignKey("exchange_accounts.id"), nullable=False, index=True)
    strategy_template_id: Mapped[int] = mapped_column(ForeignKey("strategy_templates.id"), nullable=False, index=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id"), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    start_price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    leverage: Mapped[int] = mapped_column(Integer, nullable=False)
    total_capital: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    current_stage: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    avg_entry_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    current_position_qty: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    invested_capital: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    liquidation_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="WAITING", nullable=False, index=True)
    reentry_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ─────────── 크라이시스 복구 모드 + PnL 추적 (alembic 0006) ───────────
    # 누적 최대 손실 % (음수, e.g. -32.5) — 진입 후 가장 깊었던 손실 기록
    max_loss_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    # 누적 최대 이익 % — 진입 후 가장 컸던 이익 기록
    max_profit_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    # 크라이시스 모드 진입 시각 (NULL = 미진입)
    crisis_mode_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 크라이시스 모드의 첫 TP (+5%) 발동 시각 — Stage 2 보호 활성화 기준점
    crisis_first_tp_done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 첫 TP 발동 후 피크 PnL % — 트레일링 -5% 계산용
    peak_pnl_pct_after_first_tp: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)

    # ─────────── 사장님 trailing retrace 옵션 (alembic 0017, 2026-06-08) ───────────
    # peak 대비 -X% 회귀 시 전량 청산 (TRAILING_TP).
    # NULL/5 = default (옛 동작), 10/15/20 = 사장님 선택 (= buffer 더 큼)
    # 운영 중 PATCH /strategies/{id}/trailing-retrace = 실시간 변경
    # spec: TRAILING_RETRACE_POLICY_SPEC_2026-06-08.md
    trailing_retrace_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    # ─────────── 사장님 TP1 임계 옵션 (alembic 0018, 2026-06-08) ───────────
    # 정상 모드 = 사장님 옵션 (10/15/20/25) 적용 (NULL = template default 10)
    # Crisis 모드 = 사장님 옵션 무시 = 옛 CRISIS_OVERRIDE 그대로 (TP1=5/2=10/3=15/4=20)
    # 운영 중 PATCH /strategies/{id}/tp1-threshold = 실시간 변경
    # spec: TP1_THRESHOLD_OPTION_SPEC_2026-06-08.md
    tp1_pct_override: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    # ─────────── 손실 한도 강제 청산 전략별 override (alembic 0020, 2026-06-24) ───────────
    # 전역 설정(system_settings.force_sl_*) = 모든 전략 기본 + 전략별 override 우선 (NULL=전역 상속).
    # 사장님 명시: "모두에게 같은 적용을 하는데 각각의 전략에 우선하는 방식으로 만들어줘"
    # enabled_override: NULL=전역 따름, True/False=전략 강제 on/off
    # roi_override:     NULL=전역 따름, 5/10/15/20=전략 한도(%) (ROI <= -값 시 발동)
    # 운영 중 PATCH /strategies/{id}/force-sl = 실시간 변경
    # spec: FORCE_SL_LOSS_LIMIT_SPEC_2026-06-24.md
    force_sl_enabled_override: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    force_sl_roi_override: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    # ─────────── Soft delete (alembic 0011, 2026-05-06) ───────────
    # DELETE endpoint 와 cleanup 스크립트가 row 자체를 삭제하면 realized_pnl 이
    # 통계 합계에서 영구 누락 (#96 +867 USDT 사례). 삭제 대신 archived 마킹.
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", back_populates="strategy_instances")
    exchange_account = relationship("ExchangeAccount", back_populates="strategy_instances")
    strategy_template = relationship("StrategyTemplate", back_populates="strategy_instances")
    symbol_ref = relationship("Symbol", back_populates="strategy_instances")
    stage_plans = relationship("StrategyStagePlan", back_populates="strategy_instance", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="strategy_instance", cascade="all, delete-orphan")
    positions = relationship("Position", back_populates="strategy_instance", cascade="all, delete-orphan")
    risk_events = relationship("RiskEvent", back_populates="strategy_instance", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="strategy_instance")
