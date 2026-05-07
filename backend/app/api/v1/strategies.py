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
    """Template 의 활성 TP 수 — tp1~10_percent 중 NOT NULL 카운트.

    2026-05-06: 1~10 동적 (사용자 요청 10단계 익절 확장). fallback 4 (backward-compat).
    """
    if not tpl:
        return 4
    n = sum(1 for i in range(1, 11) if getattr(tpl, f"tp{i}_percent", None) is not None)
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
    # 2026-05-06: 10단계 익절 확장 (사용자 요청).
    tp6_percent: Decimal | None = Field(default=None)
    tp7_percent: Decimal | None = Field(default=None)
    tp8_percent: Decimal | None = Field(default=None)
    tp9_percent: Decimal | None = Field(default=None)
    tp10_percent: Decimal | None = Field(default=None)
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"⚠️ 심볼 「{payload.symbol}」 가 시스템에 없습니다. 운영자에게 심볼 동기화 요청 (admin → /admin/symbol-sync) 하세요.")

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
    include_archived: bool = False,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[StrategyDetailResponse]:
    """전략 인스턴스 목록 — 대시보드 표시를 위해 detail 필드까지 포함.

    2026-05-06 (C-full Step 1): default 로 archived 제외 (UI 깔끔). UI 의 「📦 보관 보기」
    체크박스 활성 시 ?include_archived=true 로 호출 → 전체 목록 + restore 버튼.
    """
    from app.models.strategy_template import StrategyTemplate
    rows = StrategyRepository(db).list_strategies(
        user_id=user_id,
        status=status_filter,
        symbol=symbol,
        include_archived=include_archived,
    )
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.")
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.")

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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.")
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.")
    tpl = db.get(StrategyTemplate, strategy.strategy_template_id)
    if not tpl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="⚠️ 전략 템플릿이 삭제됐거나 손상됐습니다. 운영자에게 문의하세요.")

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
        # 2026-05-06: TP1~10 동적 (10단계 익절 확장).
        **{
            f"tp{n}_percent": (
                str(getattr(tpl, f"tp{n}_percent")) if getattr(tpl, f"tp{n}_percent", None) is not None else None
            ) for n in range(1, 11)
        },
        **{
            f"tp{n}_qty_ratio": (
                str(getattr(tpl, f"tp{n}_qty_ratio")) if getattr(tpl, f"tp{n}_qty_ratio", None) is not None else None
            ) for n in range(1, 11)
        },
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.")

    account = ExchangeAccountRepository(db).get(strategy.exchange_account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="⚠️ 거래소 계정이 삭제됐거나 본인 소유가 아닙니다. 「💼 계정」 모달에서 확인하세요.")

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
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"⚠️ 거래소 (Binance) 주문 실패: {e}{hint}") from e

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


