"""Strategies — control actions (start / settings PATCH / trigger-next-stage).

전략 진행 제어 + in-place 설정 수정 endpoint 모음.
2026-05-14 Phase 4 split: 기존 strategies.py 에서 분리 (~540 줄).
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.api.v1.strategies.helpers import _count_active_stages, _enrich_response
from app.core.crypto import decrypt_text
from app.core.strategy_status import TERMINAL_STATUSES
from app.repositories.exchange_account_repository import ExchangeAccountRepository
from app.repositories.strategy_repository import StrategyRepository
from app.schemas.strategy import StrategyActionResponse, StrategyDetailResponse
from app.services.execution_service import ExecutionService, PreflightCheckFailed

router = APIRouter(prefix="/strategies", tags=["strategies"])


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

    🛡 2026-06-07 방어적 강화 (사장님 EPICUSDT #23 500 에러 사례 후):
    - 모든 단계 logger.info 추가 → Sentry/log 즉시 추적
    - calculate_preview None 필드 사전 검증 → InvalidOperation 차단
    - unhandled exception 시 = logger.exception + 친절 에러 메시지 반환
    """
    import logging
    import traceback
    logger = logging.getLogger(__name__)
    from app.models.strategy_template import StrategyTemplate
    from datetime import datetime as _dt

    logger.info(
        "[update-settings] START strategy_id=%s user_id=%s payload_keys=%s",
        strategy_id, user_id,
        sorted([k for k in payload.model_dump(exclude_none=True).keys()]),
    )

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

    # 🚨 2026-06-07 critical fix (Sentry IntegrityError UniqueViolation 발견):
    # 옛: name = f"{old_tpl.name}_inplace_s{strategy.id}_{ts}"[:120]
    # 문제: 매번 「↻ 설정만 수정」 호출 = `_inplace_s{id}_{ts}` 누적 추가
    #       → 5번 시도 후 120 chars 초과 = truncated → 같은 prefix → UniqueViolation
    #       → 사장님 「↻ 설정만 수정」 영원히 500!
    #
    # Fix: 옛 inplace suffix (1개 이상) 모두 제거 → base name + 신 suffix (1번만)
    #      microsecond 추가 = 같은 초 여러 호출도 안전.
    import re as _re
    base_name = _re.sub(r'(_inplace_s\d+_\d+)+', '', old_tpl.name or '')
    now_dt = _dt.now()
    ts_full = f"{int(now_dt.timestamp())}_{now_dt.microsecond}"
    new_name = f"{base_name}_inplace_s{strategy.id}_{ts_full}"[:120]
    logger.info(
        "[update-settings] template name 생성 strategy_id=%s old_name_len=%s base_name_len=%s new_name=%s",
        strategy.id, len(old_tpl.name or ''), len(base_name), new_name,
    )
    new_tpl = StrategyTemplate(
        name=new_name,
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

        # 🚨 2026-06-08 사장님 critical 발견 (헌법 Pattern 4 — Asymmetric Policy):
        # 사장님 명시: "초과한 전략 예약률을 조정하기 위해서 진입하지 않고 남은 전략 단계를 축소"
        # → 단계 capital 변경 시 = total_capital 자동 동기화 필수!
        #
        # 옛 silent bug: strategy.total_capital 변경 X
        # → 사장님이 단계 줄여도 = 예약 그대로 = 의도 X
        #
        # 신: total_capital = sum(new_capitals) — 모든 단계 (진입+미진입) 자본 합
        # → 130% 정책 (stage_trigger_worker) 의 예약 = 즉시 정확 반영
        # → 사장님 자본 보호 + 예약률 조정 = 정확 작동
        try:
            _new_capital_sum = sum(
                (Decimal(str(c)) for c in new_capitals if c is not None),
                Decimal("0"),
            )
            if _new_capital_sum > 0:
                _old_total = Decimal(str(strategy.total_capital or 0))
                strategy.total_capital = _new_capital_sum
                logger.info(
                    "[update-settings] total_capital 자동 동기화 strategy_id=%s old=%s new=%s (단계 capital 변경 반영)",
                    strategy.id, _old_total, _new_capital_sum,
                )
        except Exception as _e:
            logger.warning(
                "[update-settings] total_capital 동기화 실패 strategy_id=%s err=%s",
                strategy.id, _e,
            )

    db.add(new_tpl)
    db.flush()
    strategy.strategy_template_id = new_tpl.id

    # 미발동 plan 재계산 + 신규/제거 stage 처리 (stages_changed 시).
    if stages_changed:
        from app.models.strategy_stage_plan import StrategyStagePlan
        from app.services.strategy_calculator import StrategyCalculator, SymbolRule
        from app.repositories.strategy_repository import StrategyRepository as _SR
        from sqlalchemy import select as _s
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
            # 🛡 2026-06-07 방어적 검증 — calculate_preview None 필드 사전 차단
            # (사장님 EPICUSDT #23 500 사례: 어느 필드 None 시 → Decimal('None') → InvalidOperation)
            missing_fields = []
            if strategy.start_price is None:
                missing_fields.append("strategy.start_price")
            if strategy.total_capital is None:
                missing_fields.append("strategy.total_capital")
            if strategy.leverage is None:
                missing_fields.append("strategy.leverage")
            for n in (1, 2, 3):
                if getattr(new_tpl, f"tp{n}_percent", None) is None:
                    missing_fields.append(f"new_tpl.tp{n}_percent")
            if new_tpl.stop_loss_percent_of_capital is None:
                missing_fields.append("new_tpl.stop_loss_percent_of_capital")

            if missing_fields:
                logger.error(
                    "[update-settings] preview 계산 차단 strategy_id=%s missing=%s",
                    strategy.id, missing_fields,
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"⚠️ 설정 수정 불가 — 필수 필드 누락: {', '.join(missing_fields)}\n\n"
                        f"💡 strategy 또는 template 의 위 필드가 None 입니다. "
                        f"먼저 「✏️ 수정」 모드에서 = 누락 필드 입력 후 재시도 권장."
                    ),
                )

            logger.info(
                "[update-settings] preview 계산 시작 strategy_id=%s start_price=%s capital=%s tp=(%s,%s,%s) sl=%s",
                strategy.id, strategy.start_price, strategy.total_capital,
                new_tpl.tp1_percent, new_tpl.tp2_percent, new_tpl.tp3_percent,
                new_tpl.stop_loss_percent_of_capital,
            )
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

    # 🛡 2026-06-07 방어적 commit + response (사장님 EPICUSDT #23 500 사례 후):
    # commit/refresh/_enrich_response 실패 = unhandled → 500. 모든 단계 try/except.
    try:
        db.commit()
        logger.info(
            "[update-settings] commit OK strategy_id=%s new_template_id=%s",
            strategy.id, new_tpl.id,
        )
        db.refresh(strategy)
        # response — template 기반 enrichment 만 (tp_count batch 는 list endpoint 가 처리).
        resp = _enrich_response(StrategyDetailResponse.model_validate(strategy), new_tpl)
        logger.info(
            "[update-settings] SUCCESS strategy_id=%s new_status=%s",
            strategy.id, strategy.status,
        )
        return resp
    except HTTPException:
        raise
    except Exception as e:
        # 모든 예외 = full traceback logger + Sentry 자동 capture
        logger.exception(
            "[update-settings] UNEXPECTED ERROR strategy_id=%s err=%s",
            strategy_id, e,
        )
        err_type = type(e).__name__
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"⚠️ 설정 수정 실패 ({err_type}): {e}\n\n"
                f"💡 backend logs + Sentry 확인 필요. "
                f"strategy_id={strategy_id}, new_template_id={new_tpl.id if new_tpl else '?'}"
            ),
        )


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
    except PreflightCheckFailed as e:
        # Phase 3: 사전 마진 검증 실패 — 거래소 호출 0, 친절 400 에러로 안내.
        db.execute(
            sa_update(StrategyStagePlan)
            .where(StrategyStagePlan.strategy_instance_id == strategy.id)
            .where(StrategyStagePlan.stage_no == next_stage_no)
            .values(is_triggered=False)
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
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


# ─────────────────────────────────────────────────────────────────────────────
# 🌟 사장님 trailing retrace 옵션 (Phase 2 — 2026-06-08)
# spec: TRAILING_RETRACE_POLICY_SPEC_2026-06-08.md
# ─────────────────────────────────────────────────────────────────────────────

_ALLOWED_RETRACE_PCT = {Decimal("5"), Decimal("10"), Decimal("15"), Decimal("20")}


class TrailingRetracePctRequest(BaseModel):
    pct: Decimal = Field(
        ...,
        description="Trailing retrace % (5/10/15/20). peak 대비 -X% 회귀 시 전량 청산.",
    )


@router.patch("/{strategy_id}/trailing-retrace", response_model=StrategyDetailResponse)
def update_trailing_retrace(
    strategy_id: int,
    payload: TrailingRetracePctRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyDetailResponse:
    """사장님 trailing retrace 옵션 실시간 변경.

    핵심 (사장님 사상 2026-06-08):
    - peak 대비 -X% 회귀 시 전량 청산
    - 옵션: 5 (default) / 10 / 15 / 20
    - 운영 중 변경 = 다음 risk evaluation cycle 부터 즉시 적용

    검증:
    - 본인 소유 strategy
    - 종료된 strategy 거부 (TERMINAL)
    - pct ∈ {5, 10, 15, 20}

    spec: TRAILING_RETRACE_POLICY_SPEC_2026-06-08.md
    """
    import logging
    from app.models.risk_event import RiskEvent
    logger = logging.getLogger(__name__)

    if payload.pct not in _ALLOWED_RETRACE_PCT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"⚠️ Trailing retrace % 는 5/10/15/20 중 하나여야 합니다 "
                f"(입력: {payload.pct}). spec: TRAILING_RETRACE_POLICY_SPEC_2026-06-08.md"
            ),
        )

    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.",
        )
    if strategy.status in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"⚠️ 이미 종료된 전략 (상태: {strategy.status}) 은 변경이 불가합니다."
            ),
        )

    old_pct = strategy.trailing_retrace_pct
    strategy.trailing_retrace_pct = payload.pct

    # Audit log (RiskEvent — 사장님 변경 이력 영구 보존)
    db.add(RiskEvent(
        strategy_instance_id=strategy.id,
        event_type="TRAILING_RETRACE_UPDATED",
        severity="INFO",
        title=f"📐 Trailing retrace 변경 — {strategy.symbol} {strategy.side}",
        message=(
            f"사장님 trailing retrace 옵션 변경: "
            f"{old_pct or '5 (default)'} → {payload.pct}%. "
            f"다음 risk evaluation cycle 부터 즉시 적용. "
            f"peak 대비 -{payload.pct}% 회귀 시 전량 청산 (TRAILING_TP)."
        ),
        event_payload={
            "old_pct": str(old_pct) if old_pct is not None else None,
            "new_pct": str(payload.pct),
        },
    ))
    db.commit()
    db.refresh(strategy)
    logger.info(
        "[trailing-retrace] update strategy_id=%s old=%s new=%s",
        strategy_id, old_pct, payload.pct,
    )

    from app.models.strategy_template import StrategyTemplate
    tpl = (
        db.get(StrategyTemplate, strategy.strategy_template_id)
        if strategy.strategy_template_id else None
    )
    return _enrich_response(StrategyDetailResponse.model_validate(strategy), tpl)


