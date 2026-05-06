"""Position reconcile worker.

매 사이클 실행 단계:
  0) Phase 1 자동 회복:
     - pre_pass_dedup           — 동일 (acc, sym, side) 중복 active 정리
     - enforce_terminal_qty_zero — STOPPED/COMPLETED 등 종료 상태 qty 잔재 정리
  1) main loop — active strategy 들에 대해 거래소 포지션 sync + status 자동 회복
     - matched=None + STOPPING  → STOPPED (좀비 정리)
     - matched=None + *_OPEN    → STOPPED (외부 청산 orphan)
     - matched=None + PENDING   → 카운터 증가 (5 사이클 stuck 시 escalate)
     - matched ≠ None           → qty/price sync, *_PENDING → *_OPEN 전이
  2) Phase 2 안전망:
     - detect_orphan_exchange_positions — 거래소 포지션 ≠ DB matching → CRITICAL + Kill-Switch
"""
from datetime import datetime, timezone
from decimal import Decimal
import logging
from sqlalchemy import select
from app.core.database import SessionLocal
from app.core.redis_client import get_redis_client
from app.core.redis_lock import redis_lock, RedisLockError
from app.core.sentry import capture_strategy_event
from app.integrations.binance.client import BinanceClient
from app.models.exchange_account import ExchangeAccount
from app.models.position import Position
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from app.observability.metrics import position_reconcile_total, position_qty_mismatch_total
from app.services.zombie_guardian import (
    pre_pass_dedup,
    enforce_terminal_qty_zero,
    detect_orphan_exchange_positions,
    escalate_stuck_strategy,
    _stuck_inc,
    _stuck_clear,
    STUCK_THRESHOLD,
)

logger = logging.getLogger(__name__)

# A07 fix (audit 2026-05-02): 다중 instance / re-entrant 호출 방지.
RECONCILE_LOCK_KEY = "lock:reconcile_worker"
RECONCILE_LOCK_TTL = 60  # 한 사이클 최대 60초 (정상 30초 cycle 의 2배 헤드룸)


def run_position_reconcile_once(decrypt_func) -> None:
    try:
        redis_client = get_redis_client()
    except Exception:
        return _do_reconcile(decrypt_func)
    try:
        with redis_lock(redis_client, RECONCILE_LOCK_KEY, ttl_seconds=RECONCILE_LOCK_TTL, wait_timeout_seconds=0):
            _do_reconcile(decrypt_func)
    except RedisLockError:
        logger.debug("reconcile_worker skip — another instance holds lock")


