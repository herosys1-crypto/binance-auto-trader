from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.crypto import decrypt_text
from app.integrations.binance.client import BinanceClient
from app.models.strategy_template import StrategyTemplate
from app.repositories.exchange_account_repository import ExchangeAccountRepository
from app.schemas.common import MessageResponse
from app.services.account_kill_switch_service import AccountKillSwitchService
from app.services.notification_service import NotificationService
from app.services.symbol_sync_service import SymbolSyncService

router = APIRouter(prefix="/admin", tags=["admin"])


# =====================================================================
# Strategy template (동적 N단계) — 운영자 입력
# =====================================================================
class StrategyTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    strategy_type: str = Field(..., min_length=1, max_length=40)
    side: Literal["LONG", "SHORT"]
    leverage: int = Field(..., ge=1, le=125)
    capitals: list[Decimal] = Field(..., min_length=1, max_length=10, description="단계별 투자금액 (1~10 단계)")
    trigger_percents: list[Decimal | None] | None = Field(
        default=None,
        description="단계별 trigger_percent (None 이면 기본 10%). 길이는 capitals 와 같아야 함",
    )
    last_stage_trigger_mode: str | None = Field(
        default=None,
        description="마지막 단계 trigger_mode. 미지정 시 SHORT=LIQUIDATION_BUFFER, LONG=PRICE_DOWN_PCT",
    )
    last_stage_trigger_percent: Decimal | None = Field(
        default=None,
        description="마지막 단계 trigger_percent. 미지정 시 SHORT=5, LONG=20",
    )
    tp1_percent: Decimal = Field(..., gt=0)
    tp2_percent: Decimal = Field(..., gt=0)
    tp3_percent: Decimal = Field(..., gt=0)
    tp1_qty_ratio: Decimal = Field(..., gt=0, le=100)
    tp2_qty_ratio: Decimal = Field(..., gt=0, le=100)
    tp3_qty_ratio: Decimal = Field(..., gt=0, le=100)
    stop_loss_percent_of_capital: Decimal = Field(..., gt=0, le=100)
    reentry_policy: str = "manual_ready"


class StrategyTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    strategy_type: str
    side: str
    leverage: int
    total_capital: Decimal
    stages_config: dict | None = None
    tp1_percent: Decimal
    tp2_percent: Decimal
    tp3_percent: Decimal
    is_active: bool


@router.post("/strategy-templates", response_model=StrategyTemplateResponse, status_code=status.HTTP_201_CREATED)
def create_strategy_template(
    payload: StrategyTemplateCreate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyTemplateResponse:
    """동적 N단계 (1~10) 전략 템플릿을 생성한다."""
    if payload.trigger_percents is not None and len(payload.trigger_percents) != len(payload.capitals):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="trigger_percents length must match capitals length",
        )

    total_capital = sum(payload.capitals)
    stages_config = {
        "capitals": [str(c) for c in payload.capitals],
        "trigger_percents": (
            [str(p) if p is not None else None for p in payload.trigger_percents]
            if payload.trigger_percents
            else [None] * len(payload.capitals)
        ),
    }
    if payload.last_stage_trigger_mode:
        stages_config["last_stage_trigger_mode"] = payload.last_stage_trigger_mode
    if payload.last_stage_trigger_percent is not None:
        stages_config["last_stage_trigger_percent"] = str(payload.last_stage_trigger_percent)

    template = StrategyTemplate(
        name=payload.name,
        strategy_type=payload.strategy_type,
        side=payload.side,
        leverage=payload.leverage,
        total_capital=total_capital,
        stages_config=stages_config,
        # 구 컬럼은 호환을 위해 채울 수 있으면 채움 (4단계인 경우만)
        stage1_capital=payload.capitals[0] if len(payload.capitals) >= 1 else None,
        stage2_capital=payload.capitals[1] if len(payload.capitals) >= 2 else None,
        stage3_capital=payload.capitals[2] if len(payload.capitals) >= 3 else None,
        stage4_capital=payload.capitals[3] if len(payload.capitals) >= 4 else None,
        tp1_percent=payload.tp1_percent,
        tp2_percent=payload.tp2_percent,
        tp3_percent=payload.tp3_percent,
        tp1_qty_ratio=payload.tp1_qty_ratio,
        tp2_qty_ratio=payload.tp2_qty_ratio,
        tp3_qty_ratio=payload.tp3_qty_ratio,
        stop_loss_percent_of_capital=payload.stop_loss_percent_of_capital,
        reentry_policy=payload.reentry_policy,
        is_active=True,
    )
    db.add(template)
    try:
        db.commit()
        db.refresh(template)
    except Exception as e:  # pragma: no cover
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return StrategyTemplateResponse.model_validate(template)


@router.get("/strategy-templates", response_model=list[StrategyTemplateResponse])
def list_strategy_templates(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[StrategyTemplateResponse]:
    rows = db.query(StrategyTemplate).order_by(StrategyTemplate.id.desc()).all()
    return [StrategyTemplateResponse.model_validate(r) for r in rows]


@router.post("/test-telegram", response_model=MessageResponse)
def test_telegram(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> MessageResponse:
    try:
        NotificationService(db).send_system_alert(
            title="[관리 테스트] Telegram alert",
            body="This is a Telegram connectivity test from the admin API.",
        )
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    return MessageResponse(message="Telegram test sent")


@router.post("/symbol-sync", response_model=MessageResponse)
def symbol_sync(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> MessageResponse:
    account = ExchangeAccountRepository(db).get_first_active_binance()
    if not account:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No active Binance account")
    client = BinanceClient(
        api_key=decrypt_text(account.api_key_enc),
        api_secret=decrypt_text(account.api_secret_enc),
        is_testnet=account.is_testnet,
    )
    count = SymbolSyncService(db, client).sync()
    return MessageResponse(message=f"Synced {count} symbols")


@router.post("/kill-switch/{exchange_account_id}/enable", response_model=MessageResponse)
def enable_kill_switch(
    exchange_account_id: int,
    reason_code: str = "MANUAL",
    reason_message: str = "Manually triggered by admin",
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> MessageResponse:
    AccountKillSwitchService(db).trigger(
        exchange_account_id=exchange_account_id,
        reason_code=reason_code,
        reason_message=reason_message,
    )
    return MessageResponse(message=f"Kill switch enabled on account {exchange_account_id}")


@router.post("/kill-switch/{exchange_account_id}/disable", response_model=MessageResponse)
def disable_kill_switch(
    exchange_account_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> MessageResponse:
    AccountKillSwitchService(db).clear(exchange_account_id)
    return MessageResponse(message=f"Kill switch cleared on account {exchange_account_id}")