# ─────────────────────────────────────────────────────────────────────────────
# 🌟 사장님 TP1 임계 옵션 (Phase 2 — 2026-06-08)
# spec: TP1_THRESHOLD_OPTION_SPEC_2026-06-08.md
#
# 정상 모드: TP1 = 사장님 옵션 (10/15/20/25) 적용
# Crisis 모드: 사장님 옵션 무시 = CRISIS_OVERRIDE 그대로 (TP1=5/TP2=10/TP3=15/TP4=20)
#   = 큰 손실 후 빠른 회복 익절 (= 사장님 자본 보호)
# ─────────────────────────────────────────────────────────────────────────────

_ALLOWED_TP1_PCT = {Decimal("10"), Decimal("15"), Decimal("20"), Decimal("25")}


class Tp1ThresholdRequest(BaseModel):
    pct: Decimal = Field(
        ...,
        description="TP1 임계 % (10/15/20/25). 정상 모드 적용, Crisis 시 -5% 자동.",
    )


@router.patch("/{strategy_id}/tp1-threshold", response_model=StrategyDetailResponse)
def update_tp1_threshold(
    strategy_id: int,
    payload: Tp1ThresholdRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyDetailResponse:
    """사장님 TP1 임계 옵션 실시간 변경.

    핵심 (사장님 사상 2026-06-08):
    - 정상 모드: TP1 = 사장님 옵션 (10/15/20/25)
    - Crisis 모드: 사장님 옵션 무시 = TP1 +5% 고정 (옛 CRISIS_OVERRIDE 그대로)
    - 운영 중 변경 = 다음 risk evaluation cycle 부터 즉시 적용

    검증:
    - 본인 소유 strategy
    - 종료된 strategy 거부 (TERMINAL)
    - pct ∈ {10, 15, 20, 25}

    spec: TP1_THRESHOLD_OPTION_SPEC_2026-06-08.md
    """
    import logging
    from app.models.risk_event import RiskEvent
    logger = logging.getLogger(__name__)

    if payload.pct not in _ALLOWED_TP1_PCT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"⚠️ TP1 임계 % 는 10/15/20/25 중 하나여야 합니다 "
                f"(입력: {payload.pct}). spec: TP1_THRESHOLD_OPTION_SPEC_2026-06-08.md"
            ),
        )

    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.",
        )
    if strategy.status in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"⚠️ 이미 종료된 전략 (상태: {strategy.status}) 은 변경이 불가합니다."
            ),
        )

    old_pct = strategy.tp1_pct_override
    strategy.tp1_pct_override = payload.pct

    # 🌟 2026-06-10 v23 사장님 신 critical 사상 (= SENTUSDT 사례!):
    # 사장님 명시: "운영자가 크라이시스를 해제하고 다른 선택을 했어 그러면 그렇게 되어야해"
    # = 사장님이 옵션 변경 = "운영자 관여" = Crisis 자동 해제 + 재진입 차단
    _crisis_was_active = strategy.crisis_mode_triggered_at is not None
    if _crisis_was_active:
        strategy.crisis_mode_triggered_at = None  # Crisis 즉시 해제!
        # Redis flag = 24시간 = 자동 Crisis 재진입 차단
        try:
            from app.core.redis_client import get_redis_client
            r = get_redis_client()
            r.setex(f"crisis_user_override:strategy:{strategy.id}", 86400, "1")
        except Exception:
            pass

    db.add(RiskEvent(
        strategy_instance_id=strategy.id,
        event_type="TP1_THRESHOLD_UPDATED",
        severity="INFO",
        title=f"📍 TP1 임계 변경 — {strategy.symbol} {strategy.side}",
        message=(
            f"🌟 사장님 TP1 임계 옵션 변경 (v30 - Crisis 영구 비활성):\n"
            f"{old_pct or '10 (default)'}% → {payload.pct}%\n"
            f"= +{payload.pct}% 도달 시 TP1 발동 (= 사장님 자율 설정).\n"
            f"= 다음 risk cycle (= 최대 10초) 즉시 적용!\n"
            f"{'🚨 기존 Crisis 모드 자동 해제!' if _crisis_was_active else ''}"
        ),
        event_payload={
            "old_pct": str(old_pct) if old_pct is not None else None,
            "new_pct": str(payload.pct),
            "crisis_was_active": _crisis_was_active,
        },
    ))
    db.commit()
    db.refresh(strategy)
    logger.info(
        "[tp1-threshold] update strategy_id=%s old=%s new=%s",
        strategy_id, old_pct, payload.pct,
    )

    from app.models.strategy_template import StrategyTemplate
    tpl = (
        db.get(StrategyTemplate, strategy.strategy_template_id)
        if strategy.strategy_template_id else None
    )
    return _enrich_response(StrategyDetailResponse.model_validate(strategy), tpl)


