from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, func, Numeric
from sqlalchemy.dialects.postgresql import JSONB
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

    # ─────────── 청산 후 자동 재진입 + 자본 관리 (alembic 0023, 2026-08-09) ───────────
    # 사장님 신 사상 v131 = 1단계 청산 → 트리거 도달 → 다음 단계 자동 진입!
    # 자본 관리 = 이전 손실만큼 자동 차감 (사장님 정확 통제!)
    # 실용 한계 = 2~3단계! (사장님 인식!)
    # spec: docs/AUTO_RETRY_AFTER_LIQUIDATION_SPEC_v131.md
    #
    # 활성 여부 (default=False = 옛 동작! 옵션 켜야 활성!)
    retry_after_liquidation_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 재진입 트리거 % (레버리지 무관!) - 청산가 기준 ±% (= 기본값!)
    retry_trigger_pct: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("10"), nullable=False)
    # 🌟 v131 신 (alembic 0024, 2026-08-09 사장님!): 단계별 재진입 트리거 개별 세팅!
    # 사장님 사고: "기본세팅은 유효해야 하고 개별세팅이 우선하는거야"
    # = 하이브리드 = 사장님 시장 분석 → 단계별 개별 트리거!
    # 값 예: {} (모두 기본!) / {"3": 15, "4": 20} (3/4단계만 개별!)
    # 우선순위: 개별값 있음 → 개별값 / 없음 or null → retry_trigger_pct 기본값!
    retry_stage_trigger_pcts: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # 자본 관리 모드 = 'fixed' (그대로) or 'auto_deduct' (손실 차감)
    capital_management_mode: Mapped[str] = mapped_column(String(20), default="fixed", nullable=False)
    # 누적 실현 손실 (USDT!) - 자본 차감 계산용!
    cumulative_realized_loss: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"), nullable=False)
    # 마지막 청산가 - 다음 단계 트리거 기준!
    last_liquidation_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)

    # ─────────── 저항 반전 SHORT (alembic 0032, 2026-08-23 v228 Fix 29) ───────────
    # 사장님 verbatim: "전고점 13354가 최대 저항 = 돌파 후 하락 시 2단계 진입"
    # 사용자 지정 우선 (source='user') / 없으면 7일 15m 최고가 자동 감지 (source='auto_7d_15m')
    # spec: docs/RESISTANCE_REVERSAL_SHORT_SPEC_v1.md
    resistance_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    resistance_source: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 'user' | 'auto_7d_15m'
    resistance_detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 24h TTL
    resistance_reversal_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # idempotency

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