class StrategySettingsUpdate(BaseModel):
    """In-place 수정 — 활성 strategy 의 TP/SL + 미발동 단계 trigger_percent + capitals + 단계 수 변경.

    안전 정책:
    - side, leverage: 변경 거부 (활성 포지션과 inconsistency 위험)
    - 이미 진입한 단계 (stage_no <= current_stage): trigger_percent / capital 변경 거부
    - 미발동 단계 (stage_no > current_stage): trigger_percent + planned_capital 변경 가능
    - 단계 수 (capitals 길이) 변경: current_stage 이상 유지 필수 (감소 시 미발동 stage 삭제, 증가 시 신규 stage 생성)

    배열 형식 (모두 길이 = 전체 단계 수):
    - trigger_percents: 양수=변경, None=유지. current_stage 이하는 None 이어야 함.
    - capitals: 양수=변경, None=유지. current_stage 이하는 변경 거부.
    - capitals 와 trigger_percents 모두 보내면 길이 일치 필요.
    - 둘 중 하나만 길이 변경하면 안 됨 (둘 다 새 길이로 보내야 함).

    Phase 3a (2026-05-04) — trigger_percents 부분 갱신.
    Phase 3b (2026-05-05) — capitals 부분 갱신.
    Phase 3c (2026-05-05) — 단계 수 변경 (추가/제거).
    """
    tp1_percent: Decimal | None = Field(default=None, gt=0)
    tp2_percent: Decimal | None = Field(default=None, gt=0)
    tp3_percent: Decimal | None = Field(default=None, gt=0)
    tp4_percent: Decimal | None = Field(default=None, gt=0)
    tp5_percent: Decimal | None = Field(default=None, gt=0)
    # 2026-05-06: 10단계 익절 확장 (사용자 요청).
    tp6_percent: Decimal | None = Field(default=None, gt=0)
    tp7_percent: Decimal | None = Field(default=None, gt=0)
    tp8_percent: Decimal | None = Field(default=None, gt=0)
    tp9_percent: Decimal | None = Field(default=None, gt=0)
    tp10_percent: Decimal | None = Field(default=None, gt=0)
    tp1_qty_ratio: Decimal | None = Field(default=None, gt=0, le=100)
    tp2_qty_ratio: Decimal | None = Field(default=None, gt=0, le=100)
    tp3_qty_ratio: Decimal | None = Field(default=None, gt=0, le=100)
    tp4_qty_ratio: Decimal | None = Field(default=None, gt=0, le=100)
    tp5_qty_ratio: Decimal | None = Field(default=None, gt=0, le=100)
    tp6_qty_ratio: Decimal | None = Field(default=None, gt=0, le=100)
    tp7_qty_ratio: Decimal | None = Field(default=None, gt=0, le=100)
    tp8_qty_ratio: Decimal | None = Field(default=None, gt=0, le=100)
    tp9_qty_ratio: Decimal | None = Field(default=None, gt=0, le=100)
    tp10_qty_ratio: Decimal | None = Field(default=None, gt=0, le=100)
    stop_loss_percent_of_capital: Decimal | None = Field(default=None, gt=0, le=100)
    crisis_qty_ratios: dict | None = None
    trigger_percents: list[Decimal | None] | None = Field(
        default=None,
        description="단계별 trigger_percent (양수=변경, None=유지). current_stage 이하 단계는 None 이어야 함.",
    )
    capitals: list[Decimal | None] | None = Field(
        default=None,
        description=(
            "단계별 planned_capital (양수=변경, None=유지). current_stage 이하 단계는 None 이어야 함. "
            "길이가 current_stage 보다 작으면 거부 (이미 발동한 단계는 보존 필수). "
            "trigger_percents 와 함께 보내면 길이 일치 필요."
        ),
    )
    last_stage_trigger_percent: Decimal | None = Field(
        default=None, gt=0,
        description="마지막 단계 trigger_percent override (옵션). 단계 수 변경 시 마지막 항목에 적용.",
    )


