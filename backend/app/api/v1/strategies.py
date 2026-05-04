from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.crypto import decrypt_text
from app.core.strategy_status import TERMINAL_STATUSES
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


def _count_active_stages(tpl) -> int:
    """Template 의 활성 단계 수 — stages_config.capitals 중 0/None 아닌 항목 카운트.

    옵션 C (1~10단계 동적). 결과 fallback 4 (backward-compat).
    """
    if not tpl:
        return 4
    cfg = getattr(tpl, "stages_config", None) or {}
    capitals = cfg.get("capitals") or []
    n = sum(1 for c in capitals if c not in (None, "") and Decimal(str(c)) > 0)
    return n if n > 0 else 4


def _count_active_tps(tpl) -> int:
    """Template 의 활성 TP 수 — tp1~5_percent 중 NOT NULL 카운트.

    1~5 동적. 결과 fallback 4 (backward-compat).
    """
    if not tpl:
        return 4
    n = sum(1 for i in range(1, 6) if getattr(tpl, f"tp{i}_percent", None) is not None)
    return n if n > 0 else 4


def _enrich_response(resp: StrategyDetailResponse, tpl) -> StrategyDetailResponse:
    """응답에 template 기반 카운트 채우기."""
    resp.total_active_stages = _count_active_stages(tpl)
    resp.total_active_tps = _count_active_tps(tpl)
    return resp


def _fetch_tp_counts_batch(db: Session, strategy_ids: set[int]) -> dict[int, dict]:
    """notifications 에서 strategy 별 TP 발동 카운트 + TRAILING 여부 batch fetch.

    N+1 방지: 모든 strategy 한 번에 query.
    Returns: {strategy_id: {"tp_count": int, "has_trailing": bool}}
    """
    if not strategy_ids:
        return {}
    from sqlalchemy import text
    # title 패턴:
    #   "[TP1 익절 체결]" / "[TP2 익절 체결]" / ... / "[TP5 익절 체결]"
    #   "[TRAILING_TP 익절 체결]"
    rows = db.execute(
        text("""
            SELECT strategy_instance_id,
                   COUNT(*) FILTER (
                     WHERE title ~ '\\[TP[1-5] 익절' AND title NOT LIKE '%TRAILING%'
                   ) AS tp_count,
                   BOOL_OR(title LIKE '%TRAILING_TP%') AS has_trailing
            FROM notifications
            WHERE strategy_instance_id = ANY(:ids)
              AND send_status IN ('SENT', 'PENDING')
            GROUP BY strategy_instance_id
        """),
        {"ids": list(strategy_ids)},
    ).all()
    return {r.strategy_instance_id: {"tp_count": r.tp_count or 0, "has_trailing": bool(r.has_trailing)} for r in rows}


def _resolve_close_reason(strategy, counts: dict, total_active_tps: int) -> str:
    """status + 발동 카운트로 마지막 종료 사유 추론.

    Returns: TP_FINAL / TRAILING / SL / MANUAL / NONE
    """
    st = (strategy.status or "").upper()
    tp_count = counts.get("tp_count", 0) if counts else 0
    has_trailing = counts.get("has_trailing", False) if counts else False
    if st in ("CLOSED_BY_SL", "STOPPED_BY_SL"):
        return "SL"
    if st == "STOPPED":
        return "MANUAL"
    if st == "COMPLETED" or st == "REENTRY_READY":
        if has_trailing:
            return "TRAILING"
        if tp_count >= total_active_tps:
            return "TP_FINAL"
        # 진입했는데 종료, TP/Trail 없음 → 기타 (예: SL fast path)
        return "SL" if tp_count == 0 else "TRAILING"
    return "NONE"


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
            leverage_override=payload.leverage_override,
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
    from app.models.strategy_template import StrategyTemplate
    rows = StrategyRepository(db).list_strategies(user_id=user_id, status=status_filter, symbol=symbol)
    # N+1 방지: distinct template_id 들을 한 번에 fetch.
    template_ids = {r.strategy_template_id for r in rows if r.strategy_template_id}
    templates = (
        {t.id: t for t in db.query(StrategyTemplate).filter(StrategyTemplate.id.in_(template_ids)).all()}
        if template_ids else {}
    )
    # TP 발동 카운트 + TRAILING 여부 batch fetch (UI 정확 표시용)
    strategy_ids = {r.id for r in rows}
    tp_counts = _fetch_tp_counts_batch(db, strategy_ids)
    out = []
    for r in rows:
        tpl = templates.get(r.strategy_template_id)
        resp = _enrich_response(StrategyDetailResponse.model_validate(r), tpl)
        cnt = tp_counts.get(r.id, {})
        resp.tp_triggered_count = cnt.get("tp_count", 0)
        resp.last_close_reason = _resolve_close_reason(r, cnt, resp.total_active_tps)
        out.append(resp)
    return out