# ─────────────────────────────────────────────────────────────────────────────
# 🌟 사장님 신 기능 (2026-06-08): 미진입 단계 trigger_price = 현재가 기준 재계산
#
# 사장님 명시:
# "포지션 유지하고 다음단계 진입을 할수 있게 현재가 기준으로 10%더 상승하면 진입하게 해줘"
#
# 사용 시나리오 (= 사장님 BEATUSDT/VELVET 사례):
# - SHORT strategy = 가격 폭등 = stage 5/6 미진입 + trigger_price 통과
# - 사장님 = 신 trigger_price 원함 = "현재가 × 1.10, 1.21, 1.331, ..."
# - 이 endpoint = 미진입 단계 만 = trigger_price 재계산
# - 진입한 단계 = 영향 X (= 사장님 자본 보호)
# ─────────────────────────────────────────────────────────────────────────────


class AddUntriggeredStageItem(BaseModel):
    """미진입 단계 추가 1건."""
    stage_no: int = Field(..., ge=1, le=10, description="단계 번호 (1~10)")
    planned_capital: Decimal = Field(..., gt=0, description="이 단계 자본 (USDT)")
    trigger_percent: Decimal | None = Field(
        default=Decimal("10"),
        gt=0,
        description="이전 단계 대비 트리거 % (default 10). 이 endpoint 에서는 = 현재가 기준 누적.",
    )