@router.patch("/{strategy_id}/settings", response_model=StrategyDetailResponse)
def update_strategy_settings_in_place(
    strategy_id: int,
    payload: StrategySettingsUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyDetailResponse:
    """활성 strategy 의 TP/SL 만 in-place 수정 (포지션/단계 유지).

    구현: 기존 template 복사 + payload 의 TP/SL 만 override → 새 template insert
    → strategy.strategy_template_id 갱신. side/leverage/stages 등은 보존.

    제약:
    - 종료된 strategy 는 거부 (재시작이 의미 — /stop 후 새 전략 시작이 정확)
    - side / leverage / stages_config 변경 거부 (위험)
    """
    from app.models.strategy_template import StrategyTemplate
    from datetime import datetime as _dt

    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.")
    if strategy.status in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"⚠️ 이미 종료된 전략 (상태: {strategy.status}) 은 설정 수정이 불가합니다.\n\n"
                "💡 해결: 「🔄 다시 시작」 (같은 설정 새 전략) 또는 「🟢 새 전략 시작」 으로 진행하세요."
            ),
        )

    old_tpl = db.get(StrategyTemplate, strategy.strategy_template_id)
    if not old_tpl:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="⚠️ 원본 전략 템플릿이 삭제됐습니다. 「🔄 다시 시작」 으로 새 전략을 생성하세요.")

    # 새 template 생성 — 모든 필드 복사 + payload override.
    # name 에 strategy id + timestamp 부착 → 중복 회피 + 추적 용이.
    ts = int(_dt.now().timestamp())
    new_tpl = StrategyTemplate(
        name=f"{old_tpl.name}_inplace_s{strategy.id}_{ts}"[:120],
        strategy_type=old_tpl.strategy_type,
        side=old_tpl.side,
        leverage=old_tpl.leverage,
        total_capital=old_tpl.total_capital,
        stages_config=dict(old_tpl.stages_config) if old_tpl.stages_config else None,
        # legacy 4단계 호환 필드 (있으면 유지)
        stage1_capital=old_tpl.stage1_capital,
        stage2_capital=old_tpl.stage2_capital,
        stage3_capital=old_tpl.stage3_capital,
        stage4_capital=old_tpl.stage4_capital,
        stage2_trigger_percent=old_tpl.stage2_trigger_percent,
        stage3_trigger_percent=old_tpl.stage3_trigger_percent,
        stage4_trigger_mode=old_tpl.stage4_trigger_mode,
        stage4_trigger_percent=old_tpl.stage4_trigger_percent,
        # TP/SL — payload 우선, 없으면 원본
        # 2026-05-06: TP1~10 동적 (10단계 익절 확장).
        **{
            f"tp{n}_percent": (
                getattr(payload, f"tp{n}_percent")
                if getattr(payload, f"tp{n}_percent", None) is not None
                else getattr(old_tpl, f"tp{n}_percent", None)
            ) for n in range(1, 11)
        },
        **{
            f"tp{n}_qty_ratio": (
                getattr(payload, f"tp{n}_qty_ratio")
                if getattr(payload, f"tp{n}_qty_ratio", None) is not None
                else getattr(old_tpl, f"tp{n}_qty_ratio", None)
            ) for n in range(1, 11)
        },
        stop_loss_percent_of_capital=(
            payload.stop_loss_percent_of_capital
            if payload.stop_loss_percent_of_capital is not None
            else old_tpl.stop_loss_percent_of_capital
        ),
        crisis_qty_ratios=(
            payload.crisis_qty_ratios
            if payload.crisis_qty_ratios is not None
            else (dict(old_tpl.crisis_qty_ratios) if old_tpl.crisis_qty_ratios else None)
        ),
        reentry_policy=old_tpl.reentry_policy,
        reentry_delay_seconds=old_tpl.reentry_delay_seconds,
        reentry_offset_pct=old_tpl.reentry_offset_pct,
        is_active=False,  # in-place 수정용 — 다른 신규 strategy 가 이걸 선택하면 안 됨
    )
    # 2026-05-04 (Phase 3a) + 2026-05-05 (Phase 3b/3c):
    #   stages_config = trigger_percents (3a) + capitals (3b) + 단계 수 변경 (3c) 통합 처리.
    #
    # 입력 정규화: 둘 다 None 이면 stages_config 변경 안 함. 하나라도 있으면 길이 새 N 결정.
    stages_changed = (payload.trigger_percents is not None) or (payload.capitals is not None)
    if stages_changed:
        old_cfg = dict(old_tpl.stages_config) if old_tpl.stages_config else {}
        old_capitals = list(old_cfg.get("capitals") or [])
        old_triggers = list(old_cfg.get("trigger_percents") or [None] * len(old_capitals))
        cur_stage_idx = (strategy.current_stage or 0)  # 1-based

        # 새 길이 결정 — payload 가 길이를 결정. 둘 다 보내면 일치 필수.
        if payload.capitals is not None and payload.trigger_percents is not None:
            if len(payload.capitals) != len(payload.trigger_percents):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"capitals 길이 ({len(payload.capitals)}) 와 trigger_percents 길이 "
                        f"({len(payload.trigger_percents)}) 가 일치해야 함."
                    ),
                )
            new_n = len(payload.capitals)
        elif payload.capitals is not None:
            new_n = len(payload.capitals)
        else:
            # trigger_percents 만 — 길이가 기존 capitals 길이와 같아야 (단계 수 변경 X)
            new_n = len(payload.trigger_percents)
            if new_n != len(old_capitals):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"trigger_percents 길이 ({new_n}) 가 전체 단계 수 ({len(old_capitals)}) 와 다름. "
                        "단계 수 변경하려면 capitals 도 함께 보내세요."
                    ),
                )

        # current_stage 이상 길이 보장 (이미 발동한 단계 보존)
        if new_n < cur_stage_idx:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"단계 수 ({new_n}) 가 current_stage ({cur_stage_idx}) 보다 작음. "
                    "이미 발동한 단계는 보존돼야 합니다."
                ),
            )

        # 새 capitals/triggers 배열 구성 — 미발동 stage 만 변경, 발동 stage 는 거부 검사
        new_capitals: list = list(old_capitals[:new_n])
        new_triggers: list = list(old_triggers[:new_n])
        # 길이 증가 시 padding (None → 검증에서 채워야 함)
        while len(new_capitals) < new_n:
            new_capitals.append(None)
        while len(new_triggers) < new_n:
            new_triggers.append(None)

        if payload.capitals is not None:
            for i, new_cap in enumerate(payload.capitals):
                if new_cap is None:
                    continue
                stage_no = i + 1
                if stage_no <= cur_stage_idx:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"이미 진입한 단계 (stage {stage_no}, current_stage={cur_stage_idx}) 의 "
                            "capital 변경 불가. 이 인덱스는 None 으로 두세요."
                        ),
                    )
                new_capitals[i] = str(new_cap)
        if payload.trigger_percents is not None:
            for i, new_pct in enumerate(payload.trigger_percents):
                if new_pct is None:
                    continue
                stage_no = i + 1
                if stage_no <= cur_stage_idx:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"이미 진입한 단계 (stage {stage_no}, current_stage={cur_stage_idx}) 의 "
                            "trigger_percent 변경 불가. 이 인덱스는 None 으로 두세요."
                        ),
                    )
                new_triggers[i] = str(new_pct)

        # 신규 stage (i >= len(old_capitals)) 는 capital 필수 검사 (None 이면 invalid)
        for i in range(len(old_capitals), new_n):
            if new_capitals[i] is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"신규 stage {i+1} 의 capital 이 None — 새 단계 추가 시 capitals 배열에 "
                        f"양수 값 필요 (capitals[{i}])."
                    ),
                )

        old_cfg["capitals"] = new_capitals
        old_cfg["trigger_percents"] = new_triggers
        if payload.last_stage_trigger_percent is not None:
            old_cfg["last_stage_trigger_percent"] = str(payload.last_stage_trigger_percent)
        new_tpl.stages_config = old_cfg

    db.add(new_tpl)
    db.flush()
    strategy.strategy_template_id = new_tpl.id

    # 미발동 plan 재계산 + 신규/제거 stage 처리 (stages_changed 시).
    if stages_changed:
        from app.models.strategy_stage_plan import StrategyStagePlan
        from app.services.strategy_calculator import StrategyCalculator, SymbolRule
        from app.repositories.strategy_repository import StrategyRepository as _SR
        from sqlalchemy import select as _s, delete as _del
        sym_model = _SR(db).get_symbol(strategy.symbol)
        if sym_model:
            sym_rule = SymbolRule(
                symbol=sym_model.symbol,
                tick_size=Decimal(str(sym_model.tick_size or 0)),
                step_size=Decimal(str(sym_model.step_size or 0)),
                min_qty=Decimal(str(sym_model.min_qty or 0)),
                price_precision=sym_model.price_precision or 8,
                quantity_precision=sym_model.quantity_precision or 8,
            )
            calc = StrategyCalculator(sym_rule)
            try:
                preview = calc.calculate_preview(
                    symbol=strategy.symbol,
                    side=strategy.side,
                    start_price=Decimal(str(strategy.start_price)),
                    stages_config=new_tpl.stages_config,
                    leverage=int(strategy.leverage),
                    total_capital=Decimal(str(strategy.total_capital)),
                    tp1_percent=Decimal(str(new_tpl.tp1_percent)),
                    tp2_percent=Decimal(str(new_tpl.tp2_percent)),
                    tp3_percent=Decimal(str(new_tpl.tp3_percent)),
                    stop_loss_percent_of_capital=Decimal(str(new_tpl.stop_loss_percent_of_capital)),
                )
                preview_by_stage = {x.stage_no: x for x in preview.stages}
                new_n = len(new_tpl.stages_config["capitals"])
                # 기존 plans 조회
                plans = db.execute(
                    _s(StrategyStagePlan)
                    .where(StrategyStagePlan.strategy_instance_id == strategy.id)
                ).scalars().all()
                # 1) 기존 plans 갱신 또는 삭제
                for p in plans:
                    if p.is_triggered:
                        continue  # 이미 발동된 plan 보존
                    if p.stage_no > new_n:
                        # 단계 수 감소 — 미발동 stage_plan 삭제
                        db.delete(p)
                        continue
                    new_plan = preview_by_stage.get(p.stage_no)
                    if new_plan:
                        p.trigger_percent = new_plan.trigger_percent
                        p.trigger_price = new_plan.trigger_price
                        p.planned_capital = new_plan.planned_capital
                        p.planned_qty = new_plan.planned_qty
                # 2) 신규 stage plan 생성 (단계 수 증가)
                existing_stage_nos = {p.stage_no for p in plans}
                for stage_no in range(1, new_n + 1):
                    if stage_no in existing_stage_nos:
                        continue
                    new_plan = preview_by_stage.get(stage_no)
                    if not new_plan:
                        continue
                    db.add(StrategyStagePlan(
                        strategy_instance_id=strategy.id,
                        stage_no=stage_no,
                        side=strategy.side,
                        trigger_mode=new_plan.trigger_mode,
                        trigger_percent=new_plan.trigger_percent,
                        trigger_price=new_plan.trigger_price,
                        planned_capital=new_plan.planned_capital,
                        planned_qty=new_plan.planned_qty,
                        is_triggered=False,
                    ))
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"새 stages_config 로 plan 재계산 실패: {e}",
                ) from e

    db.commit()
    db.refresh(strategy)

    # response — template 기반 enrichment 만 (tp_count batch 는 list endpoint 가 처리).
    resp = _enrich_response(StrategyDetailResponse.model_validate(strategy), new_tpl)
    return resp


