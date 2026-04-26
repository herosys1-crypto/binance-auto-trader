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
    tp4_percent: Decimal | None = Field(default=None, gt=0)
    tp5_percent: Decimal | None = Field(default=None, gt=0)
    tp1_qty_ratio: Decimal = Field(..., gt=0, le=100)
    tp2_qty_ratio: Decimal = Field(..., gt=0, le=100)
    tp3_qty_ratio: Decimal = Field(..., gt=0, le=100)
    tp4_qty_ratio: Decimal | None = Field(default=None, gt=0, le=100)
    tp5_qty_ratio: Decimal | None = Field(default=None, gt=0, le=100)
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
        tp4_percent=payload.tp4_percent,
        tp5_percent=payload.tp5_percent,
        tp1_qty_ratio=payload.tp1_qty_ratio,
        tp2_qty_ratio=payload.tp2_qty_ratio,
        tp3_qty_ratio=payload.tp3_qty_ratio,
        tp4_qty_ratio=payload.tp4_qty_ratio,
        tp5_qty_ratio=payload.tp5_qty_ratio,
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


@router.delete("/strategy-templates/{template_id}", response_model=MessageResponse)
def delete_strategy_template(
    template_id: int,
    cascade: bool = False,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> MessageResponse:
    """전략 템플릿 삭제.

    - cascade=False (기본): 사용 중인 strategy 가 있으면 비활성화만.
    - cascade=True: 모든 참조 strategy 가 terminal 상태(STOPPED/CLOSED/CLOSED_BY_*)면 함께 삭제.
                    하나라도 active 면 거부.
    """
    from app.models.strategy_instance import StrategyInstance

    tpl = db.get(StrategyTemplate, template_id)
    if not tpl:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    refs = db.query(StrategyInstance).filter(StrategyInstance.strategy_template_id == template_id).all()
    terminal_statuses = {"STOPPED", "CLOSED", "CLOSED_BY_TP", "CLOSED_BY_SL", "COMPLETED", "STOPPING"}
    if not refs:
        db.delete(tpl)
        db.commit()
        return MessageResponse(message=f"Template #{template_id} 삭제됨")

    if cascade:
        non_terminal = [r for r in refs if (r.status or "").upper() not in terminal_statuses]
        if non_terminal:
            ids = [r.id for r in non_terminal]
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"활성 전략 {ids} 가 있어 cascade 삭제 불가. 먼저 force-stop 후 다시 시도하세요.",
            )
        for r in refs:
            db.delete(r)
        db.delete(tpl)
        db.commit()
        return MessageResponse(message=f"Template #{template_id} + 참조 strategy {len(refs)}개 cascade 삭제됨")

    # cascade=False: 비활성화만
    tpl.is_active = False
    db.commit()
    return MessageResponse(message=f"Template #{template_id} 비활성화됨 ({len(refs)}개 strategy 인스턴스 참조 중). 모두 종료됐으면 cascade=true 로 재시도하세요")