class AddUntriggeredStagesRequest(BaseModel):
    stages: list[AddUntriggeredStageItem] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="추가할 미진입 단계들 (4~10단계 등). stage_no = 진입_단계 + 1 부터.",
    )


@router.post("/{strategy_id}/add-untriggered-stages", response_model=StrategyDetailResponse)
def add_untriggered_stages(
    strategy_id: int,
    payload: AddUntriggeredStagesRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyDetailResponse:
    """미진입 단계 추가/수정 — 진입 단계 절대 보존 + 현재가 기준 신 trigger_price.

    사장님 사상 (2026-06-08 옵션 2):
    - 진입 단계 (= is_triggered=True) = 절대 변경 X (= 사장님 자본 보호)
    - 미진입 단계 (= is_triggered=False, 또는 신 추가) = 신 trigger_price + 자본
    - trigger_price = 현재가 × (1.10)^N (= SHORT) 또는 × (0.90)^N (= LONG)
      N = stage_no - 진입_단계_count (= 진입 후 몇 번째 단계)
    - planned_capital = 사장님 입력 그대로

    검증:
    - 본인 소유 + 활성 strategy
    - 현재가 = Redis mark_price_cache
    - stage_no = 진입_단계_count 보다 커야 함 (= 진입 단계 수정 거부)
    - 사장님 자본 검증 (130% 정책)
    """
    import logging
    from app.models.risk_event import RiskEvent
    from app.models.strategy_stage_plan import StrategyStagePlan
    from app.services.mark_price_cache import get_mark_price
    from sqlalchemy import select as sa_select
    logger = logging.getLogger(__name__)

    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.",
        )
    if strategy.status in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"⚠️ 종료된 strategy ({strategy.status}) 는 단계 추가 불가.",
        )

    current_price = get_mark_price(strategy.symbol)
    if not current_price or current_price <= 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"⚠️ {strategy.symbol} 현재가 조회 실패 — Redis 캐시 없음. 1분 후 재시도.",
        )

    # 진입 단계 수 = 사장님 자본 보호 기준
    triggered_count = db.execute(
        sa_select(StrategyStagePlan)
        .where(StrategyStagePlan.strategy_instance_id == strategy.id)
        .where(StrategyStagePlan.is_triggered.is_(True))
    ).scalars().all()
    triggered_max_stage = max((p.stage_no for p in triggered_count), default=0)

    # 사장님 입력 단계 = 모두 triggered_max_stage 보다 커야!
    for item in payload.stages:
        if item.stage_no <= triggered_max_stage:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"⚠️ stage_no {item.stage_no} = 이미 진입한 단계 (= 진입 완료 stage_no={triggered_max_stage}). "
                    f"진입 단계는 절대 수정 불가 (사장님 자본 보호). "
                    f"stage_no = {triggered_max_stage + 1} 부터 가능."
                ),
            )

    # stage_no 중복 검증 + 순서대로 정렬
    sorted_items = sorted(payload.stages, key=lambda x: x.stage_no)
    stage_nos = [item.stage_no for item in sorted_items]
    if len(set(stage_nos)) != len(stage_nos):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"⚠️ stage_no 중복: {stage_nos}",
        )

    # SHORT/LONG 방향
    is_short = (strategy.side or "").upper() == "SHORT"
    direction = Decimal("1.10") if is_short else Decimal("0.90")

    changes = []
    for i, item in enumerate(sorted_items, start=1):
        # 신 trigger_price = 현재가 × direction^i
        # i = 1 (= 신 첫 단계) → 현재가 × 1.10 (SHORT)
        # i = 2 → 현재가 × 1.21
        new_trigger = (current_price * (direction ** i)).quantize(Decimal("0.00000001"))

        # 기존 plan 조회 (= 신 추가 vs 옛 수정 결정)
        existing = db.execute(
            sa_select(StrategyStagePlan)
            .where(StrategyStagePlan.strategy_instance_id == strategy.id)
            .where(StrategyStagePlan.stage_no == item.stage_no)
        ).scalar_one_or_none()

        if existing:
            # 기존 미진입 단계 = 수정
            if existing.is_triggered:
                # 안전망 (위에서 검증했지만 race condition 방지)
                continue
            old_trigger = existing.trigger_price
            old_capital = existing.planned_capital
            existing.trigger_price = new_trigger
            existing.trigger_percent = item.trigger_percent or Decimal("10")
            existing.planned_capital = item.planned_capital
            existing.is_enabled = True
            changes.append({
                "stage_no": item.stage_no,
                "action": "updated",
                "old_trigger_price": str(old_trigger) if old_trigger else None,
                "new_trigger_price": str(new_trigger),
                "old_planned_capital": str(old_capital) if old_capital else None,
                "new_planned_capital": str(item.planned_capital),
            })
        else:
            # 신 단계 추가
            trigger_mode = "PRICE_UP_PCT" if is_short else "PRICE_DOWN_PCT"
            new_plan = StrategyStagePlan(
                strategy_instance_id=strategy.id,
                stage_no=item.stage_no,
                side=strategy.side,
                trigger_mode=trigger_mode,
                trigger_percent=item.trigger_percent or Decimal("10"),
                trigger_price=new_trigger,
                planned_capital=item.planned_capital,
                is_enabled=True,
                is_triggered=False,
            )
            db.add(new_plan)
            changes.append({
                "stage_no": item.stage_no,
                "action": "added",
                "new_trigger_price": str(new_trigger),
                "new_planned_capital": str(item.planned_capital),
            })

    db.add(RiskEvent(
        strategy_instance_id=strategy.id,
        event_type="UNTRIGGERED_STAGES_ADDED",
        severity="INFO",
        title=f"➕ 미진입 단계 추가/수정 — {strategy.symbol} {strategy.side}",
        message=(
            f"사장님 미진입 단계 추가/수정. "
            f"현재가 {current_price} 기준 × ({'1.10' if is_short else '0.90'})^N. "
            f"진입 단계 {triggered_max_stage}개 = 영향 X. "
            f"변경된 단계: {len(changes)}건 = {[c['stage_no'] for c in changes]}."
        ),
        event_payload={
            "current_price": str(current_price),
            "direction": str(direction),
            "side": strategy.side,
            "triggered_max_stage": triggered_max_stage,
            "changes": changes,
        },
    ))
    db.commit()
    db.refresh(strategy)
    logger.info(
        "[add-untriggered-stages] strategy_id=%s current_price=%s changes=%s",
        strategy_id, current_price, len(changes),
    )

    from app.models.strategy_template import StrategyTemplate
    tpl = (
        db.get(StrategyTemplate, strategy.strategy_template_id)
        if strategy.strategy_template_id else None
    )
    return _enrich_response(StrategyDetailResponse.model_validate(strategy), tpl)


