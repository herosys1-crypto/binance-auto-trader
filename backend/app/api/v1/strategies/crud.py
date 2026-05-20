"""Strategies — CRUD + read-only detail views (timeline / stage-plans / blueprint).

create / list / get one + 상세 조회 endpoint 모음.
2026-05-14 Phase 4 split: 기존 strategies.py 에서 분리.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.api.v1.strategies.helpers import (
    _enrich_response,
    _fetch_tp_counts_batch,
    _resolve_close_reason,
    apply_live_unrealized_pnl,
    apply_live_unrealized_pnl_batch,
)
from app.repositories.strategy_repository import StrategyRepository
from app.schemas.strategy import (
    StrategyCreateRequest,
    StrategyDetailResponse,
)
from app.services.strategy_service import StrategyService

router = APIRouter(prefix="/strategies", tags=["strategies"])


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
    # 2026-05-20: 라이브 markPrice 로 unrealized_pnl 재계산 (Redis mget 1회).
    # 캐시 miss 인 심볼은 stored 값 유지 — backward-compat.
    apply_live_unrealized_pnl_batch(out)
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
    # 2026-05-20: 라이브 markPrice 로 unrealized_pnl 재계산.
    apply_live_unrealized_pnl(resp)
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
        # 2026-05-11 (사용자 요청): 단계별 추가 증거금 (이전 전략 불러오기에 자동 채움)
        "additional_margins": sc.get("additional_margins") or [],
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
        # 2026-05-14 (사용자 요청, alembic 0015): 크라이시스 임계 사용자 정의 자동 채움.
        "crisis_max_loss_threshold": str(tpl.crisis_max_loss_threshold) if tpl.crisis_max_loss_threshold is not None else None,
    }
