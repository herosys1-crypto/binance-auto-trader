from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.crypto import decrypt_text
from app.repositories.exchange_account_repository import ExchangeAccountRepository
from app.repositories.strategy_repository import StrategyRepository
from app.schemas.strategy import (
    StagePlanPreview,
    StrategyActionResponse,
    StrategyCalculateRequest,
    StrategyCalculateResponse,
    StrategyCreateRequest,
    StrategyDetailResponse,
    StrategyInstanceResponse,
    StrategyStopRequest,
)
from app.services.execution_service import ExecutionService
from app.services.strategy_calculator import StrategyCalculator, SymbolRule
from app.services.strategy_service import StrategyService

router = APIRouter(prefix="/strategies", tags=["strategies"])


class PreviewInlineRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=30)
    side: Literal["LONG", "SHORT"]
    start_price: Decimal = Field(..., gt=0)
    capitals: list[Decimal] = Field(..., min_length=1, max_length=10)
    trigger_percents: list[Decimal | None] | None = None
    leverage: int | None = None  # None 이면 SHORT=2, LONG=1 자동
    tp1_percent: Decimal = Field(default=Decimal("10"))
    tp2_percent: Decimal = Field(default=Decimal("20"))
    tp3_percent: Decimal = Field(default=Decimal("30"))
    tp4_percent: Decimal | None = Field(default=None)
    tp5_percent: Decimal | None = Field(default=None)
    stop_loss_percent_of_capital: Decimal = Field(default=Decimal("50"))
    last_stage_trigger_mode: str | None = None
    last_stage_trigger_percent: Decimal | None = None