@router.post("/strategy-templates/cleanup-quick", response_model=MessageResponse)
def cleanup_quick_templates(
    cascade: bool = False,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> MessageResponse:
    """이름이 '_quick_' 로 시작하는 템플릿 일괄 정리.

    - cascade=False: 미사용(인스턴스 없는)은 삭제, 사용 중은 비활성화만.
    - cascade=True : 참조 strategy 가 모두 terminal 이면 strategy 까지 함께 삭제. active 가 있으면 비활성화만.
    """
    from app.models.strategy_instance import StrategyInstance

    candidates = (
        db.query(StrategyTemplate)
        .filter(StrategyTemplate.name.like("\\_quick\\_%"))
        .all()
    )
    terminal_statuses = {"STOPPED", "CLOSED", "CLOSED_BY_TP", "CLOSED_BY_SL", "COMPLETED", "STOPPING"}
    deleted = 0
    deactivated = 0
    cascaded_strategies = 0
    skipped_active = 0

    for tpl in candidates:
        refs = db.query(StrategyInstance).filter(StrategyInstance.strategy_template_id == tpl.id).all()
        if not refs:
            db.delete(tpl)
            deleted += 1
            continue
        if cascade:
            non_terminal = [r for r in refs if (r.status or "").upper() not in terminal_statuses]
            if non_terminal:
                if tpl.is_active:
                    tpl.is_active = False
                    deactivated += 1
                skipped_active += 1
                continue
            for r in refs:
                db.delete(r)
                cascaded_strategies += 1
            db.delete(tpl)
            deleted += 1
        else:
            if tpl.is_active:
                tpl.is_active = False
                deactivated += 1

    db.commit()
    msg = f"삭제 {deleted}개, 비활성화 {deactivated}개"
    if cascade:
        msg += f", strategy 함께 삭제 {cascaded_strategies}개, active 있어 건너뜀 {skipped_active}개"
    return MessageResponse(message=msg)


@router.get("/recent-activity")
def get_recent_activity(
    limit: int = 20,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[dict]:
    """모든 전략의 최근 활동 통합 (orders + risk_events + notifications).

    메인 대시보드 활동 피드용. 시간 역순 정렬, 최근 N건만 반환.
    """
    from sqlalchemy import select as sa_select
    from app.models.order import Order
    from app.models.risk_event import RiskEvent
    from app.models.notification import Notification

    items: list[dict] = []

    # 최근 주문 (체결 위주)
    orders = db.execute(
        sa_select(Order).order_by(Order.updated_at.desc()).limit(limit)
    ).scalars().all()
    for o in orders:
        purpose_ko = {"ENTRY": "진입", "TAKE_PROFIT": "익절", "STOP_LOSS": "손절", "EMERGENCY_CLOSE": "긴급청산"}.get(o.purpose, o.purpose)
        side_ko = "매도 📉" if o.side == "SELL" else "매수 📈"
        is_filled = (o.status or "").upper() == "FILLED"
        ts = o.updated_at if (is_filled and o.updated_at) else o.created_at
        items.append({
            "ts": ts.isoformat(),
            "strategy_id": o.strategy_instance_id,
            "symbol": o.symbol,
            "kind": "ORDER",
            "icon": "✅" if is_filled else "📤",
            "title": f"{purpose_ko}{' 체결' if is_filled else ' 발송'}",
            "detail": f"{side_ko} {o.executed_qty if is_filled else o.orig_qty} @ {o.avg_price if is_filled else o.price}" + (f" — {o.stage_no}단계" if o.stage_no else ""),
        })

    # 최근 리스크 이벤트 (크라이시스/손절 등)
    risk_events = db.execute(
        sa_select(RiskEvent).order_by(RiskEvent.created_at.desc()).limit(limit)
    ).scalars().all()
    for r in risk_events:
        sev_icon = {"CRITICAL": "🚨", "WARNING": "⚠️", "INFO": "ℹ️"}.get(r.severity, "📌")
        # strategy 의 symbol 가져오기 (relationship)
        sym = r.strategy_instance.symbol if r.strategy_instance else "?"
        items.append({
            "ts": r.created_at.isoformat(),
            "strategy_id": r.strategy_instance_id,
            "symbol": sym,
            "kind": "RISK",
            "icon": sev_icon,
            "title": r.title or r.event_type,
            "detail": (r.message or "")[:200],
        })

    # 최근 알림 (Telegram 발송)
    notifications = db.execute(
        sa_select(Notification).order_by(Notification.created_at.desc()).limit(limit)
    ).scalars().all()
    for n in notifications:
        status_icon = "✉️" if (n.send_status or "").upper() == "SENT" else "❌"
        sym = n.strategy_instance.symbol if n.strategy_instance else "시스템"
        items.append({
            "ts": n.created_at.isoformat(),
            "strategy_id": n.strategy_instance_id,
            "symbol": sym,
            "kind": "NOTIFY",
            "icon": status_icon,
            "title": n.title or "알림",
            "detail": (n.body or "")[:200],
        })

    # 시간 역순 정렬 + 상위 limit 만
    items.sort(key=lambda x: x["ts"], reverse=True)
    return items[:limit]


@router.get("/stats")
def get_operation_stats(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """운영 통계 — 전체 전략 분포 + 누적 손익 + 승률 + 크라이시스 발동 횟수.

    대시보드 상단 패널에 표시. 시계열 차트는 다음 phase 에서 추가.
    """
    from decimal import Decimal
    from sqlalchemy import func, select as sa_select
    from app.models.strategy_instance import StrategyInstance

    # 전체/활성/완료/손절 분포
    rows = db.execute(
        sa_select(StrategyInstance.status, func.count(StrategyInstance.id))
        .group_by(StrategyInstance.status)
    ).all()
    status_counts = {r[0]: r[1] for r in rows}
    total = sum(status_counts.values())

    terminal = {"STOPPED", "CLOSED", "CLOSED_BY_TP", "CLOSED_BY_SL", "COMPLETED", "STOPPING"}
    active_count = sum(c for s, c in status_counts.items() if (s or "").upper() not in terminal)
    completed_count = status_counts.get("COMPLETED", 0)
    sl_count = status_counts.get("CLOSED_BY_SL", 0) + status_counts.get("STOPPING", 0)

    # 누적 실현 손익 합계
    realized_total = db.execute(
        sa_select(func.coalesce(func.sum(StrategyInstance.realized_pnl), 0))
    ).scalar_one() or Decimal("0")

    # 승률 (COMPLETED / (COMPLETED + CLOSED_BY_SL)) — 진행 중 제외
    decided = completed_count + sl_count
    win_rate = (Decimal(completed_count) / Decimal(decided) * Decimal("100")) if decided > 0 else Decimal("0")

    # 크라이시스 모드 진입 횟수
    crisis_total = db.execute(
        sa_select(func.count(StrategyInstance.id))
        .where(StrategyInstance.crisis_mode_triggered_at.is_not(None))
    ).scalar_one() or 0
    crisis_active = db.execute(
        sa_select(func.count(StrategyInstance.id))
        .where(
            StrategyInstance.crisis_mode_triggered_at.is_not(None),
            StrategyInstance.status.notin_(list(terminal)),
        )
    ).scalar_one() or 0

    # 평균 max_loss / max_profit (운영 패턴 파악)
    avg_max_loss = db.execute(
        sa_select(func.coalesce(func.avg(StrategyInstance.max_loss_pct), 0))
    ).scalar_one() or Decimal("0")
    avg_max_profit = db.execute(
        sa_select(func.coalesce(func.avg(StrategyInstance.max_profit_pct), 0))
    ).scalar_one() or Decimal("0")

    return {
        "total": total,
        "active": active_count,
        "completed": completed_count,
        "stop_loss": sl_count,
        "win_rate_pct": str(round(win_rate, 2)),
        "realized_pnl_total": str(realized_total),
        "crisis_total": crisis_total,
        "crisis_active": crisis_active,
        "avg_max_loss_pct": str(round(Decimal(str(avg_max_loss)), 2)),
        "avg_max_profit_pct": str(round(Decimal(str(avg_max_profit)), 2)),
        "status_breakdown": status_counts,
    }


@router.post("/test-telegram", response_model=MessageResponse)
def test_telegram(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> MessageResponse:
    """Telegram 연결 테스트 — 한국어 + 이모지 포함된 시스템 알림 1건 발송.

    실제 발송 성공 여부를 검증해 운영자에게 정확한 결과를 알려준다.
    NotificationService.send() 가 silent-fail 하므로 send_status / body 를 직접 검사.
    """
    notification = NotificationService(db).send_system_alert(
        title="🤖 [관리 테스트] 텔레그램 연결 확인",
        body=(
            "✅ 백엔드 → 텔레그램 알림 라인이 정상 동작합니다.\n"
            "📡 채널         : TELEGRAM\n"
            "🔧 발송 경로    : admin API (/admin/test-telegram)\n"
            "📦 메시지 포맷  : HTML (parse_mode=HTML)\n"
            "👤 운영자       : herosys1@gmail.com\n"
            "\n"
            "이제 단계 진입 / 익절 / 손절 / Kill-Switch / 청산 임박 알림이\n"
            "자동으로 이 채널로 발송됩니다."
        ),
    )
    if (notification.send_status or "").upper() == "FAILED":
        # body 끝의 [send_error] ... 부분 추출
        body = notification.body or ""
        err = "unknown"
        if "[send_error]" in body:
            err = body.split("[send_error]", 1)[1].strip()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Telegram 발송 실패 — {err}",
        )
    return MessageResponse(message=f"Telegram 발송 완료 (notification id={notification.id}, ext_id={notification.external_message_id})")


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
