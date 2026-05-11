from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.crypto import decrypt_text
from app.core.strategy_status import TERMINAL_STATUSES
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
    # 2026-05-11 (사용자 요청): 단계별 추가 isolated 증거금 (USDT). None/0 = 추가 안 함.
    additional_margins: list[Decimal | None] | None = Field(
        default=None,
        description="단계별 추가 isolated 증거금 USDT (None/0 = 추가 안 함). 길이는 capitals 와 같아야 함. 단계 진입 시 add_position_margin 자동 호출.",
    )
    last_stage_trigger_mode: str | None = Field(
        default=None,
        description="마지막 단계 trigger_mode. 미지정 시 SHORT=PRICE_UP_PCT, LONG=PRICE_DOWN_PCT (2026-04-30 변경)",
    )
    last_stage_trigger_percent: Decimal | None = Field(
        default=None,
        description="마지막 단계 trigger_percent. 미지정 시 SHORT=20, LONG=20 (2026-04-30 변경)",
    )
    tp1_percent: Decimal = Field(..., gt=0)
    tp2_percent: Decimal = Field(..., gt=0)
    tp3_percent: Decimal = Field(..., gt=0)
    tp4_percent: Decimal | None = Field(default=None, gt=0)
    tp5_percent: Decimal | None = Field(default=None, gt=0)
    # 2026-05-06: 10단계 익절 확장 (사용자 요청).
    tp6_percent: Decimal | None = Field(default=None, gt=0)
    tp7_percent: Decimal | None = Field(default=None, gt=0)
    tp8_percent: Decimal | None = Field(default=None, gt=0)
    tp9_percent: Decimal | None = Field(default=None, gt=0)
    tp10_percent: Decimal | None = Field(default=None, gt=0)
    tp1_qty_ratio: Decimal = Field(..., gt=0, le=100)
    tp2_qty_ratio: Decimal = Field(..., gt=0, le=100)
    tp3_qty_ratio: Decimal = Field(..., gt=0, le=100)
    tp4_qty_ratio: Decimal | None = Field(default=None, gt=0, le=100)
    tp5_qty_ratio: Decimal | None = Field(default=None, gt=0, le=100)
    tp6_qty_ratio: Decimal | None = Field(default=None, gt=0, le=100)
    tp7_qty_ratio: Decimal | None = Field(default=None, gt=0, le=100)
    tp8_qty_ratio: Decimal | None = Field(default=None, gt=0, le=100)
    tp9_qty_ratio: Decimal | None = Field(default=None, gt=0, le=100)
    tp10_qty_ratio: Decimal | None = Field(default=None, gt=0, le=100)
    stop_loss_percent_of_capital: Decimal = Field(..., gt=0, le=100)
    reentry_policy: Literal["manual_ready", "auto"] = "manual_ready"
    reentry_delay_seconds: int = Field(default=600, ge=10, le=86400)
    reentry_offset_pct: Decimal = Field(default=Decimal("1.0"), ge=0, le=50)


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

    # 2026-05-11: additional_margins 길이 검증
    if payload.additional_margins is not None and len(payload.additional_margins) != len(payload.capitals):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="additional_margins length must match capitals length",
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
    # 2026-05-11 (사용자 요청): 단계별 추가 증거금. None/0 = 추가 안 함.
    if payload.additional_margins:
        stages_config["additional_margins"] = [
            str(m) if m is not None and Decimal(str(m)) > 0 else None
            for m in payload.additional_margins
        ]
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
        tp6_percent=payload.tp6_percent,
        tp7_percent=payload.tp7_percent,
        tp8_percent=payload.tp8_percent,
        tp9_percent=payload.tp9_percent,
        tp10_percent=payload.tp10_percent,
        tp1_qty_ratio=payload.tp1_qty_ratio,
        tp2_qty_ratio=payload.tp2_qty_ratio,
        tp3_qty_ratio=payload.tp3_qty_ratio,
        tp4_qty_ratio=payload.tp4_qty_ratio,
        tp5_qty_ratio=payload.tp5_qty_ratio,
        tp6_qty_ratio=payload.tp6_qty_ratio,
        tp7_qty_ratio=payload.tp7_qty_ratio,
        tp8_qty_ratio=payload.tp8_qty_ratio,
        tp9_qty_ratio=payload.tp9_qty_ratio,
        tp10_qty_ratio=payload.tp10_qty_ratio,
        stop_loss_percent_of_capital=payload.stop_loss_percent_of_capital,
        reentry_policy=payload.reentry_policy,
        reentry_delay_seconds=payload.reentry_delay_seconds,
        reentry_offset_pct=payload.reentry_offset_pct,
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
    # 2026-05-04 fix: 공통 TERMINAL_STATUSES 사용 (REENTRY_READY, KILL_SWITCH_TRIGGERED 빠짐 + STOPPING 포함은 위험).
    terminal_statuses = TERMINAL_STATUSES
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
    force: bool = False,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> MessageResponse:
    """이름이 '_quick_' 로 시작하는 템플릿 일괄 정리.

    - cascade=False, force=False : 미사용(인스턴스 없는)은 삭제, 사용 중은 비활성화만.
    - cascade=True,  force=False : 참조 strategy 가 모두 terminal 이면 strategy 까지 함께 삭제. active 가 있으면 비활성화만.
    - force=True (UX #19, 2026-04-29):
        활성 전략까지 emergency_stop (cancel_all_orders + 시장가 청산) 후
        strategy + template 모두 일괄 삭제. testnet 검증 종료 후 한 번에 깨끗이 정리하는 용도.
        주의: mainnet 에서 사용 시 실제 포지션이 시장가 청산되어 손실 확정될 수 있음.
    """
    from app.models.strategy_instance import StrategyInstance
    from app.services.execution_service import EmergencyCloseInProgress, ExecutionService

    # Bug #14 fix (2026-04-29): PostgreSQL LIKE 의 underscore (_) 는 와일드카드라서
    # 단순히 \\_ 만으로는 매칭 안 됨 (ESCAPE 절 필요). startswith() 가 자동으로 처리해줌.
    candidates = (
        db.query(StrategyTemplate)
        .filter(StrategyTemplate.name.startswith("_quick_"))
        .all()
    )
    # 2026-05-04 fix: 공통 TERMINAL_STATUSES 사용 (이전엔 항목 누락 + STOPPING 위험 포함).
    terminal_statuses = TERMINAL_STATUSES
    deleted = 0
    deactivated = 0
    cascaded_strategies = 0
    skipped_active = 0
    force_closed = 0  # force 모드에서 시장가 청산한 전략 수
    force_close_errors: list[str] = []

    # UX #19: force 모드 — 활성 전략을 먼저 모두 종료시킴
    if force:
        for tpl in candidates:
            refs = db.query(StrategyInstance).filter(StrategyInstance.strategy_template_id == tpl.id).all()
            for r in refs:
                if (r.status or "").upper() in terminal_statuses:
                    continue
                # 거래소 시장가 청산 + 미체결 취소
                try:
                    account = ExchangeAccountRepository(db).get(r.exchange_account_id)
                    if not account:
                        force_close_errors.append(f"#{r.id}: 거래소 계정 없음")
                        continue
                    exec_svc = ExecutionService(
                        db,
                        api_key=decrypt_text(account.api_key_enc),
                        api_secret=decrypt_text(account.api_secret_enc),
                        is_testnet=account.is_testnet,
                    )
                    try:
                        exec_svc.client.cancel_all_orders(symbol=r.symbol)
                    except Exception:
                        pass  # 미체결 없을 수 있음
                    qty = Decimal(str(r.current_position_qty or 0)).copy_abs()
                    if qty > 0:
                        try:
                            exec_svc.emergency_close_position(r.id, quantity=qty)
                        except ValueError:
                            # Bug #8 fix: 거래소 포지션 0 일 때 ValueError. 정상 정리됨.
                            pass
                        except EmergencyCloseInProgress:
                            # 2026-05-08 #120 fix: 다른 caller 가 청산 중 — 정상 진행
                            pass
                    r.status = "STOPPED"
                    r.current_position_qty = Decimal("0")
                    force_closed += 1
                except Exception as e:
                    force_close_errors.append(f"#{r.id}: {e!s}")
        db.commit()
        # force 모드는 자동으로 cascade=True 로 처리 (모든 전략이 terminal 이 됐으니)
        cascade = True

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
    if force:
        msg += f", 강제 청산 {force_closed}개"
        if force_close_errors:
            msg += f", 청산 에러 {len(force_close_errors)}건: {'; '.join(force_close_errors[:3])}"
    return MessageResponse(message=msg)