@router.get("/{strategy_id}", response_model=StrategyDetailResponse)
def get_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyDetailResponse:
    from app.models.strategy_template import StrategyTemplate
    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")
    tpl = db.get(StrategyTemplate, strategy.strategy_template_id) if strategy.strategy_template_id else None
    resp = _enrich_response(StrategyDetailResponse.model_validate(strategy), tpl)
    counts = _fetch_tp_counts_batch(db, {strategy.id}).get(strategy.id, {})
    resp.tp_triggered_count = counts.get("tp_count", 0)
    resp.last_close_reason = _resolve_close_reason(strategy, counts, resp.total_active_tps)
    return resp


@router.get("/{strategy_id}/timeline")
def get_strategy_timeline(
    strategy_id: int,
    limit: int = 200,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[dict]:
    """전략의 활동 타임라인 — orders / risk_events / notifications 시간순 통합.

    각 항목 형식:
      { "ts": ISO8601, "kind": "ORDER"|"RISK"|"NOTIFY", "icon": "✅", "title": "...", "detail": "..." }

    프론트엔드 상세 패널에서 한눈에 "이 전략이 어떻게 흘러갔는지" 확인용.
    """
    from sqlalchemy import select as sa_select
    from app.models.order import Order
    from app.models.risk_event import RiskEvent
    from app.models.notification import Notification

    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")

    items: list[dict] = []

    # 주문 — 발송 시점 + 체결 시점
    orders = db.execute(
        sa_select(Order)
        .where(Order.strategy_instance_id == strategy_id)
        .order_by(Order.created_at.asc())
    ).scalars().all()
    for o in orders:
        purpose_ko = {"ENTRY": "진입", "TAKE_PROFIT": "익절", "STOP_LOSS": "손절", "EMERGENCY_CLOSE": "긴급청산"}.get(o.purpose, o.purpose)
        side_ko = "매도 📉" if o.side == "SELL" else "매수 📈"
        # 발송
        items.append({
            "ts": o.created_at.isoformat(),
            "kind": "ORDER",
            "icon": "📤",
            "title": f"{purpose_ko} 주문 발송 (#{o.id})",
            "detail": f"{side_ko} {o.order_type} @ {o.price} / 수량 {o.orig_qty}" + (f" — {o.stage_no}단계" if o.stage_no else ""),
        })
        # 체결 (status=FILLED 이고 updated_at 이 created_at 보다 늦으면)
        if (o.status or "").upper() == "FILLED" and o.updated_at and o.created_at and o.updated_at > o.created_at:
            items.append({
                "ts": o.updated_at.isoformat(),
                "kind": "ORDER",
                "icon": "✅",
                "title": f"{purpose_ko} 체결 (#{o.id})",
                "detail": f"{side_ko} {o.executed_qty} @ {o.avg_price}" + (f" — {o.stage_no}단계" if o.stage_no else ""),
            })

    # 리스크 이벤트 (크라이시스 진입, 손절 발동 등)
    risk_events = db.execute(
        sa_select(RiskEvent)
        .where(RiskEvent.strategy_instance_id == strategy_id)
        .order_by(RiskEvent.created_at.asc())
    ).scalars().all()
    for r in risk_events:
        sev_icon = {"CRITICAL": "🚨", "WARNING": "⚠️", "INFO": "ℹ️"}.get(r.severity, "📌")
        items.append({
            "ts": r.created_at.isoformat(),
            "kind": "RISK",
            "icon": sev_icon,
            "title": r.title or r.event_type,
            "detail": r.message or "",
        })

    # 알림 (Telegram 발송 등)
    notifications = db.execute(
        sa_select(Notification)
        .where(Notification.strategy_instance_id == strategy_id)
        .order_by(Notification.created_at.asc())
    ).scalars().all()
    for n in notifications:
        status_icon = "✉️" if (n.send_status or "").upper() == "SENT" else "❌"
        items.append({
            "ts": n.created_at.isoformat(),
            "kind": "NOTIFY",
            "icon": status_icon,
            "title": n.title or "알림",
            "detail": (n.body or "")[:200],
        })

    # 시간 역순 정렬 (최신이 위로)
    items.sort(key=lambda x: x["ts"], reverse=True)
    return items[:limit]


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
        # Bug #12 fix (2026-04-29): start_stage1 실패 시 DB 의 strategy 를 STOPPED
        # 로 마킹해서 orphan WAITING/PENDING 안 남김. 사용자는 retry 시 새 전략 만들면 됨.
        strategy.status = "STOPPED"
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:  # pragma: no cover - upstream/network faults bubble up
        # 거래소 에러 (PERCENT_PRICE filter, MIN_NOTIONAL 등) 시도 마찬가지
        strategy.status = "STOPPED"
        db.commit()
        # 친화적 메시지로 자주 나오는 Binance 에러 코드 매핑
        msg = str(e)
        if "-4016" in msg or "Limit price" in msg:
            hint = " (시작가가 현재 시세 대비 너무 멀어 거래소가 거절. 시작가를 현재가 ±1~2% 이내로 조정해주세요)"
        elif "-1111" in msg or "Precision" in msg:
            hint = " (수량 정밀도 문제. 자본 조정 필요)"
        elif "-4131" in msg or "MIN_NOTIONAL" in msg:
            hint = " (주문 금액이 최소 거래 금액 미만. 자본 늘리세요)"
        else:
            hint = ""
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Exchange error: {e}{hint}") from e

    db.refresh(strategy)
    # 전략 시작 즉시 텔레그램 알림 (체결 무관 — 미체결로 한참 기다려도 사용자가 확인 가능).
    try:
        from app.services.notification_service import NotificationService
        NotificationService(db).send_strategy_started_alert(
            strategy_instance_id=strategy.id,
            symbol=strategy.symbol,
            side=strategy.side,
            start_price=strategy.start_price,
            leverage=strategy.leverage,
            total_capital=strategy.total_capital,
        )
    except Exception:  # 알림 실패해도 거래 로직 영향 없음
        pass
    return StrategyActionResponse(
        strategy_id=strategy.id,
        status=strategy.status,
        message="Stage 1 order submitted",
    )


class AddMarginRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, description="추가할 증거금 (USDT, 양수). 거래소 ISOLATED 모드 포지션에만 가능.")