@router.post("/preview-inline", response_model=StrategyCalculateResponse)
def preview_inline(
    payload: PreviewInlineRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyCalculateResponse:
    """DB 에 템플릿을 만들지 않고 즉석 미리보기 계산만 수행한다.

    대시보드 '직접 입력' 모드의 [미리보기] 버튼 전용. 매번 DB 에 임시 템플릿이
    누적되는 문제 방지.
    """
    symbol_model = StrategyRepository(db).get_symbol(payload.symbol)
    if not symbol_model:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Symbol not synced: {payload.symbol}")

    leverage = payload.leverage if payload.leverage is not None else (2 if payload.side == "SHORT" else 1)
    total_capital = sum(payload.capitals)

    stages_config: dict = {
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

    symbol_rule = SymbolRule(
        symbol=symbol_model.symbol,
        tick_size=Decimal(symbol_model.tick_size or 0),
        step_size=Decimal(symbol_model.step_size or 0),
        min_qty=Decimal(symbol_model.min_qty or 0),
        price_precision=symbol_model.price_precision or 8,
        quantity_precision=symbol_model.quantity_precision or 8,
    )
    calculator = StrategyCalculator(symbol_rule)
    try:
        preview = calculator.calculate_preview(
            symbol=payload.symbol,
            side=payload.side,
            start_price=payload.start_price,
            stages_config=stages_config,
            leverage=leverage,
            total_capital=total_capital,
            tp1_percent=payload.tp1_percent,
            tp2_percent=payload.tp2_percent,
            tp3_percent=payload.tp3_percent,
            stop_loss_percent_of_capital=payload.stop_loss_percent_of_capital,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    return StrategyCalculateResponse(
        symbol=preview.symbol,
        side=preview.side,
        leverage=preview.leverage,
        stages=[StagePlanPreview(**s.__dict__) for s in preview.stages],
        tp1_percent=preview.tp1_percent,
        tp2_percent=preview.tp2_percent,
        tp3_percent=preview.tp3_percent,
        stop_loss_amount=preview.stop_loss_amount,
    )


@router.post("/calculate", response_model=StrategyCalculateResponse)
def calculate_preview(
    payload: StrategyCalculateRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyCalculateResponse:
    try:
        preview = StrategyService(db).calculate_preview(
            symbol=payload.symbol,
            side=payload.side,
            start_price=payload.start_price,
            strategy_template_id=payload.strategy_template_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return StrategyCalculateResponse(
        symbol=preview.symbol,
        side=preview.side,
        leverage=preview.leverage,
        stages=[StagePlanPreview(**s.__dict__) for s in preview.stages],
        tp1_percent=preview.tp1_percent,
        tp2_percent=preview.tp2_percent,
        tp3_percent=preview.tp3_percent,
        stop_loss_amount=preview.stop_loss_amount,
    )


@router.post("", response_model=StrategyDetailResponse, status_code=status.HTTP_201_CREATED)
def create_strategy(
    payload: StrategyCreateRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyDetailResponse:
    try:
        instance = StrategyService(db).create_strategy_instance(
            user_id=user_id,
            exchange_account_id=payload.exchange_account_id,
            strategy_template_id=payload.strategy_template_id,
            symbol=payload.symbol,
            side=payload.side,
            start_price=payload.start_price,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return StrategyDetailResponse.model_validate(instance)


@router.get("", response_model=list[StrategyDetailResponse])
def list_strategies(
    status_filter: str | None = None,
    symbol: str | None = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[StrategyDetailResponse]:
    """전략 인스턴스 목록 — 대시보드 표시를 위해 detail 필드까지 포함."""
    rows = StrategyRepository(db).list_strategies(user_id=user_id, status=status_filter, symbol=symbol)
    return [StrategyDetailResponse.model_validate(r) for r in rows]


@router.get("/{strategy_id}", response_model=StrategyDetailResponse)
def get_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyDetailResponse:
    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")
    return StrategyDetailResponse.model_validate(strategy)


@router.get("/{strategy_id}/stage-plans")
def get_strategy_stage_plans(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[dict]:
    """전략의 단계별 계획 + 트리거 상태 반환. 대시보드 상세 패널용."""
    from app.models.strategy_stage_plan import StrategyStagePlan
    from sqlalchemy import select as sa_select

    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")
    rows = db.execute(
        sa_select(StrategyStagePlan)
        .where(StrategyStagePlan.strategy_instance_id == strategy_id)
        .order_by(StrategyStagePlan.stage_no.asc())
    ).scalars().all()
    return [
        {
            "stage_no": r.stage_no,
            "trigger_mode": r.trigger_mode,
            "trigger_percent": str(r.trigger_percent) if r.trigger_percent is not None else None,
            "trigger_price": str(r.trigger_price) if r.trigger_price is not None else None,
            "planned_capital": str(r.planned_capital),
            "planned_qty": str(r.planned_qty) if r.planned_qty is not None else None,
            "is_enabled": r.is_enabled,
            "is_triggered": r.is_triggered,
            "triggered_at": r.triggered_at.isoformat() if r.triggered_at else None,
        }
        for r in rows
    ]


@router.get("/{strategy_id}/blueprint")
def get_strategy_blueprint(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """이전 전략의 모든 설정을 한 번에 반환 — 새 전략 시작 모달에서 재사용용.

    반환: {
      symbol, side, leverage, exchange_account_id, start_price,
      capitals: [...], trigger_percents: [...],
      tp1_percent, tp2_percent, tp3_percent,
      tp1_qty_ratio, tp2_qty_ratio, tp3_qty_ratio,
      stop_loss_percent_of_capital,
      last_stage_trigger_mode, last_stage_trigger_percent,
    }
    """
    from app.models.strategy_template import StrategyTemplate

    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")
    tpl = db.get(StrategyTemplate, strategy.strategy_template_id)
    if not tpl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template missing")

    sc = tpl.stages_config or {}
    return {
        "source_strategy_id": strategy.id,
        "symbol": strategy.symbol,
        "side": strategy.side,
        "leverage": tpl.leverage,
        "exchange_account_id": strategy.exchange_account_id,
        "start_price": str(strategy.start_price) if strategy.start_price else None,
        "capitals": sc.get("capitals") or [],
        "trigger_percents": sc.get("trigger_percents") or [],
        "last_stage_trigger_mode": sc.get("last_stage_trigger_mode"),
        "last_stage_trigger_percent": sc.get("last_stage_trigger_percent"),
        "tp1_percent": str(tpl.tp1_percent),
        "tp2_percent": str(tpl.tp2_percent),
        "tp3_percent": str(tpl.tp3_percent),
        "tp4_percent": str(tpl.tp4_percent) if tpl.tp4_percent is not None else None,
        "tp5_percent": str(tpl.tp5_percent) if tpl.tp5_percent is not None else None,
        "tp1_qty_ratio": str(tpl.tp1_qty_ratio),
        "tp2_qty_ratio": str(tpl.tp2_qty_ratio),
        "tp3_qty_ratio": str(tpl.tp3_qty_ratio),
        "tp4_qty_ratio": str(tpl.tp4_qty_ratio) if tpl.tp4_qty_ratio is not None else None,
        "tp5_qty_ratio": str(tpl.tp5_qty_ratio) if tpl.tp5_qty_ratio is not None else None,
        "stop_loss_percent_of_capital": str(tpl.stop_loss_percent_of_capital),
    }


@router.post("/{strategy_id}/start", response_model=StrategyActionResponse)
def start_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyActionResponse:
    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")

    account = ExchangeAccountRepository(db).get(strategy.exchange_account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Exchange account not found")

    try:
        execution_service = ExecutionService(
            db,
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=account.is_testnet,
        )
        execution_service.start_stage1(strategy.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:  # pragma: no cover - upstream/network faults bubble up
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Exchange error: {e}") from e

    db.refresh(strategy)
    return StrategyActionResponse(
        strategy_id=strategy.id,
        status=strategy.status,
        message="Stage 1 order submitted",
    )


@router.post("/{strategy_id}/force-stop", response_model=StrategyActionResponse)
def force_stop_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyActionResponse:
    """거래소 호출 없이 DB 상에서만 전략을 STOPPED 로 마킹한다.

    사용 사례:
    - 거래소 API 키가 깨져서 일반 /stop 이 실패하는 고립 전략
    - 미체결 주문이 이미 거래소에서 사라진(만료/수동취소) 후 DB 만 남은 전략
    - 테스트/실험용 미사용 strategy 정리

    포지션이 거래소에 남아있을 수 있으니 운영자가 직접 확인 후 사용 권장.
    """
    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")
    strategy.status = "STOPPED"
    strategy.reentry_ready = False
    db.commit()
    db.refresh(strategy)
    return StrategyActionResponse(
        strategy_id=strategy.id,
        status=strategy.status,
        message="DB 상에서만 STOPPED 로 마킹됨 (거래소 호출 없음)",
    )


@router.post("/{strategy_id}/stop", response_model=StrategyActionResponse)
def stop_strategy(
    strategy_id: int,
    payload: StrategyStopRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyActionResponse:
    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")

    account = ExchangeAccountRepository(db).get(strategy.exchange_account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Exchange account not found")

    execution_service = ExecutionService(
        db,
        api_key=decrypt_text(account.api_key_enc),
        api_secret=decrypt_text(account.api_secret_enc),
        is_testnet=account.is_testnet,
    )

    message = ""
    try:
        if payload.mode == "cancel_only":
            execution_service.client.cancel_all_orders(symbol=strategy.symbol)
            strategy.status = "STOPPING"
            db.commit()
            message = "All open orders cancelled"
        elif payload.mode in {"close_position_market", "emergency_stop"}:
            execution_service.client.cancel_all_orders(symbol=strategy.symbol)
            qty = Decimal(str(strategy.current_position_qty or 0)).copy_abs()
            if qty > 0:
                execution_service.emergency_close_position(strategy.id, quantity=qty)
            strategy.status = "STOPPING"
            db.commit()
            message = "Position closed at market"
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Exchange error: {e}") from e

    db.refresh(strategy)
    return StrategyActionResponse(strategy_id=strategy.id, status=strategy.status, message=message)