@router.get("/export/strategies")
def export_strategies_csv(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """전략 인스턴스 전체를 CSV 로 내보내기. 회계/세무 분석용."""
    import csv
    import io
    from sqlalchemy import select as sa_select
    from app.models.strategy_instance import StrategyInstance
    from fastapi.responses import StreamingResponse

    rows = db.execute(
        sa_select(StrategyInstance).order_by(StrategyInstance.id.asc())
    ).scalars().all()

    buf = io.StringIO()
    # 한글 Excel 호환 — UTF-8 BOM 추가
    buf.write("﻿")
    writer = csv.writer(buf)
    writer.writerow([
        "id", "심볼", "방향", "상태", "현재단계", "레버리지",
        "시작가", "평균진입가", "포지션수량", "투입자본",
        "실현손익", "미실현손익", "최대손실%", "최대이익%",
        "크라이시스진입시각", "크라이시스첫TP시각", "재진입대기",
        "시작시각", "종료시각", "생성시각",
    ])
    for r in rows:
        writer.writerow([
            r.id, r.symbol, r.side, r.status, r.current_stage, r.leverage,
            str(r.start_price) if r.start_price else "",
            str(r.avg_entry_price) if r.avg_entry_price else "",
            str(r.current_position_qty), str(r.invested_capital),
            str(r.realized_pnl), str(r.unrealized_pnl),
            str(r.max_loss_pct) if r.max_loss_pct is not None else "",
            str(r.max_profit_pct) if r.max_profit_pct is not None else "",
            r.crisis_mode_triggered_at.isoformat() if r.crisis_mode_triggered_at else "",
            r.crisis_first_tp_done_at.isoformat() if r.crisis_first_tp_done_at else "",
            "TRUE" if r.reentry_ready else "FALSE",
            r.started_at.isoformat() if r.started_at else "",
            r.stopped_at.isoformat() if r.stopped_at else "",
            r.created_at.isoformat() if r.created_at else "",
        ])
    buf.seek(0)
    filename = f"strategies_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/orders")
