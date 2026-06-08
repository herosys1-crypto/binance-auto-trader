"""Admin — Strategy template CRUD (동적 N단계).

운영자가 strategy template 을 생성/조회/삭제하는 endpoint.
2026-05-14 Phase 4 split: 기존 admin.py 1,360 줄에서 분리 (~325 줄).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.crypto import decrypt_text
from app.core.strategy_status import TERMINAL_STATUSES
from app.models.strategy_template import StrategyTemplate
from app.repositories.exchange_account_repository import ExchangeAccountRepository
from app.schemas.common import MessageResponse

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
    # 2026-05-14 (사용자 요청, alembic 0015): 크라이시스 임계 사용자 정의.
    # NULL = global default -50% / -50~-80 = 그 값 사용 / -100 (이하) = 비활성.
    crisis_max_loss_threshold: Decimal | None = Field(default=None, ge=Decimal("-200"), le=Decimal("-30"))


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
    stop_loss_percent_of_capital: Decimal | None = None
    is_active: bool
    is_favorite: bool = False


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
        crisis_max_loss_threshold=payload.crisis_max_loss_threshold,
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


# ─────────────────────────────────────────────────────────────────────────────
# 🌟 사장님 즐겨찾기 템플릿 (2026-06-09)
#
# 사장님 명시: "기본 세팅 5개 만들수 있게 + 1 클릭 신 전략"
# - is_favorite=True 마킹된 template 만 조회 (최대 5개 권장)
# - 「⭐ 즐겨찾기 템플릿」 카드 = 사장님 자주 쓰는 신 전략 1 클릭
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/strategy-templates/favorites", response_model=list[StrategyTemplateResponse])
def list_favorite_templates(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[StrategyTemplateResponse]:
    """is_favorite=True + is_active=True 인 template 조회 (= 사장님 즐겨찾기).

    사장님 「⭐ 즐겨찾기 템플릿」 카드 = 최대 5개 권장.
    """
    rows = (
        db.query(StrategyTemplate)
        .filter(StrategyTemplate.is_favorite.is_(True))
        .filter(StrategyTemplate.is_active.is_(True))
        .order_by(StrategyTemplate.id.desc())
        .limit(10)  # 안전 한도 (사장님 권장 5개)
        .all()
    )
    return [StrategyTemplateResponse.model_validate(r) for r in rows]


@router.post("/strategy-templates/{template_id}/toggle-favorite", response_model=StrategyTemplateResponse)
def toggle_favorite_template(
    template_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyTemplateResponse:
    """template 즐겨찾기 토글 (= True/False 자동 전환).

    사장님 = 「⭐」 클릭 = 즐겨찾기 추가/제거.
    """
    tpl = db.get(StrategyTemplate, template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
    tpl.is_favorite = not bool(tpl.is_favorite)
    db.commit()
    db.refresh(tpl)
    return StrategyTemplateResponse.model_validate(tpl)