def _do_reconcile(decrypt_func) -> None:
    db = SessionLocal()
    try:
        # ===== Phase 1 (자동 회복) =====
        # (a) 중복 active 좀비 강등
        try:
            n_demoted = pre_pass_dedup(db)
            db.commit()
            if n_demoted:
                logger.info("Zombie Guardian pre_pass_dedup: %d demoted", n_demoted)
        except Exception as e:
            logger.error("pre_pass_dedup 실패: %s", e)
            db.rollback()
            # Phase 1 자동회복 실패는 좀비 정리가 한 사이클 누락된다는 의미.
            # 30초 뒤 다음 사이클에 재시도되지만 운영자 가시성 위해 Sentry 캡처.
            capture_strategy_event(
                "Zombie Guardian pre_pass_dedup failed",
                level="error", error=e,
                tags={"event_type": "PRE_PASS_DEDUP_FAILED"},
            )

        # (b) 종료 상태 qty 잔재 정리
        try:
            n_fixed = enforce_terminal_qty_zero(db)
            db.commit()
            if n_fixed:
                logger.info("Zombie Guardian enforce_terminal_qty_zero: %d fixed", n_fixed)
        except Exception as e:
            logger.error("enforce_terminal_qty_zero 실패: %s", e)
            db.rollback()
            capture_strategy_event(
                "Zombie Guardian enforce_terminal_qty_zero failed",
                level="error", error=e,
                tags={"event_type": "ENFORCE_TERMINAL_QTY_ZERO_FAILED"},
            )

        # ===== Main loop — active strategy 별 거래소 sync + 자동 회복 =====
        # 활성 전략 조회. *_PENDING 상태도 포함 — user-stream 이 죽어 체결 이벤트를
        # 놓친 경우 reconcile 이 거래소 상태를 보고 PENDING -> OPEN 으로 자가 회복.
        # 2026-05-04 fix: 옵션 C 1~10단계 동적 — 이전엔 STAGE1~4_OPEN_PENDING/OPEN 만 active 분류라
        # 5+ stage 진입한 strategy 가 reconcile main loop 에서 누락되는 버그.
        _ACTIVE_PENDING = [f"STAGE{n}_OPEN_PENDING" for n in range(1, 11)]
        _ACTIVE_OPEN = [f"STAGE{n}_OPEN" for n in range(1, 11)]
        _ACTIVE_TP_PARTIAL = [f"TP{n}_DONE_PARTIAL" for n in range(1, 6)]
        rows = db.execute(
            select(StrategyInstance, ExchangeAccount)
            .join(ExchangeAccount, StrategyInstance.exchange_account_id == ExchangeAccount.id)
            .where(StrategyInstance.status.in_(
                _ACTIVE_PENDING + _ACTIVE_OPEN + _ACTIVE_TP_PARTIAL + ["STOPPING"]
            ))
            .where(StrategyInstance.is_archived.is_(False))  # 2026-05-06 C-full: archived 제외
            .where(ExchangeAccount.is_active.is_(True))
        ).all()
        for strategy, account in rows:
            try:
                client = BinanceClient(
                    api_key=decrypt_func(account.api_key_enc),
                    api_secret=decrypt_func(account.api_secret_enc),
                    is_testnet=account.is_testnet,
                )
                position_risk = client.get_position_risk(symbol=strategy.symbol)
                if isinstance(position_risk, dict):
                    position_risk = [position_risk]
                matched = None
                for item in position_risk:
                    if item.get("symbol") == strategy.symbol and item.get("positionSide") == strategy.side:
                        matched = item
                        break

                # ----- matched=None: 거래소엔 포지션 없음 -----
                if not matched:
                    # STOPPING 좀비 자동 정리
                    if strategy.status == "STOPPING":
                        db.add(RiskEvent(
                            strategy_instance_id=strategy.id,
                            event_type="RECONCILE_STOPPING_ZOMBIE_CLEANUP",
                            severity="INFO",
                            title="✅ 좀비 STOPPING 자동 정리 (STOPPED 전환)",
                            message=f"{strategy.symbol} {strategy.side} — 거래소 포지션 0 확인됨, STOPPING → STOPPED 자동 승격",
                            event_payload={"strategy_id": strategy.id},
                        ))
                        strategy.status = "STOPPED"
                        strategy.current_position_qty = Decimal("0")
                        strategy.stopped_at = datetime.now(timezone.utc)
                        position_reconcile_total.labels(status="zombie_stopped").inc()
                        _stuck_clear(strategy.id)
                        continue
                    # *_OPEN orphan 자동 정리 — 1~10단계 + TP 1~5 PARTIAL.
                    _OPEN_STATES = (
                        {f"STAGE{n}_OPEN" for n in range(1, 11)}
                        | {f"TP{n}_DONE_PARTIAL" for n in range(1, 6)}
                    )
                    if strategy.status in _OPEN_STATES:
                        db.add(RiskEvent(
                            strategy_instance_id=strategy.id,
                            event_type="RECONCILE_AUTO_STOP_ORPHAN",
                            severity="WARN",
                            title="🧹 외부 청산된 전략 자동 정리 (STOPPED)",
                            message=f"{strategy.symbol} {strategy.side} — 거래소에서 외부 청산되어 시스템에만 잔재. STOPPED 마킹",
                            event_payload={"strategy_id": strategy.id, "old_status": strategy.status},
                        ))
                        strategy.status = "STOPPED"
                        strategy.current_position_qty = Decimal("0")
                        strategy.stopped_at = datetime.now(timezone.utc)
                        position_reconcile_total.labels(status="orphan_stopped").inc()
                        _stuck_clear(strategy.id)
                    else:
                        # PENDING 등 — limit 미체결일 가능성. 카운터 증가, 임계 초과 시 escalate.
                        n_stuck = _stuck_inc(strategy.id)
                        db.add(RiskEvent(
                            strategy_instance_id=strategy.id,
                            event_type="POSITION_RECONCILE_MISS",
                            severity="WARN",
                            title=f"⚠️ 거래소에 매칭 포지션 없음 (stuck {n_stuck}/{STUCK_THRESHOLD})",
                            message=(
                                f"{strategy.symbol} {strategy.side} ({strategy.status}) — "
                                f"DB 는 active 인데 거래소엔 포지션 없음. "
                                f"연속 미스 {n_stuck}회. {STUCK_THRESHOLD}회 초과 시 강제종료 + Kill-Switch."
                            ),
                            event_payload={"strategy_id": strategy.id, "stuck_count": n_stuck},
                        ))
                        position_reconcile_total.labels(status="miss").inc()
                        if n_stuck >= STUCK_THRESHOLD:
                            escalate_stuck_strategy(
                                db,
                                strategy,
                                reason_code="PENDING_STUCK_NO_EXCHANGE_POSITION",
                                reason_detail=(
                                    f"{n_stuck} cycles 연속 거래소 매칭 없음. "
                                    "LIMIT 주문 미체결 + 거래소 거절 가능성. 신규 주문 차단 후 운영자 확인 필요."
                                ),
                                exchange_snapshot=None,
                            )
                    continue

                # ----- matched 존재: 거래소 포지션 sync -----
                exchange_position_amt = Decimal(str(matched.get("positionAmt", "0")))
                exchange_entry_price = Decimal(str(matched.get("entryPrice", "0")))
                exchange_mark_price = Decimal(str(matched.get("markPrice", "0")))
                exchange_unrealized_pnl = Decimal(str(matched.get("unRealizedProfit", "0")))
                exchange_liquidation_price = Decimal(str(matched.get("liquidationPrice", "0")))
                db.add(Position(
                    strategy_instance_id=strategy.id,
                    symbol=strategy.symbol, side=strategy.side, position_side=strategy.side,
                    entry_price=exchange_entry_price if exchange_entry_price > 0 else None,
                    break_even_price=Decimal(str(matched.get("breakEvenPrice", "0"))) or None,
                    mark_price=exchange_mark_price if exchange_mark_price > 0 else None,
                    liquidation_price=exchange_liquidation_price if exchange_liquidation_price > 0 else None,
                    position_amt=exchange_position_amt,
                    isolated_margin=Decimal(str(matched.get("isolatedMargin", "0"))),
                    unrealized_pnl=exchange_unrealized_pnl,
                    margin_type=matched.get("marginType"),
                    leverage=int(matched.get("leverage", strategy.leverage)) if matched.get("leverage") else strategy.leverage,
                    source="POSITION_RISK_SYNC",
                ))
                local_qty = Decimal(str(strategy.current_position_qty or 0))
                if local_qty != exchange_position_amt:
                    n_stuck = _stuck_inc(strategy.id)
                    db.add(RiskEvent(
                        strategy_instance_id=strategy.id,
                        event_type="POSITION_QTY_MISMATCH",
                        severity="WARN",
                        title=f"⚠️ 포지션 수량 불일치 (DB ↔ 거래소) (stuck {n_stuck}/{STUCK_THRESHOLD})",
                        message=(
                            f"시스템 기록 {local_qty} vs 거래소 실 포지션 {exchange_position_amt} — "
                            f"reconcile 이 자동 동기화함. 연속 mismatch {n_stuck}회."
                        ),
                        event_payload={
                            "local_qty": str(local_qty),
                            "exchange_qty": str(exchange_position_amt),
                            "stuck_count": n_stuck,
                        },
                    ))
                    position_qty_mismatch_total.labels(symbol=strategy.symbol, side=strategy.side).inc()
                    # 자동 sync 로 정합성은 회복되지만, 같은 strategy 가 매 사이클 계속 mismatch 면
                    # 시스템 외부에서 포지션이 변경되고 있다는 신호. 임계 초과 시 escalate.
                    if n_stuck >= STUCK_THRESHOLD:
                        escalate_stuck_strategy(
                            db,
                            strategy,
                            reason_code="QTY_MISMATCH_PERSISTENT",
                            reason_detail=(
                                f"{n_stuck} cycles 연속 qty 불일치 — DB sync 후에도 외부 변경 지속. "
                                "stream 누락/외부 거래/거래소 장애 의심. Kill-Switch 발동."
                            ),
                            exchange_snapshot=matched,
                        )
                        continue
                else:
                    _stuck_clear(strategy.id)
                strategy.avg_entry_price = exchange_entry_price if exchange_entry_price > 0 else strategy.avg_entry_price
                strategy.current_position_qty = exchange_position_amt
                strategy.unrealized_pnl = exchange_unrealized_pnl
                strategy.liquidation_price = exchange_liquidation_price if exchange_liquidation_price > 0 else strategy.liquidation_price
                # 자가 회복: *_OPEN_PENDING + 거래소에 실 포지션 → *_OPEN 전이.
                # 2026-05-04 fix v2 (사용자 #96 TSTUSDT 사례):
                # 이전 버그 — 단순히 "exchange_position != 0" 만 보고 promote → 다단계 strategy 의
                # stage N (N>=2) LIMIT 가 미체결인데도 reconcile 이 status 를 STAGE_N_OPEN 으로
                # 잘못 승격. 거래소 포지션은 stage 1~(N-1) 합 (= 이전 fills) 이라 != 0 인 게 당연.
                # 해당 stage 의 LIMIT 가 실제로 fill 됐는지 확인하려면 stage_plan.is_triggered 검사.
                # is_triggered 는 stream_service 가 ENTRY FILLED 처리 시 atomic UPDATE 함.
                _PENDING_TO_OPEN = {
                    f"STAGE{n}_OPEN_PENDING": (f"STAGE{n}_OPEN", n) for n in range(1, 11)
                }
                if strategy.status in _PENDING_TO_OPEN and exchange_position_amt != 0:
                    new_status, pending_stage_no = _PENDING_TO_OPEN[strategy.status]
                    # 그 stage 의 plan 이 실제 fill 됐는지 확인 (stream 누락 회복용 가드).
                    from app.models.strategy_stage_plan import StrategyStagePlan
                    plan = db.execute(
                        select(StrategyStagePlan)
                        .where(StrategyStagePlan.strategy_instance_id == strategy.id)
                        .where(StrategyStagePlan.stage_no == pending_stage_no)
                    ).scalar_one_or_none()
                    if plan is not None and plan.is_triggered:
                        db.add(RiskEvent(
                            strategy_instance_id=strategy.id,
                            event_type="RECONCILE_RECOVERED_PENDING",
                            severity="WARN",
                            title="Reconciled stuck PENDING -> OPEN",
                            message=f"status {strategy.status} -> {new_status} (stage_plan triggered, position={exchange_position_amt})",
                            event_payload={
                                "strategy_id": strategy.id,
                                "old_status": strategy.status,
                                "new_status": new_status,
                                "position_amt": str(exchange_position_amt),
                            },
                        ))
                        strategy.status = new_status
                    # else: stage_plan 미발동 — LIMIT 가 아직 거래소 book 에 대기 중. 그대로 PENDING 유지.
                position_reconcile_total.labels(status="success").inc()
            except Exception as e:
                db.add(RiskEvent(
                    strategy_instance_id=strategy.id,
                    event_type="POSITION_RECONCILE_ERROR",
                    severity="ERROR",
                    title="Position reconcile failed",
                    message=str(e),
                    event_payload={"strategy_id": strategy.id},
                ))
                position_reconcile_total.labels(status="error").inc()
                # Sentry: per-strategy reconcile 실패 — 거래소 API 일시 장애 또는
                # 권한 문제일 수 있음. strategy_id 태그로 빈도 추적.
                capture_strategy_event(
                    "Position reconcile failed for strategy",
                    level="error", error=e,
                    strategy_id=strategy.id, symbol=strategy.symbol, side=strategy.side,
                    account_id=strategy.exchange_account_id,
                    tags={"event_type": "POSITION_RECONCILE_ERROR"},
                )
        db.commit()

        # ===== Phase 2 안전망 — 거래소 orphan 포지션 감지 =====
        try:
            n_orphan = detect_orphan_exchange_positions(db, decrypt_func=decrypt_func)
            db.commit()
            if n_orphan:
                logger.critical(
                    "Zombie Guardian: %d orphan exchange position(s) detected", n_orphan
                )
        except Exception as e:
            logger.error("detect_orphan_exchange_positions 실패: %s", e)
            db.rollback()
            # Sentry: orphan detection 자체 실패 — Phase 2 안전망이 한 사이클 작동 안 함.
            capture_strategy_event(
                "detect_orphan_exchange_positions failed",
                level="error", error=e,
                tags={"event_type": "ORPHAN_DETECTION_LOOP_FAILED"},
            )
    finally:
        db.close()