def export_orders_csv(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """주문 전체를 CSV 로 내보내기."""
    import csv
    import io
    from sqlalchemy import select as sa_select
    from app.models.order import Order
    from fastapi.responses import StreamingResponse

    rows = db.execute(
        sa_select(Order).order_by(Order.id.asc())
    ).scalars().all()

    buf = io.StringIO()
    buf.write("﻿")
    writer = csv.writer(buf)
    writer.writerow([
        "id", "전략ID", "단계", "유형", "심볼", "방향", "포지션방향", "주문타입",
        "거래소주문ID", "트리거가", "지정가", "주문수량", "체결수량", "체결단가",
        "상태", "발송시각", "갱신시각",
    ])
    for o in rows:
        writer.writerow([
            o.id, o.strategy_instance_id, o.stage_no or "", o.purpose, o.symbol,
            o.side, o.position_side, o.order_type,
            o.exchange_order_id or "",
            str(o.trigger_price) if o.trigger_price else "",
            str(o.price) if o.price else "",
            str(o.orig_qty) if o.orig_qty else "",
            str(o.executed_qty),
            str(o.avg_price) if o.avg_price else "",
            o.status,
            o.created_at.isoformat() if o.created_at else "",
            o.updated_at.isoformat() if o.updated_at else "",
        ])
    buf.seek(0)
    filename = f"orders_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/system-health")