@router.post("/{strategy_id}/trigger-next-stage", response_model=StrategyActionResponse)
def trigger_next_stage_manually(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyActionResponse:
    """현재 전략의 다음 단계를 수동으로 즉시 진입 (가격 trigger 무시).

    사용자 요청 (2026-05-04): "현재 포지션에서 추가로 진입할 수 있는 옵션".
    안전한 구현: 새 임의 주문이 아니라 기존 stage_plan 의 다음 단계를 trigger_price
    체크 없이 즉시 발동. capital/qty 는 stage_plan 에 사전 계산된 값 그대로 사용
    (template 의 단계 자본 분배 보존).

    검증:
    - 본인 소유 strategy
    - 활성 status (TERMINAL 거부)
    - kill-switch 미발동 (execution_service.trigger_next_stage 가 자체 검증)
    - 다음 단계가 아직 trigger 안 됐어야 함
    - stage_plan 존재
    """
    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.")
    if strategy.status in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"종료된 strategy ({strategy.status}) 는 추가 단계 진입 불가.",
        )
    next_stage_no = (strategy.current_stage or 0) + 1
    # template 의 활성 단계 수 확인
    from app.models.strategy_template import StrategyTemplate
    tpl = db.get(StrategyTemplate, strategy.strategy_template_id)
    total_stages = _count_active_stages(tpl)
    if next_stage_no > total_stages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"이미 모든 단계 ({total_stages}/{total_stages}) 진입 완료. 추가 진입 불가.",
        )
    # stage_plan 존재 확인 (atomic claim 전 plan 자체가 있는지)
    from app.models.strategy_stage_plan import StrategyStagePlan
    from app.models.order import Order
    from sqlalchemy import select as sa_select, update as sa_update
    plan = db.execute(
        sa_select(StrategyStagePlan)
        .where(StrategyStagePlan.strategy_instance_id == strategy.id)
        .where(StrategyStagePlan.stage_no == next_stage_no)
    ).scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Stage {next_stage_no} plan 없음")
    # 2026-05-04 fix v2 (사용자 #96 사례): 거래소 NEW LIMIT 중복 방지.
    # 자동 워커가 LIMIT 을 placed (NEW 상태) 한 stage 에 사용자가 ▶ (MARKET) 추가 시
    # 가격 도달 시 자동 LIMIT 도 fill → 포지션 더블링. 이 가드로 차단.
    existing_pending = db.execute(
        sa_select(Order)
        .where(Order.strategy_instance_id == strategy.id)
        .where(Order.stage_no == next_stage_no)
        .where(Order.purpose == "ENTRY")
        .where(Order.status == "NEW")
    ).scalar_one_or_none()
    if existing_pending is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Stage {next_stage_no} 의 LIMIT 주문이 이미 거래소에 미체결 상태로 있음 "
                f"(Order #{existing_pending.id}, qty={existing_pending.orig_qty}, price={existing_pending.price}). "
                "가격 도달 시 자동 체결되거나, 「⏸」 로 취소 후 재발송하세요."
            ),
        )
    # 2026-05-04 fix v3 (Phase 1 race condition): 빠르게 ▶ 더블 클릭 시
    # 1차 호출이 commit 되기 전 2차 호출이 같은 stage 의 is_triggered=False 를 보고 통과 →
    # 같은 stage 에 MARKET 더블 발송 = 포지션 더블링.
    # Atomic UPDATE 로 점유: WHERE is_triggered=False AND ... → 0 rows 면 race 차단.
    # PostgreSQL 의 UPDATE 는 implicit row lock 이라, 동시 트랜잭션은 직렬화됨.
    claim_result = db.execute(
        sa_update(StrategyStagePlan)
        .where(StrategyStagePlan.strategy_instance_id == strategy.id)
        .where(StrategyStagePlan.stage_no == next_stage_no)
        .where(StrategyStagePlan.is_triggered == False)  # noqa: E712
        .values(is_triggered=True)
    )
    if claim_result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Stage {next_stage_no} 가 이미 진입됨 또는 다른 요청이 처리 중. "
                "잠시 후 화면을 새로고침해 진행 상황을 확인하세요."
            ),
        )
    db.commit()  # claim 영구화 — 다른 동시 요청이 위 UPDATE 에서 0 rows 보도록.

    account = ExchangeAccountRepository(db).get(strategy.exchange_account_id)
    if not account:
        # claim 롤백 (account 검증 실패는 거래소 호출 전이라 안전하게 풀어줌)
        db.execute(
            sa_update(StrategyStagePlan)
            .where(StrategyStagePlan.strategy_instance_id == strategy.id)
            .where(StrategyStagePlan.stage_no == next_stage_no)
            .values(is_triggered=False)
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="⚠️ 거래소 계정이 삭제됐거나 본인 소유가 아닙니다. 「💼 계정」 모달에서 확인하세요.")
    try:
        execution_service = ExecutionService(
            db,
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=account.is_testnet,
        )
        # 2026-05-04 (사용자 요청): 수동 「▶ 다음 단계」 = 시장가 즉시 진입.
        # enter_stage_at_market: 현재가 MARKET, planned_capital 로 qty 재계산.
        # 자체 is_triggered=True 마킹은 우리가 위에서 이미 처리 → no-op.
        execution_service.enter_stage_at_market(strategy.id, stage_no=next_stage_no)
    except ValueError as e:
        # claim 롤백 — kill-switch / qty=0 등 사용자 수정 가능 에러
        db.execute(
            sa_update(StrategyStagePlan)
            .where(StrategyStagePlan.strategy_instance_id == strategy.id)
            .where(StrategyStagePlan.stage_no == next_stage_no)
            .values(is_triggered=False)
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        # claim 롤백 — 거래소 통신 실패 등
        db.execute(
            sa_update(StrategyStagePlan)
            .where(StrategyStagePlan.strategy_instance_id == strategy.id)
            .where(StrategyStagePlan.stage_no == next_stage_no)
            .values(is_triggered=False)
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Exchange error: {e}") from e
    db.refresh(strategy)
    return StrategyActionResponse(
        strategy_id=strategy.id,
        status=strategy.status,
        message=f"수동 진입 — stage {next_stage_no} 시장가 즉시 진입 (capital={plan.planned_capital} USDT). 체결되면 평단/qty 자동 갱신됨.",
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.")
    account = ExchangeAccountRepository(db).get(strategy.exchange_account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="⚠️ 거래소 계정이 삭제됐거나 본인 소유가 아닙니다. 「💼 계정」 모달에서 확인하세요.")
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
    # 2026-05-06 (사용자 요청): 증거금 추가 시 텔레그램 알림 발송.
    try:
        from app.services.notification_service import NotificationService
        NotificationService(db).send_margin_added_alert(
            strategy_instance_id=strategy.id,
            symbol=strategy.symbol,
            side=strategy.side,
            amount=payload.amount,
        )
    except Exception:
        # 알림 실패는 본 작업 성공에 영향 X (silent fail, NotificationService 자체에서 SENT/FAILED 기록)
        pass
    return StrategyActionResponse(
        strategy_id=strategy.id,
        status=strategy.status,
        message=f"증거금 {payload.amount} USDT 추가 완료. 거래소에서 새 청산가 확인.",
    )


# 2026-05-04 (사용자 요청): 「💉 포지션 추가」 — 자유 금액 즉시 진입 (시장가 또는 지정가).
class AddPositionRequest(BaseModel):
    amount_usdt: Decimal = Field(..., gt=0, description="추가할 자본 (USDT, margin). qty = amount × leverage / price.")
    order_type: str = Field(..., description="MARKET 또는 LIMIT")
    limit_price: Decimal | None = Field(None, gt=0, description="LIMIT 주문일 때 지정가 (양수). MARKET 이면 무시.")


@router.post("/{strategy_id}/add-position", response_model=StrategyActionResponse)
def add_position_to_strategy(
    strategy_id: int,
    payload: AddPositionRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyActionResponse:
    """ad-hoc 포지션 추가 — 사용자가 입력한 USDT 금액을 시장가/지정가로 즉시 진입.

    증거금 추가 (마진만 늘림) 와 다름: qty 도 늘어남 + 평단 갱신 + invested_capital 증가.

    검증:
    - 본인 소유 strategy
    - kill-switch 미발동
    - amount_usdt > 0 (Pydantic 가드)
    - order_type ∈ {MARKET, LIMIT}
    - LIMIT 면 limit_price 필수
    """
    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.")
    account = ExchangeAccountRepository(db).get(strategy.exchange_account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="⚠️ 거래소 계정이 삭제됐거나 본인 소유가 아닙니다. 「💼 계정」 모달에서 확인하세요.")
    try:
        execution_service = ExecutionService(
            db,
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=account.is_testnet,
        )
        order = execution_service.add_position_now(
            strategy.id,
            amount_usdt=payload.amount_usdt,
            order_type=payload.order_type,
            limit_price=payload.limit_price,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Exchange error: {e}") from e
    db.refresh(strategy)
    order_type_label = payload.order_type.upper()
    # 2026-05-06 (사용자 요청): 포지션 추가 시 텔레그램 알림 발송.
    try:
        from app.services.notification_service import NotificationService
        NotificationService(db).send_position_added_alert(
            strategy_instance_id=strategy.id,
            symbol=strategy.symbol,
            side=strategy.side,
            amount_usdt=payload.amount_usdt,
            order_type=order_type_label,
            qty=order.orig_qty,
            limit_price=payload.limit_price,
        )
    except Exception:
        # 알림 실패는 본 작업 성공에 영향 X
        pass
    msg = (
        f"포지션 추가 — {order_type_label} 주문 발송됨 (amount={payload.amount_usdt} USDT, qty={order.orig_qty}). "
        f"체결되면 평단/qty 자동 갱신."
    )
    return StrategyActionResponse(
        strategy_id=strategy.id,
        status=strategy.status,
        message=msg,
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.")
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
    """종료된 전략을 archive (soft delete) 한다 — DB row 보존.

    UX #17 (2026-04-29): 시작 실패한 전략 (-4164 등) 이 STOPPED 상태로
    "수동 종료" 표시되어 대시보드에 쌓이는 문제.

    2026-05-06 (사용자 #96 사례 — cascade hard delete 로 +867 USDT
    realized_pnl 누락 — soft delete 로 변경):
    - 한 번도 체결 안 한 전략 (current_stage=0): archive (UI 숨김 가능)
    - 1단계 이상 체결된 전략: archive (realized_pnl 통계 보존됨)
    - 어느 경우든 row + orders 보존 → realized_pnl 합계 정확성 유지

    안전장치:
    - 종료 상태가 아니면 거절 (활성 전략 archive 방지)
    - 이미 archived 면 noop (idempotent)
    """
    from datetime import datetime as _dt
    from datetime import timezone as _tz
    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.")

    # 2026-05-04: 공통 TERMINAL_STATUSES 사용 (이전엔 inline set 이라 다른 곳과 drift).
    if strategy.status not in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"활성 전략은 삭제 불가. 먼저 종료(/stop)하세요. 현재 status={strategy.status}",
        )

    # 이미 archived → idempotent
    if getattr(strategy, "is_archived", False):
        return StrategyActionResponse(
            strategy_id=strategy.id,
            status="ARCHIVED",
            message=f"전략 #{strategy.id} 는 이미 archive 상태입니다.",
        )

    # 2026-05-06 fix (#96 사례): hard delete → soft delete.
    # row + orders 보존 → /admin/stats 의 realized_pnl 합계가 거래소 history 일치.
    sid = strategy.id
    had_position = (strategy.current_stage or 0) > 0 or (
        strategy.avg_entry_price and Decimal(str(strategy.avg_entry_price)) > 0
    )
    realized = Decimal(str(strategy.realized_pnl or 0))
    strategy.is_archived = True
    strategy.archived_at = _dt.now(_tz.utc)
    db.commit()

    if had_position:
        msg = (
            f"전략 #{sid} 보관 처리됨 (DB row + orders 보존, UI 숨김). "
            f"realized_pnl {realized:+.4f} USDT 통계 합계에 유지됨."
        )
    else:
        msg = f"전략 #{sid} 보관 처리됨 (포지션 미진입, audit log 보존)."
    return StrategyActionResponse(
        strategy_id=sid,
        status="ARCHIVED",
        message=msg,
    )


@router.post("/{strategy_id}/restore", response_model=StrategyActionResponse)
def restore_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyActionResponse:
    """archived 된 strategy 를 복원 (is_archived → false). 2026-05-06 (C-full Step 2).

    DELETE 가 archive 로 변경됐으니 (PR #7), 실수로 archive 한 경우 되돌리기.
    archived 가 아닌 strategy 는 noop (idempotent). 복원 후 status 그대로 유지 —
    여전히 종료 상태 (STOPPED/COMPLETED/등). 사용자가 「🔄 다시 시작」 으로 새 progression
    시작 가능.
    """
    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.")

    if not getattr(strategy, "is_archived", False):
        return StrategyActionResponse(
            strategy_id=strategy.id,
            status=strategy.status,
            message=f"전략 #{strategy.id} 는 archive 상태가 아닙니다 (이미 활성/UI 표시 중).",
        )

    strategy.is_archived = False
    strategy.archived_at = None
    db.commit()
    return StrategyActionResponse(
        strategy_id=strategy.id,
        status=strategy.status,
        message=(
            f"전략 #{strategy.id} 복원 완료 — UI 목록에 다시 표시. status={strategy.status} "
            "그대로. 「🔄 다시 시작」 으로 새 progression 시작 가능."
        ),
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.")

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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="⚠️ 거래소 계정이 삭제됐거나 본인 소유가 아닙니다. 「💼 계정」 모달에서 확인하세요.")

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