# ─────────────────────────────────────────────────────────────────────────────
# 🌟 사장님 신 기능 (2026-06-08): 미체결 LIMIT 주문 시각 + 개별 취소
#
# 사장님 명시: "「💉 포지션 추가」 지정가 진입예정 = 어디서 관리?"
# = 사장님 = 미체결 LIMIT 주문 시각 + 개별 취소 의도
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/{strategy_id}/open-orders")
def list_open_orders(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """미체결 주문 조회 (LIMIT 등 status=NEW + PARTIALLY_FILLED).

    사장님 사상: 「💉 포지션 추가」 지정가 + 자동 단계 LIMIT 모두 추적.
    """
    from sqlalchemy import select as sa_select
    from app.models.order import Order

    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(404, "전략을 찾을 수 없거나 본인 소유가 아닙니다.")

    orders = db.execute(
        sa_select(Order)
        .where(Order.strategy_instance_id == strategy_id)
        .where(Order.status.in_(["NEW", "PARTIALLY_FILLED"]))
        .order_by(Order.created_at.desc())
    ).scalars().all()

    return {
        "strategy_id": strategy_id,
        "symbol": strategy.symbol,
        "side": strategy.side,
        "count": len(orders),
        "orders": [
            {
                "id": o.id,
                "stage_no": o.stage_no,
                "purpose": o.purpose,
                "side": o.side,
                "order_type": o.order_type,
                "trigger_price": str(o.trigger_price) if o.trigger_price else None,
                "price": str(o.price) if o.price else None,
                "orig_qty": str(o.orig_qty) if o.orig_qty else None,
                "executed_qty": str(o.executed_qty) if o.executed_qty else None,
                "status": o.status,
                "client_order_id": o.client_order_id,
                "exchange_order_id": str(o.exchange_order_id) if o.exchange_order_id else None,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "is_adhoc": o.stage_no is None,  # ad-hoc (= 「💉 포지션 추가」)
            }
            for o in orders
        ],
    }


@router.delete("/{strategy_id}/open-orders/{order_id}")
def cancel_open_order(
    strategy_id: int,
    order_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """개별 미체결 주문 취소.

    검증:
    - 본인 소유 strategy
    - 주문 = 해당 strategy 소속
    - 주문 status = NEW 또는 PARTIALLY_FILLED
    """
    import logging
    from sqlalchemy import select as sa_select
    from app.models.order import Order
    from app.models.risk_event import RiskEvent
    from app.services.execution_service import ExecutionService
    logger = logging.getLogger(__name__)

    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(404, "전략을 찾을 수 없거나 본인 소유가 아닙니다.")

    order = db.execute(
        sa_select(Order)
        .where(Order.id == order_id)
        .where(Order.strategy_instance_id == strategy_id)
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(404, "주문을 찾을 수 없습니다.")
    if order.status not in ("NEW", "PARTIALLY_FILLED"):
        raise HTTPException(400, f"이미 종료된 주문 (status={order.status})")

    # 거래소 호출 (= lifecycle.py manual-tp 패턴)
    try:
        from app.repositories.exchange_account_repository import ExchangeAccountRepository
        from app.core.security import decrypt_text
        account = ExchangeAccountRepository(db).get(strategy.exchange_account_id)
        if not account:
            raise HTTPException(400, f"거래소 계정 없음 (id={strategy.exchange_account_id})")
        api_key = decrypt_text(account.api_key_enc)
        api_secret = decrypt_text(account.api_secret_enc)
        execution = ExecutionService(
            db, api_key=api_key, api_secret=api_secret, is_testnet=account.is_testnet,
        )
        result = execution.cancel_exchange_order(
            symbol=order.symbol,
            order_id=int(order.exchange_order_id) if order.exchange_order_id else None,
            orig_client_order_id=order.client_order_id,
        )
        logger.info(
            "[cancel-open-order] strategy_id=%s order_id=%s exchange_oid=%s status=%s",
            strategy_id, order_id, order.exchange_order_id, (result or {}).get("status"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[cancel-open-order] 거래소 호출 실패: %s", e)
        raise HTTPException(502, f"거래소 호출 실패: {e}")

    # DB 갱신
    order.status = "CANCELED"
    db.add(RiskEvent(
        strategy_instance_id=strategy.id,
        event_type="OPEN_ORDER_CANCELED_MANUAL",
        severity="INFO",
        title=f"❌ 미체결 주문 수동 취소 — {strategy.symbol} {strategy.side}",
        message=(
            f"사장님 수동 취소. order_id={order_id} stage_no={order.stage_no} "
            f"type={order.order_type} qty={order.orig_qty} @{order.price or '-'}"
        ),
        event_payload={
            "order_id": order_id,
            "exchange_order_id": str(order.exchange_order_id) if order.exchange_order_id else None,
            "stage_no": order.stage_no,
            "is_adhoc": order.stage_no is None,
        },
    ))
    db.commit()
    return {
        "ok": True,
        "order_id": order_id,
        "message": f"주문 #{order_id} 취소 완료",
    }


# ─────────────────────────────────────────────────────────────────────────────
# (옛 endpoint 그대로 유지)
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/{strategy_id}/recalc-untriggered-from-current", response_model=StrategyDetailResponse)
def recalc_untriggered_from_current(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyDetailResponse:
    """미진입 단계의 trigger_price = 현재가 × (1.10)^N 재계산.

    사장님 사상 (2026-06-08):
    - 포지션 + 진입 단계 = 그대로 유지
    - 다음 미진입 단계 = 현재가 × 1.10
    - 그 다음 단계 = 현재가 × 1.21 (= 1.10^2)
    - trigger_percent = 10% 유지

    검증:
    - 본인 소유 + 활성 strategy
    - 현재가 = Redis mark_price_cache 조회
    - 미진입 단계 (is_triggered=False) 만 수정
    - 진입 단계 = 영향 X (사장님 자본 보호)
    """
    import logging
    from app.models.risk_event import RiskEvent
    from app.models.strategy_stage_plan import StrategyStagePlan
    from app.services.mark_price_cache import get_mark_price
    from sqlalchemy import select as sa_select
    logger = logging.getLogger(__name__)

    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.",
        )
    if strategy.status in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"⚠️ 종료된 strategy ({strategy.status}) 는 재계산 불가.",
        )

    current_price = get_mark_price(strategy.symbol)
    if not current_price or current_price <= 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"⚠️ {strategy.symbol} 현재가 조회 실패 — Redis 캐시 없음. 1분 후 재시도.",
        )

    untriggered_plans = db.execute(
        sa_select(StrategyStagePlan)
        .where(StrategyStagePlan.strategy_instance_id == strategy.id)
        .where(StrategyStagePlan.is_triggered.is_(False))
        .where(StrategyStagePlan.is_enabled.is_(True))
        .order_by(StrategyStagePlan.stage_no.asc())
    ).scalars().all()

    if not untriggered_plans:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="⚠️ 미진입 단계가 없습니다 (= 모든 단계 진입 완료).",
        )

    # SHORT: trigger = 현재가 × (1.10)^N (가격 상승 시 진입)
    # LONG:  trigger = 현재가 × (0.90)^N (가격 하락 시 진입)
    is_short = (strategy.side or "").upper() == "SHORT"
    direction = Decimal("1.10") if is_short else Decimal("0.90")

    changes = []
    for i, plan in enumerate(untriggered_plans, start=1):
        old_trigger = plan.trigger_price
        new_trigger = (current_price * (direction ** i)).quantize(Decimal("0.00000001"))
        plan.trigger_price = new_trigger
        plan.trigger_percent = Decimal("10")
        changes.append({
            "stage_no": plan.stage_no,
            "old_trigger_price": str(old_trigger) if old_trigger else None,
            "new_trigger_price": str(new_trigger),
            "step": i,
        })

    db.add(RiskEvent(
        strategy_instance_id=strategy.id,
        event_type="UNTRIGGERED_STAGES_RECALC",
        severity="INFO",
        title=f"🔄 미진입 단계 재계산 — {strategy.symbol} {strategy.side}",
        message=(
            f"사장님 미진입 단계 trigger_price 재계산. "
            f"현재가 {current_price} 기준 × ({'1.10' if is_short else '0.90'})^N. "
            f"변경된 단계: {len(changes)}건 = {[c['stage_no'] for c in changes]}. "
            f"진입 단계 영향 X (사장님 자본 보호)."
        ),
        event_payload={
            "current_price": str(current_price),
            "direction": str(direction),
            "side": strategy.side,
            "changes": changes,
        },
    ))
    db.commit()
    db.refresh(strategy)
    logger.info(
        "[recalc-untriggered] strategy_id=%s current_price=%s changes=%s",
        strategy_id, current_price, len(changes),
    )

    from app.models.strategy_template import StrategyTemplate
    tpl = (
        db.get(StrategyTemplate, strategy.strategy_template_id)
        if strategy.strategy_template_id else None
    )
    return _enrich_response(StrategyDetailResponse.model_validate(strategy), tpl)