@router.post("/{strategy_id}/add-margin", response_model=StrategyActionResponse)
def add_margin_to_strategy(
    strategy_id: int,
    payload: AddMarginRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyActionResponse:
    """ISOLATED 모드 포지션에 증거금 추가 — 청산가 완화.

    검증:
    - strategy 존재 + 본인 소유
    - 포지션 보유 (qty != 0)
    - amount > 0 (Pydantic 가드)
    - 거래소 마진 모드가 CROSS 면 -4046 거절 (친절 에러 메시지)
    """
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
        execution_service.add_position_margin(strategy.id, amount=payload.amount)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    db.refresh(strategy)
    return StrategyActionResponse(
        strategy_id=strategy.id,
        status=strategy.status,
        message=f"증거금 {payload.amount} USDT 추가 완료. 거래소에서 새 청산가 확인.",
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
    # 좀비 방지 (2026-05-03): force-stop 시에도 qty=0 보장 — UI/통계 잔재 방지.
    # 실제 거래소 포지션은 운영자가 직접 정리해야 함 (force-stop 본 의도).
    from decimal import Decimal as _D
    strategy.current_position_qty = _D("0")
    if not strategy.stopped_at:
        from datetime import datetime as _dt, timezone as _tz
        strategy.stopped_at = _dt.now(_tz.utc)
    db.commit()
    db.refresh(strategy)
    return StrategyActionResponse(
        strategy_id=strategy.id,
        status=strategy.status,
        message="DB 상에서만 STOPPED + qty=0 마킹됨 (거래소 호출 없음 — 거래소 잔재는 운영자가 직접 확인)",
    )


@router.delete("/{strategy_id}", response_model=StrategyActionResponse)
def delete_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyActionResponse:
    """대기 (current_stage=0) 상태의 종료된 전략을 DB 에서 삭제한다.

    UX #17 (2026-04-29): 시작 실패한 전략 (-4164 등) 이 STOPPED 상태로
    "수동 종료" 표시되어 대시보드에 쌓이는 문제. 한번도 체결된 적 없는
    전략 (current_stage=0 AND avg_entry_price=NULL) 만 삭제 허용.

    안전장치:
    - 종료 상태가 아니면 거절 (실수로 활성 전략 삭제 방지)
    - 1단계라도 진입했던 전략은 거절 (감사 로그 보존)
    """
    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")

    # 2026-05-04: 공통 TERMINAL_STATUSES 사용 (이전엔 inline set 이라 다른 곳과 drift).
    if strategy.status not in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"활성 전략은 삭제 불가. 먼저 종료(/stop)하세요. 현재 status={strategy.status}",
        )

    if (strategy.current_stage or 0) > 0 or (strategy.avg_entry_price and Decimal(str(strategy.avg_entry_price)) > 0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미 1단계 이상 체결된 전략은 감사 로그 보존을 위해 삭제 불가. (대시보드 종료 숨김으로 가리세요)",
        )

    sid = strategy.id
    db.delete(strategy)
    db.commit()
    return StrategyActionResponse(
        strategy_id=sid,
        status="DELETED",
        message=f"전략 #{sid} 대기 상태에서 삭제됨 (포지션 미진입)",
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

    # Terminal status guard (2026-05-04 fix):
    # COMPLETED / STOPPED / REENTRY_READY 등 이미 종료된 strategy 에 stop 누르면
    # 무조건 STOPPING 으로 덮어쓰던 버그 → 좀비 발생 (#90 사례).
    # 종료 상태에서는 noop 으로 응답.
    if strategy.status in TERMINAL_STATUSES:
        return StrategyActionResponse(
            strategy_id=strategy.id,
            status=strategy.status,
            message=f"이미 종료된 전략 ({strategy.status}) 입니다. 추가 정지 불필요.",
        )

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
                try:
                    execution_service.emergency_close_position(strategy.id, quantity=qty)
                except ValueError as ve:
                    # UX (2026-04-29): Bug #8 fix 가 거래소 포지션 0 일 때 ValueError 를
                    # 던짐 (cleanup 은 이미 완료). 이 경우 502 가 아닌 정상 응답으로 처리.
                    if "no" in str(ve).lower() and "position" in str(ve).lower():
                        db.refresh(strategy)
                        return StrategyActionResponse(
                            strategy_id=strategy.id,
                            status=strategy.status,
                            message=f"이미 청산된 상태였습니다. 미체결 주문 취소 + STOPPED 마킹 완료. ({ve})",
                        )
                    raise
            strategy.status = "STOPPING"
            db.commit()
            message = "Position closed at market"
    except HTTPException:
        raise
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Exchange error: {e}") from e

    db.refresh(strategy)
    return StrategyActionResponse(strategy_id=strategy.id, status=strategy.status, message=message)
