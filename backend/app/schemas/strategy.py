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
    # 2026-05-11 (사용자 요청): 단계별 추가 증거금 (USDT). 미리보기 테이블 노출용.
    # None/0 = 추가 안 함. StagePlan dataclass.__dict__ 에서 그대로 전달.
    additional_margin_usdt: Decimal | None = None

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
    # 2026-06-05 fix (사장님 진단 박스 발견):
    # frontend strategies-list.js 의 Binance 비교 인라인 행 (PR #39) 이
    # s.exchange_account_id 필드 사용 → activeAccountIds 추출 → /binance-positions fetch.
    # 그러나 이 schema 에 필드 누락 → frontend = undefined → fetch skip → Binance 비교 행 표시 안 됨.
    # DB column 은 존재 (StrategyInstance.exchange_account_id), schema 만 노출 빠뜨림.
    exchange_account_id: int | None = None
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
    # ─── 사장님 trailing retrace 옵션 (alembic 0017, 2026-06-08) ───
    # peak 대비 -X% 회귀 시 전량 청산 (TRAILING_TP).
    # NULL/5 = default, 10/15/20 = 사장님 선택. 운영 중 실시간 변경.
    trailing_retrace_pct: Decimal | None = None
    # ─── 사장님 TP1 임계 옵션 (alembic 0018, 2026-06-08) ───
    # 정상 모드 = 사장님 옵션 (10/15/20/25) 적용
    # Crisis 모드 = 옵션 무시 = 옛 CRISIS_OVERRIDE 그대로 (TP1=5)
    # NULL = template default. 운영 중 PATCH 실시간 변경.
    tp1_pct_override: Decimal | None = None
    # ─── 손실 한도 강제 청산 전략별 override (alembic 0020, 2026-06-24) ───
    # NULL = 전역 설정 상속. enabled True/False + roi 5/10/15/20 = 전략 우선.
    # spec: FORCE_SL_LOSS_LIMIT_SPEC_2026-06-24.md
    force_sl_enabled_override: bool | None = None
    force_sl_roi_override: Decimal | None = None
    # ─── 진입 일시 (대시보드 표시용) ───
    created_at: datetime | None = None       # strategy 생성 시점
    # 2026-05-21 STOPPING 갇힘 감지용 — frontend 가 updated_at 기준 5분 초과 시
    # 「⚠️ 갇힘 N분」 배지 + 상단 경고 표시. 다른 status 에서도 단순 표시용으로 사용.
    updated_at: datetime | None = None       # 마지막 status/필드 변경 시점
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
    # 2026-06-03 신규 (사장님 SL 한도 시각화): template 의 stop_loss_percent_of_capital.
    # frontend 「전략 인스턴스」 카드에 SL 한도 (total_capital × sl_pct / 100) 표시용.
    # 사장님 사상 (PR #57): SL = 투자금 대비 손실 % (레버리지 무관) → SL 한도 USDT 즉시 계산 가능.
    stop_loss_percent_of_capital: Decimal | None = None
    # ─── Soft delete (2026-05-06 PR #7 + C-full) ───
    # is_archived=true 면 default UI list 에서 숨김. ?include_archived=true 로 조회 시 표시 +
    # 「↻ 복원」 버튼 노출. archived_at 은 archive 시점 (audit log).
    is_archived: bool = False
    archived_at: datetime | None = None
