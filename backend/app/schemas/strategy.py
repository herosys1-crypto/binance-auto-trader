from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

StrategySide = Literal["LONG", "SHORT"]

class StagePlanPreview(BaseModel):
    stage_no: int
    trigger_mode: str
    trigger_percent: Decimal | None = None
    trigger_price: Decimal | None = None
    planned_capital: Decimal
    planned_qty: Decimal | None = None

class StrategyCalculateRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=30)
    side: StrategySide
    start_price: Decimal = Field(..., gt=0)
    strategy_template_id: int

class StrategyCalculateResponse(BaseModel):
    symbol: str
    side: StrategySide
    leverage: int
    stages: list[StagePlanPreview]
    tp1_percent: Decimal
    tp2_percent: Decimal
    tp3_percent: Decimal
    stop_loss_amount: Decimal

class StrategyCreateRequest(BaseModel):
    exchange_account_id: int
    strategy_template_id: int
    symbol: str
    side: StrategySide
    start_price: Decimal = Field(..., gt=0)
    # UX #18 (2026-04-29): 사용자가 템플릿 기본 레버리지를 override 할 수 있게 지원.
    # None 이면 템플릿 leverage 사용. 1~125 범위.
    leverage_override: int | None = Field(default=None, ge=1, le=125)

class StrategyStopRequest(BaseModel):
    mode: Literal["cancel_only", "close_position_market", "emergency_stop"]
    reason: str | None = None

class StrategyActionResponse(BaseModel):
    strategy_id: int
    status: str
    message: str

class StrategyInstanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    symbol: str
    side: StrategySide
    status: str
    reentry_ready: bool

class StrategyDetailResponse(StrategyInstanceResponse):
    leverage: int
    current_stage: int
    start_price: Decimal | None = None      # 운영자가 입력한 1단계 LIMIT 진입요청가
    avg_entry_price: Decimal | None = None
    current_position_qty: Decimal
    invested_capital: Decimal
    total_capital: Decimal | None = None    # 템플릿의 총 자본 (모든 단계 합계) — 마진 계산용
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    liquidation_price: Decimal | None = None
    # ─── 크라이시스 복구 모드 + PnL 추적 (Phase D) ───
    max_loss_pct: Decimal | None = None
    max_profit_pct: Decimal | None = None
    crisis_mode_triggered_at: datetime | None = None
    crisis_first_tp_done_at: datetime | None = None
    peak_pnl_pct_after_first_tp: Decimal | None = None
    # ─── 진입 일시 (대시보드 표시용) ───
    created_at: datetime | None = None       # strategy 생성 시점
    # ─── UI 진행도 표시 분모 (동적) ───
    # template 의 활성 단계 수 (stages_config.capitals 의 NOT NULL/0 카운트, 1~10)
    # template 의 활성 TP 수 (tp1~5_percent 의 NOT NULL 카운트, 1~5)
    # default 4 로 두면 backward-compat (이전 frontend 도 동작)
    total_active_stages: int = 4
    total_active_tps: int = 4
    # ─── 실제 TP 발동 카운트 + 종료 사유 (UI 정확 표시용, 2026-05-03 fix) ───
    # tp_triggered_count: notifications 의 [TPN 익절 체결] 카운트 (TRAILING 제외)
    # last_close_reason: TP_FINAL / TRAILING / SL / MANUAL / NONE
    tp_triggered_count: int = 0
    last_close_reason: str = "NONE"
    # ─── Soft delete (2026-05-06 PR #7 + C-full) ───
    # is_archived=true 면 default UI list 에서 숨김. ?include_archived=true 로 조회 시 표시 +
    # 「↻ 복원」 버튼 노출. archived_at 은 archive 시점 (audit log).
    is_archived: bool = False
    archived_at: datetime | None = None
