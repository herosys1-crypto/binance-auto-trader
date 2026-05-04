"""Stage 2~N 자동 진입 트리거 감시 worker.

이전엔 stage 1 LIMIT 주문만 거래소에 발송됐고, stage 2~N 은 자동 트리거 worker
가 없어서 가격이 트리거를 통과해도 진입이 안 되는 critical bug 가 있었음.
이 worker 가 그 missing piece — 활성 전략의 다음 stage 트리거를 매 10초마다 체크.

동작:
- 상태가 STAGE{1~9}_OPEN 인 전략 조회
- 각 전략의 다음 stage_no 계산 (current_stage + 1)
- 그 stage_plan 의 trigger_price 와 현재 mark_price 비교
- SHORT: mark >= trigger 시 진입 / LONG: mark <= trigger 시 진입
- ExecutionService.trigger_next_stage() 호출 → 거래소에 LIMIT 주문 발송

LIMIT 주문은 즉시 fill 될 수도, book 에 대기할 수도 있음. fill 시 stream_service
가 stage_plan.is_triggered = True 로 갱신.
"""
from __future__ import annotations
import logging
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.repositories.position_repository import PositionRepository
from app.services.execution_service import ExecutionService
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

# 다음 stage 진입 검사 대상 상태 (stage 1~9 가 OPEN 이면 그 다음 stage 진입 검사 — 10 은 마지막).
# 2026-05-04: 옵션 C 1~10단계 동적 — comprehension 으로 통일.
ACTIVE_STAGE_STATUSES = {f"STAGE{n}_OPEN" for n in range(1, 10)}


def _count_total_stages_from_template(tpl) -> int:
    """Template 의 stages_config 에서 총 활성 단계 수 산출 (1~10 동적).

    A08 fix (audit 2026-05-02): 이전엔 _get_total_stages 가 매번 새 SessionLocal
    + db.get 호출 → N+1 쿼리 (활성 전략 N개 × 새 세션). 이제 호출자가 미리 batch
    fetch 한 tpl 객체를 전달하면 세션 추가 호출 없음.
    """
    if not tpl:
        return 4
    cfg = tpl.stages_config or {}
    capitals = cfg.get("capitals") or []
    return len(capitals) if capitals else 4


def run_stage_trigger_once(decrypt_text) -> None:
    """활성 전략의 다음 stage 트리거 검사 + 자동 LIMIT 주문 발송.

    매 10초마다 scheduler 가 호출. Redis lock 은 scheduler 가 처리.
    """
    db = SessionLocal()
    try:
        from app.models.strategy_template import StrategyTemplate
        rows = db.execute(
            select(StrategyInstance, ExchangeAccount)
            .join(ExchangeAccount, StrategyInstance.exchange_account_id == ExchangeAccount.id)
            .where(StrategyInstance.status.in_(ACTIVE_STAGE_STATUSES))
            .where(ExchangeAccount.is_active.is_(True))
        ).all()
        # A08 fix: N+1 방지 — 모든 strategy 의 template 을 한 번에 batch fetch.
        # 이전엔 strategy 마다 SessionLocal() + db.get() 호출 → 활성 N개일 때 N개 세션.
        template_ids = {s.strategy_template_id for s, _ in rows if s.strategy_template_id}
        templates = (
            {t.id: t for t in db.query(StrategyTemplate).filter(StrategyTemplate.id.in_(template_ids)).all()}
            if template_ids else {}
        )
        for strategy, account in rows:
            try:
                next_stage_no = (strategy.current_stage or 0) + 1
                total_stages = _count_total_stages_from_template(templates.get(strategy.strategy_template_id))
                if next_stage_no > total_stages:
                    continue  # 모든 단계 진입 완료
                # Stage plans 조회 (lazy load 회피 위해 새 쿼리)
                from app.models.strategy_stage_plan import StrategyStagePlan
                next_plan = db.execute(
                    select(StrategyStagePlan)
                    .where(StrategyStagePlan.strategy_instance_id == strategy.id)
                    .where(StrategyStagePlan.stage_no == next_stage_no)
                ).scalar_one_or_none()
                if not next_plan:
                    continue
                if next_plan.is_triggered:
                    continue  # 이미 진입됨
                if not next_plan.trigger_price:
                    # LIQUIDATION_BUFFER 모드 (마지막 단계) — trigger_price 가 None.
                    # 실시간으로 청산가 -5% 기반 산출 필요. 일단 skip (후속 작업으로 분리).
                    continue
                # 현재 mark price 조회 (last position snapshot)
                latest_pos = PositionRepository(db).latest_by_strategy(strategy.id)
                if not latest_pos or not latest_pos.mark_price:
                    continue
                mark = Decimal(str(latest_pos.mark_price))
                trigger = Decimal(str(next_plan.trigger_price))
                # SHORT: 가격 위로 더 갔으면 추가 SHORT 진입 (mark >= trigger)
                # LONG: 가격 아래로 더 갔으면 추가 LONG 진입 (mark <= trigger)
                should_fire = (mark >= trigger) if strategy.side == "SHORT" else (mark <= trigger)
                if not should_fire:
                    continue
                # LIMIT 주문 발송
                exec_service = ExecutionService(
                    db,
                    api_key=decrypt_text(account.api_key_enc),
                    api_secret=decrypt_text(account.api_secret_enc),
                    is_testnet=account.is_testnet,
                )
                logger.info(
                    f"[stage-trigger] firing stage{next_stage_no} for #{strategy.id} "
                    f"{strategy.symbol} {strategy.side} (mark={mark} {'>=' if strategy.side == 'SHORT' else '<='} trig={trigger})"
                )
                exec_service.trigger_next_stage(strategy.id, next_stage_no)
            except Exception as e:
                logger.exception(f"[stage-trigger] failed for strategy #{strategy.id}: {e}")
                try:
                    NotificationService(db).send_system_alert(
                        title="[시스템 오류] Stage 자동 진입 실패",
                        body=f"strategy_id={strategy.id} stage={next_stage_no if 'next_stage_no' in dir() else '?'} error={e}",
                    )
                except Exception:
                    pass
    finally:
        db.close()