def get_system_health(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """8개 컴포넌트의 통합 상태 — 대시보드 시스템 패널용.

    각 컴포넌트는 status: 'ok' | 'warn' | 'down' + detail 메시지.
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import text
    from app.core.redis_client import get_redis_client
    from app.core.config import settings

    components: dict[str, dict] = {}

    # 1. API (이 endpoint 가 응답한다 = 작동 중)
    components["api"] = {"status": "ok", "label": "API 서버", "detail": "응답 정상"}

    # 2. DB
    try:
        db.execute(text("SELECT 1"))
        components["db"] = {"status": "ok", "label": "데이터베이스", "detail": "PostgreSQL 연결됨"}
    except Exception as e:  # pragma: no cover
        components["db"] = {"status": "down", "label": "데이터베이스", "detail": f"DB 오류: {e}"}

    # 3. Redis
    try:
        client = get_redis_client()
        client.ping()
        components["redis"] = {"status": "ok", "label": "Redis 캐시", "detail": "Redis 연결됨"}
    except Exception as e:  # pragma: no cover
        components["redis"] = {"status": "down", "label": "Redis 캐시", "detail": f"Redis 오류: {e}"}

    # 4. Scheduler (Redis heartbeat 키 확인)
    try:
        client = get_redis_client()
        if client.exists("health:scheduler:leader"):
            components["scheduler"] = {"status": "ok", "label": "스케줄러", "detail": "Leader heartbeat 정상"}
        else:
            components["scheduler"] = {"status": "warn", "label": "스케줄러", "detail": "heartbeat 없음 (60s 내 갱신 필요)"}
    except Exception:  # pragma: no cover
        components["scheduler"] = {"status": "down", "label": "스케줄러", "detail": "확인 불가"}

    # 5. User Stream (Redis heartbeat 키)
    try:
        client = get_redis_client()
        if client.exists("health:user_stream:connected"):
            components["user_stream"] = {"status": "ok", "label": "Binance User Stream", "detail": "WebSocket 연결됨"}
        else:
            components["user_stream"] = {"status": "warn", "label": "Binance User Stream", "detail": "heartbeat 없음 (재연결 필요)"}
    except Exception:  # pragma: no cover
        components["user_stream"] = {"status": "down", "label": "Binance User Stream", "detail": "확인 불가"}

    # 6. Telegram (설정 + 최근 발송 성공률)
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        components["telegram"] = {"status": "warn", "label": "Telegram", "detail": "TOKEN 또는 CHAT_ID 미설정"}
    else:
        from app.models.notification import Notification
        recent = db.execute(
            text("SELECT send_status FROM notifications WHERE channel='TELEGRAM' AND created_at > NOW() - INTERVAL '24 hours' ORDER BY id DESC LIMIT 5")
        ).scalars().all()
        if not recent:
            components["telegram"] = {"status": "ok", "label": "Telegram", "detail": "설정 완료 (최근 24h 발송 없음)"}
        else:
            failed = sum(1 for s in recent if (s or "").upper() == "FAILED")
            if failed == len(recent):
                components["telegram"] = {"status": "down", "label": "Telegram", "detail": f"최근 {len(recent)}건 모두 실패"}
            elif failed > 0:
                components["telegram"] = {"status": "warn", "label": "Telegram", "detail": f"최근 {len(recent)}건 중 {failed}건 실패"}
            else:
                components["telegram"] = {"status": "ok", "label": "Telegram", "detail": f"최근 {len(recent)}건 모두 발송 성공"}

    # 7. Sentry (DSN 설정 여부)
    if settings.sentry_dsn:
        components["sentry"] = {"status": "ok", "label": "Sentry", "detail": "DSN 설정됨 (에러 추적 활성)"}
    else:
        components["sentry"] = {"status": "warn", "label": "Sentry", "detail": "DSN 미설정 (mainnet 직전 권장)"}

    # 8. DB Backup (마지막 백업 row 확인 — 실제 파일 시스템 확인은 어려우니 가능 여부만)
    components["db_backup"] = {"status": "ok", "label": "DB 자동 백업", "detail": "스케줄러 동작 (매일 03:00 UTC)"}

    # 전체 상태 요약
    statuses = [c["status"] for c in components.values()]
    overall = "down" if "down" in statuses else ("warn" if "warn" in statuses else "ok")

    return {
        "overall": overall,
        "components": components,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/notifications-by-title")
def get_notifications_by_title(
    title_like: str,
    limit: int = 200,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[dict]:
    """제목 패턴 매칭 알림 목록 — 운영 통계 패널의 TP/TRAIL 셀 클릭 시 사용.

    2026-05-12 (사용자 요청): TP1~10/TRAILING_TP 카운트 셀 클릭 → 해당 알림 상세 목록.
    title_like 는 SQL LIKE 패턴 (% 허용). 보안상 길이 200자 이내.

    예: title_like='%[TP1 익절%' → TP1 익절 알림 모두
        title_like='%[TRAILING_TP 익절%' → 트레일링 청산 모두
    """
    from sqlalchemy import select as sa_select
    from app.models.notification import Notification
    if not title_like or len(title_like) > 200:
        raise HTTPException(status_code=400, detail="title_like 1~200자")
    limit = max(1, min(limit, 1000))
    rows = db.execute(
        sa_select(Notification)
        .where(Notification.title.like(title_like))
        .order_by(Notification.created_at.desc())
        .limit(limit)
    ).scalars().all()
    out: list[dict] = []
    for n in rows:
        sym = n.strategy_instance.symbol if n.strategy_instance else None
        side = n.strategy_instance.side if n.strategy_instance else None
        out.append({
            "id": n.id,
            "ts": n.created_at.isoformat() if n.created_at else None,
            "strategy_id": n.strategy_instance_id,
            "symbol": sym,
            "side": side,
            "title": n.title or "",
            "body": (n.body or "")[:500],
            "send_status": n.send_status,
        })
    return out


@router.get("/recent-activity")
def get_recent_activity(
    limit: int = 20,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[dict]:
    """모든 전략의 최근 활동 통합 (orders + risk_events + notifications).

    메인 대시보드 활동 피드용. 시간 역순 정렬, 최근 N건만 반환.
    2026-05-12 (사용자 요청): 20건 한도 → 사용자가 20/50/100/200/500 선택 가능.
    상한 1000 — 메모리 안전 (3 source × 1000 = 3000 sort).
    """
    limit = max(1, min(limit, 1000))
    from sqlalchemy import select as sa_select
    from app.models.order import Order
    from app.models.risk_event import RiskEvent
    from app.models.notification import Notification

    items: list[dict] = []

    # 최근 주문 (체결 위주).
    # 2026-05-12 (사용자 요청): 「매도/매수」 → 「SHORT/LONG 포지션 진입/청산」 으로 변경.
    # 사용자 의견: 「실제로 매도/매수가 일어나긴 하지만 의미는 포지션 진입/청산이라
    # 헷갈림. 실제 사용 용어로 표시해줘」.
    # 매핑:
    #   ENTRY  + SELL  → SHORT 포지션 진입
    #   ENTRY  + BUY   → LONG 포지션 진입
    #   TP/SL/EMERG + BUY  → SHORT 포지션 청산 (SHORT 닫으려면 BUY)
    #   TP/SL/EMERG + SELL → LONG 포지션 청산 (LONG 닫으려면 SELL)
    orders = db.execute(
        sa_select(Order).order_by(Order.updated_at.desc()).limit(limit)
    ).scalars().all()
    _close_purposes = {"TAKE_PROFIT", "STOP_LOSS", "EMERGENCY_CLOSE"}
    _purpose_ko = {"ENTRY": "진입", "TAKE_PROFIT": "익절", "STOP_LOSS": "손절", "EMERGENCY_CLOSE": "긴급청산"}
    for o in orders:
        purpose_upper = (o.purpose or "").upper()
        order_side = (o.side or "").upper()
        is_close = purpose_upper in _close_purposes
        if is_close:
            # 청산: BUY=SHORT 청산, SELL=LONG 청산
            pos_dir = "SHORT" if order_side == "BUY" else ("LONG" if order_side == "SELL" else "?")
            action_ko = "포지션 청산"
        else:
            # 진입 (ENTRY 또는 unknown — 진입으로 간주)
            pos_dir = "SHORT" if order_side == "SELL" else ("LONG" if order_side == "BUY" else "?")
            action_ko = "포지션 진입"
        dir_emoji = "📉" if pos_dir == "SHORT" else ("📈" if pos_dir == "LONG" else "❓")
        purpose_ko = _purpose_ko.get(purpose_upper, o.purpose or "")
        is_filled = (o.status or "").upper() == "FILLED"
        ts = o.updated_at if (is_filled and o.updated_at) else o.created_at
        # title — 청산이면 사유 추가 (익절/손절/긴급청산), 진입이면 단순 「SHORT 포지션 진입」
        if is_close:
            title = f"{dir_emoji} {pos_dir} {action_ko} ({purpose_ko}){' 체결' if is_filled else ' 발송'}"
        else:
            title = f"{dir_emoji} {pos_dir} {action_ko}{' 체결' if is_filled else ' 발송'}"
        qty = o.executed_qty if is_filled else o.orig_qty
        px = o.avg_price if is_filled else o.price
        items.append({
            "ts": ts.isoformat(),
            "strategy_id": o.strategy_instance_id,
            "symbol": o.symbol,
            "kind": "ORDER",
            "icon": "✅" if is_filled else "📤",
            "title": title,
            "detail": f"수량 {qty} @ {px}" + (f" — {o.stage_no}단계" if o.stage_no else ""),
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
    # 익절 카운트 (사용자 기획 B 안, 2026-04-30): notification 의 TP 알림 합계.
    # 자동 TP 만 익절로 분류 — 수동 emergency_stop 은 수익이 나도 익절 X.
    # 이전 status 기반은 부분 TP 누락 + 수동 청산이 익절로 잘못 분류되는 문제 해결.
    from app.models.notification import Notification as _Notif
    completed_count = db.execute(
        sa_select(func.count(_Notif.id))
        .where(_Notif.title.like("%익절 체결%"))
    ).scalar_one() or 0
    # 손절 카운트 — 자동 SL 알림 기준. 수동 stopping 제외.
    sl_count = db.execute(
        sa_select(func.count(_Notif.id))
        .where(_Notif.title.like("%[손절 발동]%"))
    ).scalar_one() or 0
    # 수동 종료 카운트 (참고용)
    manual_stop_count = db.execute(
        sa_select(func.count(StrategyInstance.id))
        .where(StrategyInstance.status.in_(["STOPPED", "STOPPING"]))
    ).scalar_one() or 0

    # 누적 실현 손익 합계
    realized_total = db.execute(
        sa_select(func.coalesce(func.sum(StrategyInstance.realized_pnl), 0))
    ).scalar_one() or Decimal("0")

    # 2026-05-06 fix (사용자 보고): strategy 단위 손익 분류 — 알림 기반 승률은 부정확.
    # 손실 strategy 가 「[손절 발동]」 알림 없이 STOPPED 되면 (수동 정리 또는 -50% 임계
    # 미달) 분모에서 빠져 승률 100% 잘못 계산됐음. 실제 strategy.realized_pnl 부호 기준.
    profit_strategy_count = db.execute(
        sa_select(func.count(StrategyInstance.id))
        .where(StrategyInstance.realized_pnl > 0)
    ).scalar_one() or 0
    loss_strategy_count = db.execute(
        sa_select(func.count(StrategyInstance.id))
        .where(StrategyInstance.realized_pnl < 0)
    ).scalar_one() or 0
    decided_strategy_count = profit_strategy_count + loss_strategy_count
    win_rate = (
        Decimal(profit_strategy_count) / Decimal(decided_strategy_count) * Decimal("100")
        if decided_strategy_count > 0 else Decimal("0")
    )
    # 알림 기반 승률 (이전 호환 + tooltip 노출용) — 명칭 명확화.
    decided_alert = completed_count + sl_count
    win_rate_alert_based = (
        Decimal(completed_count) / Decimal(decided_alert) * Decimal("100")
        if decided_alert > 0 else Decimal("0")
    )

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

    # TP 단계별 카운트 — notification 의 title prefix 로 집계.
    # 2026-05-12: TP1~10 + TRAILING_TP 동적 확장 (사용자 요청 — 기존 TP1~5 만 집계로
    # TP6~10 발동분 누락. TRAILING_TP 도 별도 카운트해서 trailing 빈도 파악 가능).
    from app.models.notification import Notification
    tp_breakdown = {}
    for n in range(1, 11):
        level = f"TP{n}"
        tp_breakdown[level] = db.execute(
            sa_select(func.count(Notification.id))
            .where(Notification.title.like(f"%[{level} 익절%"))
        ).scalar_one() or 0
    tp_breakdown["TRAILING_TP"] = db.execute(
        sa_select(func.count(Notification.id))
        .where(Notification.title.like("%[TRAILING_TP 익절%"))
    ).scalar_one() or 0

    return {
        "total": total,
        "active": active_count,
        "completed": completed_count,  # 익절 알림 건수 (한 strategy 가 다단계 거치면 중복)
        "stop_loss": sl_count,         # 손절 발동 알림 건수
        "manual_stop": manual_stop_count,
        "win_rate_pct": str(round(win_rate, 2)),  # 2026-05-06 부터 strategy 단위
        "win_rate_alert_based_pct": str(round(win_rate_alert_based, 2)),  # 이전 호환
        # 2026-05-06: strategy 단위 손익 분류 (정확한 승률 계산용)
        "profit_strategy_count": profit_strategy_count,
        "loss_strategy_count": loss_strategy_count,
        "decided_strategy_count": decided_strategy_count,
        "realized_pnl_total": str(realized_total),
        "crisis_total": crisis_total,
        "crisis_active": crisis_active,
        "avg_max_loss_pct": str(round(Decimal(str(avg_max_loss)), 2)),
        "avg_max_profit_pct": str(round(Decimal(str(avg_max_profit)), 2)),
        "status_breakdown": status_counts,
        "tp_breakdown": tp_breakdown,
    }


@router.get("/stats/breakdown")
def get_stats_breakdown(
    view: str = "strategies",
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """운영 통계 상세 — 사용자가 운영 통계 패널의 셀 클릭 시 띄울 모달 데이터.

    2026-05-06 (사용자 요청): 합계만 보이는 패널의 산출 근거 가시화.
    archive 된 strategy 도 포함 (realized_pnl 통계 일관성 유지 목적).

    view 옵션:
    - "strategies" (default): 모든 strategy 별 분류 + 손익 + 라이프사이클
    - "realized": realized_pnl != 0 인 strategy 만 (수익/손실 분류, 절댓값 정렬)
    - "losses": 손실/STOPPED 분류 (감사 시점 detail)
    """
    from sqlalchemy import select as sa_select, func, desc
    from app.models.strategy_instance import StrategyInstance
    from app.models.notification import Notification

    if view not in {"strategies", "realized", "losses"}:
        raise HTTPException(status_code=400, detail=f"Unknown view: {view}")

    # 공통 select — 핵심 필드만 (응답 가벼움)
    base = sa_select(
        StrategyInstance.id,
        StrategyInstance.symbol,
        StrategyInstance.side,
        StrategyInstance.status,
        StrategyInstance.current_stage,
        StrategyInstance.realized_pnl,
        StrategyInstance.unrealized_pnl,
        StrategyInstance.max_loss_pct,
        StrategyInstance.max_profit_pct,
        StrategyInstance.crisis_mode_triggered_at,
        StrategyInstance.is_archived,
        StrategyInstance.started_at,
        StrategyInstance.stopped_at,
        StrategyInstance.created_at,
    )

    # 2026-05-08 fix (사용자 보고): realized 탭이 PNL 절대값 큰 순이라 최신 데이터가
    # 안 보이던 문제. 모든 view 를 「최신 시작 순」 으로 통일 — 사용자가 가장 알고 싶은 것은
    # "최근 거래가 어떻게 됐나". 정렬 기준 변경 시 created_at 우선, ID 폴백 (옛날 row 호환).
    _recent_first = (desc(StrategyInstance.created_at), desc(StrategyInstance.id))
    if view == "realized":
        rows = db.execute(
            base.where(StrategyInstance.realized_pnl != 0).order_by(*_recent_first)
        ).all()
    elif view == "losses":
        # 2026-05-12 (사용자 보고): 「손실/감사」 view 가 realized_pnl<0 만 필터링.
        # 수동 정지 (STOPPED/STOPPING) + 크라이시스 모드 진입 + max_loss<-10% 모두 누락.
        # 사용자 의도: 감사 대상 = 「뭔가 비정상이거나 사용자 개입 있었던 strategy 모두」.
        # → realized_pnl<0 OR max_loss_pct<-10 OR 수동정지 OR 크라이시스 진입 (OR 조건).
        from sqlalchemy import or_
        rows = db.execute(
            base.where(or_(
                StrategyInstance.realized_pnl < 0,
                StrategyInstance.max_loss_pct < Decimal("-10"),
                StrategyInstance.status.in_(["STOPPED", "STOPPING"]),
                StrategyInstance.crisis_mode_triggered_at.is_not(None),
            )).order_by(*_recent_first)
        ).all()
    else:  # strategies
        rows = db.execute(base.order_by(*_recent_first)).all()

    def _classify(realized, status, stage, crisis, max_loss):
        # 2026-05-12: 「수동정지」 분류 추가 — STOPPED/STOPPING 인 strategy 명시.
        # 우선순위: 실현 손익 > 크라이시스 > 수동정지 > 큰 미실현 손실 > 종료/진행.
        if realized is not None and Decimal(str(realized)) > 0:
            return "수익"
        if realized is not None and Decimal(str(realized)) < 0:
            return "손실"
        if crisis is not None:
            return "🚨크라이시스"
        if status in {"STOPPED", "STOPPING"}:
            return "✋수동정지"
        if max_loss is not None and Decimal(str(max_loss)) < Decimal("-10"):
            return "⚠️큰낙폭"
        if status in {"COMPLETED", "CLOSED", "REENTRY_READY"}:
            return "BREAKEVEN" if (stage or 0) > 0 else "미진입_종료"
        return "진행중"

    items = [
        {
            "id": r[0],
            "symbol": r[1],
            "side": r[2],
            "status": r[3],
            "current_stage": r[4],
            "realized_pnl": str(r[5] or 0),
            "unrealized_pnl": str(r[6] or 0),
            "max_loss_pct": str(r[7]) if r[7] is not None else None,
            "max_profit_pct": str(r[8]) if r[8] is not None else None,
            "crisis_triggered": r[9] is not None,
            "is_archived": bool(r[10]),
            "started_at": r[11].isoformat() if r[11] else None,
            "stopped_at": r[12].isoformat() if r[12] else None,
            "created_at": r[13].isoformat() if r[13] else None,
            "classification": _classify(r[5], r[3], r[4], r[9], r[7]),
        }
        for r in rows
    ]

    # 요약 — UI 헤더에 표시
    profit_count = sum(1 for x in items if x["classification"] == "수익")
    loss_count = sum(1 for x in items if x["classification"] == "손실")
    realized_sum = sum((Decimal(x["realized_pnl"]) for x in items), Decimal("0"))
    archived_count = sum(1 for x in items if x["is_archived"])

    return {
        "view": view,
        "count": len(items),
        "profit_count": profit_count,
        "loss_count": loss_count,
        "archived_count": archived_count,
        "realized_pnl_sum": str(realized_sum),
        "items": items,
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
    # 2026-05-04 audit fix: user_id 전달 — 다른 user 의 API key 로 symbol-sync 하던 결함 차단.
    account = ExchangeAccountRepository(db).get_first_active_binance(user_id=user_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No active Binance account for current user")
    client = BinanceClient(
        api_key=decrypt_text(account.api_key_enc),
        api_secret=decrypt_text(account.api_secret_enc),
        is_testnet=account.is_testnet,
    )
    count = SymbolSyncService(db, client).sync()
    return MessageResponse(message=f"Synced {count} symbols")


def _verify_account_ownership(db: Session, exchange_account_id: int, user_id: int) -> None:
    """2026-05-04 audit fix: 인증된 user 라도 자기 계정만 조작 가능하도록.

    이전엔 admin endpoint 라고 user_id 검증 없이 모든 계정의 kill-switch 조작 가능.
    multi-user 시 다른 user 의 계정을 임의로 enable/disable 할 수 있는 보안 결함.
    """
    from app.models.exchange_account import ExchangeAccount
    from sqlalchemy import select
    acc = db.execute(
        select(ExchangeAccount)
        .where(ExchangeAccount.id == exchange_account_id)
        .where(ExchangeAccount.user_id == user_id)
    ).scalar_one_or_none()
    if not acc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exchange account #{exchange_account_id} not found (또는 본인 소유 아님)",
        )


# ============================================================================
# System Settings — 운영자 런타임 토글 (2026-05-07 사용자 요청)
# ============================================================================
class WhitelistSettingResponse(BaseModel):
    """화이트리스트 운영 상태."""
    enabled: bool
    allowed_symbols: list[str]
    env_configured: bool  # env 에 ALLOWED_SYMBOLS_CSV 값이 있는지 (없으면 toggle 켜도 무의미)


class WhitelistSettingUpdate(BaseModel):
    enabled: bool


@router.get("/settings/whitelist", response_model=WhitelistSettingResponse)
def get_whitelist_setting(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> WhitelistSettingResponse:
    """현재 화이트리스트 토글 상태 + env 의 허용 심볼 목록."""
    from app.core.config import settings
    from app.services.system_settings_service import SystemSettingsService

    allowed = settings.allowed_symbols_set
    env_configured = allowed is not None
    enabled = SystemSettingsService(db).is_whitelist_enabled(default_from_env=env_configured)
    return WhitelistSettingResponse(
        enabled=enabled,
        allowed_symbols=sorted(allowed) if allowed else [],
        env_configured=env_configured,
    )


@router.patch("/settings/whitelist", response_model=WhitelistSettingResponse)
def update_whitelist_setting(
    payload: WhitelistSettingUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> WhitelistSettingResponse:
    """화이트리스트 토글 변경 (DB 영속). 즉시 적용 — strategy 생성 시점에 반영."""
    from app.core.config import settings
    from app.services.system_settings_service import SystemSettingsService

    SystemSettingsService(db).set(
        "whitelist_enabled",
        payload.enabled,
        updated_by=user_id,
        description="화이트리스트 적용 여부 (운영자 UI 토글)",
    )
    allowed = settings.allowed_symbols_set
    return WhitelistSettingResponse(
        enabled=payload.enabled,
        allowed_symbols=sorted(allowed) if allowed else [],
        env_configured=allowed is not None,
    )


@router.post("/kill-switch/{exchange_account_id}/enable", response_model=MessageResponse)
def enable_kill_switch(
    exchange_account_id: int,
    reason_code: str = "MANUAL",
    reason_message: str = "Manually triggered by admin",
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> MessageResponse:
    _verify_account_ownership(db, exchange_account_id, user_id)
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
    """Kill-Switch 해제 + 오늘의 daily_risk_limit row TRIGGERED → ACTIVE 리셋.

    배경 (2026-05-07 사용자 운영 발견): KS 만 clear 하고 row.status 가 TRIGGERED 로
    남아있으면 update_pnl_and_check 가 'breached and status != TRIGGERED' 가드로
    재발동 안 함. → KS 가 해제된 채 손실이 더 커져도 자동 차단 실패.

    이 fix: KS clear 시 row 도 함께 ACTIVE 로 리셋해서 다음 사이클부터 다시
    임계 검사 가능. (PR #15 의 실 운영 검증에서 발견된 latent 버그)
    """
    from datetime import date
    from app.models.account_daily_risk_limit import AccountDailyRiskLimit
    from sqlalchemy import select as _s

    _verify_account_ownership(db, exchange_account_id, user_id)
    AccountKillSwitchService(db).clear(exchange_account_id)

    # 오늘의 daily_risk_limit row 가 TRIGGERED 면 ACTIVE 로 리셋 (재검사 가능 상태로).
    row = db.execute(
        _s(AccountDailyRiskLimit)
        .where(AccountDailyRiskLimit.exchange_account_id == exchange_account_id)
        .where(AccountDailyRiskLimit.trading_date == date.today())
    ).scalar_one_or_none()
    if row and row.status == "TRIGGERED":
        row.status = "ACTIVE"
        db.commit()
    return MessageResponse(message=f"Kill switch cleared on account {exchange_account_id}")


# =====================================================================
# 시스템 상태 통합 (대시보드 배너용) — 좀비/Kill-Switch/Critical 이벤트 한 번에
# =====================================================================
@router.get("/system-status")
def get_system_status(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """대시보드 상단 경고 배너용 통합 시스템 상태.

    응답:
      {
        "kill_switches_active": [{exchange_account_id, reason_code, reason_message, triggered_at}, ...],
        "critical_events_recent": [{id, event_type, title, message, created_at, strategy_id}, ...],
        "stuck_zombie_count": int,   # Redis 의 zombie:stuck_count:* 키 개수
        "is_healthy": bool,           # 위 셋 다 비어있고 stuck=0 이면 true
      }
    """
    from datetime import timedelta
    from sqlalchemy import select
    from app.models.account_kill_switch import AccountKillSwitch
    from app.models.risk_event import RiskEvent

    # 1) 활성 Kill-Switch
    ks_rows = db.execute(
        select(AccountKillSwitch).where(AccountKillSwitch.is_enabled.is_(True))
    ).scalars().all()
    kill_switches = [
        {
            "exchange_account_id": r.exchange_account_id,
            "reason_code": r.reason_code,
            "reason_message": r.reason_message,
            "triggered_at": r.triggered_at.isoformat() if r.triggered_at else None,
        }
        for r in ks_rows
    ]

    # 2) 최근 1시간 CRITICAL 이벤트
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    crit_rows = db.execute(
        select(RiskEvent)
        .where(RiskEvent.severity == "CRITICAL")
        .where(RiskEvent.created_at >= cutoff)
        .order_by(RiskEvent.id.desc())
        .limit(20)
    ).scalars().all()
    critical_events = [
        {
            "id": r.id,
            "event_type": r.event_type,
            "title": r.title,
            "message": r.message,
            "strategy_id": r.strategy_instance_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in crit_rows
    ]

    # 3) Redis stuck zombie counter
    stuck_count = 0
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        # SCAN 으로 키 개수 (KEYS 는 production 에서 비권장)
        count = 0
        for _ in r.scan_iter(match="zombie:stuck_count:*", count=100):
            count += 1
        stuck_count = count
    except Exception:
        pass

    is_healthy = (
        len(kill_switches) == 0
        and len(critical_events) == 0
        and stuck_count == 0
    )
    return {
        "kill_switches_active": kill_switches,
        "critical_events_recent": critical_events,
        "stuck_zombie_count": stuck_count,
        "is_healthy": is_healthy,
    }


# ============================================================================
# Layer 2 (2026-05-09 사용자 요청): 운영 점검 dashboard endpoint.
# health_check.py CLI 와 같은 데이터를 JSON 으로 반환 — UI 「🩺 점검」 탭 용.
# ============================================================================

# health_check.py 와 동일 — 정상 패턴 (검토 필요 분류 제외)
_BENIGN_EVENT_TYPES = {
    "ORDER_TRADE_UPDATE",
    "ZOMBIE_ORPHAN_RACE_DEFERRED",
    "RECONCILE_RECOVERED_PENDING",
    "RECONCILE_AUTO_STOP_ORPHAN",
    "RECONCILE_STOPPING_ZOMBIE_CLEANUP",
}


@router.get("/health/dashboard")
def get_health_dashboard(
    hours: int = 24,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """운영 점검 dashboard — 직전 N시간 거래/이벤트/손익 요약.

    UI 「🩺 점검」 탭이 호출. health_check.py CLI 와 동일 데이터 형식.
    """
    from collections import Counter
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    from sqlalchemy import func
    from app.models.notification import Notification
    from app.models.order import Order
    from app.models.risk_event import RiskEvent
    from app.models.strategy_instance import StrategyInstance
    from app.core.strategy_status import TERMINAL_STATUSES

    if hours < 1 or hours > 720:  # 최대 30일
        raise HTTPException(status_code=400, detail="hours 는 1~720 범위")

    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    # ----- 거래 활동 -----
    entry_count = db.execute(
        select(func.count(Order.id))
        .where(Order.purpose == "ENTRY")
        .where(Order.status == "FILLED")
        .where(Order.created_at >= since)
    ).scalar() or 0
    exit_count = db.execute(
        select(func.count(Order.id))
        .where(Order.purpose == "EXIT")
        .where(Order.status == "FILLED")
        .where(Order.created_at >= since)
    ).scalar() or 0
    new_strategies = db.execute(
        select(func.count(StrategyInstance.id))
        .where(StrategyInstance.created_at >= since)
    ).scalar() or 0

    # ----- 손익 -----
    total_realized = db.execute(
        select(func.sum(StrategyInstance.realized_pnl))
    ).scalar() or Decimal("0")
    active_strategies = db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.status.notin_(TERMINAL_STATUSES))
        .where(StrategyInstance.is_archived.is_(False))
    ).scalars().all()
    unrealized = sum(Decimal(str(s.unrealized_pnl or 0)) for s in active_strategies)

    # ----- 텔레그램 -----
    notif_total = db.execute(
        select(func.count(Notification.id)).where(Notification.created_at >= since)
    ).scalar() or 0
    notif_failed = db.execute(
        select(func.count(Notification.id))
        .where(Notification.created_at >= since)
        .where(Notification.send_status != "SENT")
    ).scalar() or 0

    # ----- 위험 이벤트 -----
    events = db.execute(
        select(RiskEvent)
        .where(RiskEvent.created_at >= since)
        .order_by(RiskEvent.id.desc())
    ).scalars().all()
    sev_counts: Counter = Counter()
    type_counts: Counter = Counter()
    action_needed: list[dict] = []
    for e in events:
        sev_counts[e.severity] += 1
        type_counts[e.event_type] += 1
        if e.severity in ("CRITICAL", "ERROR") and e.event_type not in _BENIGN_EVENT_TYPES:
            if len(action_needed) < 20:  # top 20 만 반환
                action_needed.append({
                    "created_at": e.created_at.isoformat(),
                    "severity": e.severity,
                    "event_type": e.event_type,
                    "title": e.title,
                    "strategy_instance_id": e.strategy_instance_id,
                })

    # ----- 권장 조치 -----
    recommendations = []
    rl = type_counts.get("POSITION_RECONCILE_FAILED", 0) + type_counts.get("POSITION_RECONCILE_ERROR", 0)
    if rl >= 5:
        recommendations.append(f"⚙️ Reconcile 실패 {rl}회 — Binance API rate limit 의심")
    orph = type_counts.get("ZOMBIE_ORPHAN_EXCHANGE_POSITION", 0)
    if orph >= 5:
        recommendations.append(f"🚨 Orphan 반복 {orph}회 — 거래소 직접 점검")
    qm = type_counts.get("POSITION_QTY_MISMATCH", 0)
    if qm >= 3:
        recommendations.append(f"⚖️ qty mismatch {qm}회 — 부분 체결 검토")
    if sev_counts.get("CRITICAL", 0) > 0:
        recommendations.append(f"🚨 CRITICAL {sev_counts['CRITICAL']}건 — 즉시 확인")
    if notif_failed > 0:
        recommendations.append(f"📱 텔레그램 실패 {notif_failed}건 — 토큰/네트워크 확인")

    # 빈도 top 5 (정상 마커 포함)
    top_events = [
        {"event_type": et, "count": cnt, "is_benign": et in _BENIGN_EVENT_TYPES}
        for et, cnt in type_counts.most_common(5)
    ]

    return {
        "period_hours": hours,
        "since": since.isoformat(),
        "is_healthy": len(action_needed) == 0 and notif_failed == 0,
        "trading": {
            "new_strategies": new_strategies,
            "entries": entry_count,
            "exits": exit_count,
        },
        "pnl": {
            "realized_total": str(total_realized),
            "unrealized": str(unrealized),
            "active_count": len(active_strategies),
        },
        "telegram": {
            "sent": notif_total,
            "failed": notif_failed,
        },
        "events": {
            "total": len(events),
            "by_severity": dict(sev_counts),
            "top_5": top_events,
        },
        "action_needed": {
            "count": sum(1 for e in events if e.severity in ("CRITICAL", "ERROR") and e.event_type not in _BENIGN_EVENT_TYPES),
            "items": action_needed,
        },
        "recommendations": recommendations,
    }
