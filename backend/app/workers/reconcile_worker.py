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
from app.core.strategy_status import (
    ACTIVE_WAITING,
    ACTIVE_WITH_POSITION,
    MANUAL_CLEANUP_REQUIRED,
    OPEN_LIKE_FOR_ORPHAN_CHECK,
    PENDING_TO_OPEN_MAP,
)
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
    detect_orphan_exchange_open_orders,
    detect_orphan_db_orders,
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
        # 2026-05-14 Phase 1 centralize: ACTIVE_WAITING + ACTIVE_WITH_POSITION 사용.
        # ACTIVE_WITH_POSITION 이 STOPPING + STAGE_n_OPEN + TP_n_DONE_PARTIAL 모두 포함.
        # 이전 inline build 시 5-06 TP10 확장에서 TP6~10 누락 버그 발생 → centralize 로 영구 차단.
        _RECONCILE_TARGET_STATUSES = list(ACTIVE_WAITING | ACTIVE_WITH_POSITION)
        rows = db.execute(
            select(StrategyInstance, ExchangeAccount)
            .join(ExchangeAccount, StrategyInstance.exchange_account_id == ExchangeAccount.id)
            .where(StrategyInstance.status.in_(_RECONCILE_TARGET_STATUSES))
            .where(StrategyInstance.is_archived.is_(False))  # 2026-05-06 C-full: archived 제외
            .where(ExchangeAccount.is_active.is_(True))
        ).all()

        # 2026-05-09 (#120 사후 — rate limit 178건 발견): 같은 account 의 모든 strategy
        # 가 각자 client.get_position_risk(symbol=...) 호출하던 것을 account 별 1회 bulk
        # 호출로 변경. 5 strategy → 5 호출 이 1 호출로 줄어 rate limit 부담 ~80% 감소.
        # 추가로 account 별 BinanceClient 도 1번만 만들어서 재활용.
        # bulk 호출 결과는 Phase 2 orphan detection 도 재사용 (총 절감 효과 ↑↑).
        # 2026-05-09 Layer 4: API ban 감지 시 자동 backoff — 다음 cycle 들 skip.
        bulk_positions_cache: dict[int, list[dict]] = {}  # acc_id → positions
        bulk_client_cache: dict[int, BinanceClient] = {}  # acc_id → client
        bulk_failure_accs: set[int] = set()  # 호출 실패한 계정 (개별 strategy 도 skip)

        # Backoff: ban 중인 계정 미리 감지 → bulk 호출 자체 skip
        from app.core.api_backoff import (
            check_api_ban, parse_rate_limit_error, record_api_ban,
        )
        from app.services.notification_service import NotificationService
        try:
            from app.core.redis_client import get_redis_client as _get_rc
            _redis = _get_rc()
        except Exception:
            _redis = None
        notif_svc = NotificationService(db)

        def _get_bulk_for_account(acc: ExchangeAccount) -> list[dict] | None:
            if acc.id in bulk_positions_cache:
                return bulk_positions_cache[acc.id]
            if acc.id in bulk_failure_accs:
                return None
            # Backoff 사전 점검 — ban 중이면 거래소 호출 시도조차 안 함
            is_banned, expiry_ms = check_api_ban(_redis, acc.id)
            if is_banned:
                logger.info("API ban active for account=%s — skip cycle", acc.id)
                bulk_failure_accs.add(acc.id)
                return None
            try:
                cli = BinanceClient(
                    api_key=decrypt_func(acc.api_key_enc),
                    api_secret=decrypt_func(acc.api_secret_enc),
                    is_testnet=acc.is_testnet,
                )
                bulk_client_cache[acc.id] = cli
                pos = cli.get_position_risk()  # bulk — symbol 인자 없음
                if isinstance(pos, dict):
                    pos = [pos]
                bulk_positions_cache[acc.id] = pos
                return pos
            except Exception as e:
                # rate limit / ban 인지 검사
                ban_until = parse_rate_limit_error(e)
                if ban_until is not None:
                    record_api_ban(
                        _redis, acc.id, ban_until,
                        notification_service=notif_svc,
                        error_message=str(e),
                    )
                # bulk 실패 (rate limit 등) — 이번 cycle 의 main loop + orphan 모두 skip.
                logger.warning("Bulk get_position_risk failed acc=%s: %s — cycle skip", acc.id, e)
                bulk_failure_accs.add(acc.id)
                return None

        for strategy, account in rows:
            try:
                bulk_positions = _get_bulk_for_account(account)
                if bulk_positions is None:
                    # bulk 실패 — 이 strategy reconcile skip (rate limit 부담 줄임)
                    continue
                client = bulk_client_cache[account.id]
                matched = None
                for item in bulk_positions:
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
                    # *_OPEN orphan 자동 정리 — 1~10단계 + TP 1~10 PARTIAL.
                    # 2026-05-14 Phase 1 centralize: OPEN_LIKE_FOR_ORPHAN_CHECK 사용.
                    if strategy.status in OPEN_LIKE_FOR_ORPHAN_CHECK:
                        # 🌟 2026-06-18 사장님 critical: realized_pnl_sync_worker 가 매 1분 = Binance trades 동기화 = OK!
                        # 사장님 ESPORTSUSDT #182 = Binance +30.26 USDT (= But DB = +15.21 = silent bug 발견!)
                        # = 신 fix: STOPPED 마킹 시 = Telegram 사장님 안내 (= "Binance 실제 손익 확인!")
                        db.add(RiskEvent(
                            strategy_instance_id=strategy.id,
                            event_type="RECONCILE_AUTO_STOP_ORPHAN",
                            severity="WARN",
                            title="🧹 외부 청산된 전략 자동 정리 (STOPPED)",
                            message=(
                                f"{strategy.symbol} {strategy.side} — 거래소에서 외부 청산되어 시스템에만 잔재. STOPPED 마킹.\n"
                                f"⚠️ DB realized_pnl = {strategy.realized_pnl or 0} USDT (= 시스템 청산만 반영!)\n"
                                f"💡 사장님 Binance 앱 = ESPORTSUSDT Position History = 실제 손익 확인 필수!\n"
                                f"= 사장님 자율 청산 또는 = liquidation = realized_pnl_sync_worker 다음 cycle 자동 동기화!"
                            ),
                            event_payload={"strategy_id": strategy.id, "old_status": strategy.status, "db_realized_pnl": str(strategy.realized_pnl or 0)},
                        ))
                        strategy.status = "STOPPED"
                        strategy.current_position_qty = Decimal("0")
                        strategy.stopped_at = datetime.now(timezone.utc)
                        position_reconcile_total.labels(status="orphan_stopped").inc()
                        _stuck_clear(strategy.id)
                    else:
                        # 🚨 2026-06-25 사장님 critical fix (#232 SYNUSDT):
                        # 사장님 보고: "내가 0.43에 1단계 포지션 진입을 했어야 해!"
                        # = 사장님 의도: LIMIT 가격 도달 = 영구 대기!
                        # = 옛 silent bug: STAGE_PENDING (= LIMIT 미체결) + 5 cycle (2.5분) = 강제 종료!
                        # = 사장님 = #232 SYNUSDT 시작가 0.43 = LIMIT @ 0.43 발송!
                        # = 2.5분 후 = STOPPING + STOPPED = silent 종료!
                        # = 사장님 자율 운영 위반!
                        #
                        # fix: STAGE_n_OPEN_PENDING (= LIMIT 미체결!) = stuck counter 제외!
                        # = LIMIT 활성 시 = 영구 대기 (= 사장님 의도!)
                        # = 진짜 stuck (STAGE_n_OPEN + 거래소 X) 만 counter!
                        #
                        # 진짜 정리 필요 시 = 사장님 = 직접 「⛔ 종료」 버튼 클릭!
                        if strategy.status and strategy.status.endswith("_OPEN_PENDING"):
                            # LIMIT 활성 = 사장님 가격 대기 = stuck X = continue!
                            logger.info(
                                "[reconcile] #%s %s status=%s = LIMIT 가격 대기 = stuck 제외 (사장님 의도!)",
                                strategy.id, strategy.symbol, strategy.status,
                            )
                            continue
                        # 그 외 = stuck counter (= 정상 동작!)
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

                # ----- 2026-05-18: flat 거래소 레코드 (positionAmt=0) = 포지션 없음과 동일 -----
                # #53 BASUSDT 사례 (사용자 보고): 거래소가 BASUSDT 를 positionAmt=0 (flat)
                # 으로 반환하면 `matched` 가 truthy → 위 `not matched` orphan 정리 분기를
                # 안 탐 → status 가 TP_n_DONE_PARTIAL 에 갇힘 → emergency-close 무한루프 →
                # API 호출 spam → rate limit / 418 ban 악화. flat 레코드는 「포지션 없음」
                # 과 동일하게 취급해 orphan/STOPPING 자동정리 적용 (snapshot/sync 생략).
                if exchange_position_amt == 0 and (
                    strategy.status == "STOPPING"
                    or strategy.status in OPEN_LIKE_FOR_ORPHAN_CHECK
                ):
                    _is_stopping = strategy.status == "STOPPING"
                    db.add(RiskEvent(
                        strategy_instance_id=strategy.id,
                        event_type="RECONCILE_FLAT_POSITION_CLEANUP",
                        severity="INFO" if _is_stopping else "WARN",
                        title=(
                            "✅ 좀비 STOPPING 자동 정리 (flat 레코드 — STOPPED)"
                            if _is_stopping else
                            "🧹 외부 청산된 전략 자동 정리 (flat 레코드 — STOPPED)"
                        ),
                        message=(
                            f"{strategy.symbol} {strategy.side} — 거래소가 positionAmt=0 "
                            f"(flat) 반환. 포지션 없음과 동일 → STOPPED 마킹 "
                            f"(이전 status={strategy.status})."
                        ),
                        event_payload={"strategy_id": strategy.id, "old_status": strategy.status},
                    ))
                    strategy.status = "STOPPED"
                    strategy.current_position_qty = Decimal("0")
                    strategy.stopped_at = datetime.now(timezone.utc)
                    position_reconcile_total.labels(
                        status="zombie_stopped" if _is_stopping else "orphan_stopped"
                    ).inc()
                    _stuck_clear(strategy.id)
                    continue

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

                # 2026-06-05 자본 자동 동기화 (사장님 사상 PR #56 확장):
                # 사장님이 Binance UI 에서 직접 증거금/포지션 추가 → 우리 시스템 통과 X
                # → DB total_capital 미갱신 → SL 한도 옛 자본 기준 (사장님 노력 보호 안 됨).
                # 매 사이클 Binance 실 마진 vs DB total_capital 비교:
                # - 실 마진 > 자본 × 1.05 (5% 초과) = 사장님 추가 감지
                # - DB total_capital = max(현재, 실 마진) 으로 자동 갱신
                # - audit log + Telegram 알림 (사장님 인지)
                # 사장님 사상: total_capital = 마진 단위 (PR #57 SL 계산 기준)
                try:
                    iso_margin = Decimal(str(matched.get("isolatedMargin", "0")))
                    init_margin = Decimal(str(matched.get("positionInitialMargin", "0")))
                    binance_actual_margin = max(iso_margin, init_margin)
                    cur_total_capital = Decimal(str(strategy.total_capital or 0))
                    # 5% 초과 + 절대 차이 1 USDT 초과 = 의미 있는 차이 (소수점 노이즈 회피)
                    if (binance_actual_margin > cur_total_capital * Decimal("1.05")
                            and (binance_actual_margin - cur_total_capital) > Decimal("1")):
                        old_capital = cur_total_capital
                        new_capital = binance_actual_margin
                        strategy.total_capital = new_capital
                        delta = new_capital - old_capital
                        delta_pct = (delta / old_capital * 100) if old_capital > 0 else Decimal("0")
                        db.add(RiskEvent(
                            strategy_instance_id=strategy.id,
                            event_type="TOTAL_CAPITAL_AUTO_SYNC",
                            severity="INFO",
                            title=f"💰 자본 자동 동기화 ({strategy.symbol}): {old_capital:.2f} → {new_capital:.2f} USDT (+{delta:.2f})",
                            message=(
                                f"Binance 실 마진 {binance_actual_margin:.2f} USDT 가 DB total_capital "
                                f"{old_capital:.2f} 보다 큼 (사장님 외부 증거금/포지션 추가 감지). "
                                f"DB 자동 갱신 → SL 한도 자동 재계산 (사장님 노력 보호 PR #56 확장)."
                            ),
                            event_payload={
                                "old_capital": str(old_capital),
                                "new_capital": str(new_capital),
                                "delta": str(delta),
                                "delta_pct": f"{delta_pct:.2f}",
                                "binance_isolated_margin": str(iso_margin),
                                "binance_init_margin": str(init_margin),
                            },
                        ))
                        logger.info(
                            "[capital-sync] strategy=%d %s total_capital %.2f → %.2f USDT (+%.2f, +%.1f%%)",
                            strategy.id, strategy.symbol, float(old_capital), float(new_capital),
                            float(delta), float(delta_pct),
                        )
                except Exception as e:
                    # 자본 동기화 실패 = 다음 사이클 재시도 (reconcile 본 로직 영향 X)
                    logger.warning("[capital-sync] strategy=%d failed: %s", strategy.id, e)

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
                # 2026-05-14 Phase 1 centralize: PENDING_TO_OPEN_MAP 사용 (app.core.strategy_status).
                if strategy.status in PENDING_TO_OPEN_MAP and exchange_position_amt != 0:
                    new_status, pending_stage_no = PENDING_TO_OPEN_MAP[strategy.status]
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
        # 2026-05-09: bulk_positions_cache 전달 — main loop 가 이미 fetch 한 결과 재사용.
        try:
            n_orphan = detect_orphan_exchange_positions(
                db, decrypt_func=decrypt_func,
                positions_cache=bulk_positions_cache,
            )
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

        # ===== Phase 3 안전망 — 거래소 orphan open order 감지 (사용자 #VICUSDT 보고 2026-05-15) =====
        # LIMIT 미체결 주문이 archive/stop 시 cancel_all_orders 누락으로 거래소에 잔존
        # 하는 케이스. WARN RiskEvent 기록 — 운영자가 거래소에서 직접 취소 권장.
        try:
            n_orphan_oo = detect_orphan_exchange_open_orders(
                db, decrypt_func=decrypt_func, auto_cancel=False,
            )
            if n_orphan_oo:
                logger.warning(
                    "Zombie Guardian: %d orphan exchange open order(s) detected", n_orphan_oo
                )
        except Exception as e:
            logger.error("detect_orphan_exchange_open_orders 실패: %s", e)
            db.rollback()
            capture_strategy_event(
                "detect_orphan_exchange_open_orders failed",
                level="error", error=e,
                tags={"event_type": "ORPHAN_OO_DETECTION_LOOP_FAILED"},
            )

        # ===== Phase 4 안전망 (2026-06-02 #20) — DB → 거래소 sync (외부 cancel 감지) =====
        # 우리 DB Order.status = NEW/PARTIALLY_FILLED 인데 거래소 openOrders 에 없음
        # → 사용자가 Binance UI 에서 직접 cancel 했거나 외부 expire
        # → 우리 DB 가 stale 면 stage_trigger 가 매번 같은 stage 재시도 + 다음 단계 진입 불가
        # → auto_fix_db=True 로 DB Order.status → CANCELED 자동 정정 + 알림.
        try:
            n_orphan_db = detect_orphan_db_orders(
                db, decrypt_func=decrypt_func, auto_fix_db=True,
            )
            if n_orphan_db:
                logger.warning(
                    "Zombie Guardian: %d DB order(s) out-of-sync (auto-fixed)", n_orphan_db
                )
        except Exception as e:
            logger.error("detect_orphan_db_orders 실패: %s", e)
            db.rollback()
            capture_strategy_event(
                "detect_orphan_db_orders failed",
                level="error", error=e,
                tags={"event_type": "ORPHAN_DB_ORDER_DETECTION_LOOP_FAILED"},
            )

        # ===== Phase 4 안전망 — STOPPING 갇힘 감지 (2026-05-21, #77/#78 사례 재발 방지) =====
        # 사장님 #77 PHB / #78 RONIN 사례 (실 손해 ~$384):
        #   emergency_close 가 거래소에서 거절 → strategy.status="STOPPING" 갇힘.
        #   거래소엔 포지션이 그대로 남아있고, reconcile 의 matched 분기는 「positionAmt
        #   != 0」 케이스를 자동 정리 못 함 (= 정상 — 거래소에 실 포지션이 있음). 그 사이
        #   `_NOT_FOR_TP_SL` 필터에 막혀 TP/SL 평가도 차단 → PHB 가 +20% (TP3) 임계점을
        #   지나갔는데도 TP 미발동 → 결국 -24 로 회귀 (피크 +359 → -24, 손실 ~$384).
        #
        # 본 가드:
        #   - reconcile 매 사이클 (2분 주기) STOPPING + updated_at 5분 초과 strategy 스캔
        #   - 각 strategy 별 30분 cooldown (Redis) — 사이클마다 알림 폭주 차단
        #   - 텔레그램 CRITICAL: 「긴급 종료 재시도 또는 거래소 UI 직접 청산 필요」
        #   - RiskEvent CRITICAL 기록 — UI 알림 + 감사 추적
        try:
            _detect_stopping_stuck(db, notif_svc=notif_svc, redis=_redis)
            db.commit()
        except Exception as e:
            logger.error("STOPPING stuck detection 실패: %s", e)
            db.rollback()
            capture_strategy_event(
                "STOPPING stuck detection failed",
                level="error", error=e,
                tags={"event_type": "STOPPING_STUCK_DETECTION_FAILED"},
            )
    finally:
        db.close()


# ===== STOPPING 갇힘 감지 =====
# 5분 이상 STOPPING 상태인 strategy 를 reconcile 마지막에 스캔.
# 임계는 frontend `STOPPING_STUCK_THRESHOLD_MS` 와 동일 (= 5분).
STOPPING_STUCK_THRESHOLD_SECONDS = 5 * 60

# Redis cooldown — 같은 strategy 에 대해 알림 한 번 발송 후 30분 침묵.
# 너무 짧으면 텔레그램 spam, 너무 길면 사장님이 잊을 가능성 → 30분 절충.
STOPPING_STUCK_ALERT_COOLDOWN_SECONDS = 30 * 60
STOPPING_STUCK_ALERT_REDIS_PREFIX = "stopping_stuck_alert:"


def _detect_stopping_stuck(db, *, notif_svc, redis) -> None:
    """STOPPING 5분 초과 strategy → MANUAL_CLEANUP_REQUIRED 전환 + 텔레그램 CRITICAL.

    2026-05-21 Phase 2 (사장님 요구):
      Phase 1 은 알림만 발송하고 status 는 STOPPING 그대로 두어, reconcile 의 매칭=None
      분기가 거래소 포지션 0 을 보면 자동 STOPPED 전환했음. 그 결과 「사장님이 직접
      처리한 건」 vs 「자동 정리된 건」 구분 불가 → 책임 추적 어려움.
      이제 5분 초과 시 명시적으로 MANUAL_CLEANUP_REQUIRED 로 전환 — 사장님이 거래소
      에서 직접 청산 후 「✅ 처리 완료」 클릭해야만 STOPPED 으로 전환됨.

    notif_svc / redis 는 호출부에서 만들어 전달 — _do_reconcile 본문이 이미 둘 다
    초기화한 상태라 재생성 비용을 피한다.
    """
    now = datetime.now(timezone.utc)
    threshold = now.timestamp() - STOPPING_STUCK_THRESHOLD_SECONDS

    stuck_rows = db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.status == "STOPPING")
        .where(StrategyInstance.is_archived.is_(False))
    ).scalars().all()

    for s in stuck_rows:
        # updated_at 이 NULL 인 경우는 없지만 (server_default + onupdate), 방어적 가드.
        if s.updated_at is None:
            continue
        # postgres 는 timezone=True 라 항상 tz-aware. sqlite (테스트) 는 naive 라
        # `.timestamp()` 가 로컬 타임존 기준으로 계산 — UTC 로 가정해 보정.
        updated_at = s.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        if updated_at.timestamp() > threshold:
            continue  # 아직 5분 안 지남
        age_seconds = int(now.timestamp() - updated_at.timestamp())
        age_min = age_seconds // 60

        # cooldown 검사 — Redis 에 키 존재하면 skip. 실패 시 (Redis down) cooldown 무시
        # 하지 말고 알림 발송 — 갇힘은 무시하면 안 됨.
        # Phase 2: status 가 이미 MANUAL_CLEANUP_REQUIRED 로 전환된 후엔 status 자체가
        # 「STOPPING != MANUAL_CLEANUP_REQUIRED」 이라 다음 사이클 select 에서 빠짐 →
        # cooldown 이 사실상 무의미해졌지만, execution_service 의 post-verify 가 곧바로
        # MANUAL_CLEANUP_REQUIRED 전환한 후 reconcile 이 STOPPING 으로 잡으려는 race 만
        # 차단하기 위해 유지.
        cooldown_key = f"{STOPPING_STUCK_ALERT_REDIS_PREFIX}{s.id}"
        already_alerted = False
        if redis is not None:
            try:
                already_alerted = bool(redis.get(cooldown_key))
            except Exception as e:
                logger.debug("STOPPING cooldown 조회 실패 (alert 계속): %s", e)
        if already_alerted:
            continue

        title = f"🔴 [긴급] 전략 종료 갇힘 — #{s.id} {s.symbol} {s.side}"
        body = (
            f"⚠️ STOPPING 상태가 {age_min}분째 지속 (updated_at={updated_at.isoformat()})\n"
            f"\n"
            f"원인: emergency_close 가 거래소에서 거절돼 status 만 STOPPING 으로 남음. "
            f"거래소엔 포지션이 잔재할 가능성 높음.\n"
            f"\n"
            f"부작용: TP/SL 평가가 차단됨 (`_NOT_FOR_TP_SL` 필터) — 그 사이 가격이 익절 "
            f"임계 넘어도 자동 청산 안 됨.\n"
            f"\n"
            f"status: STOPPING → MANUAL_CLEANUP_REQUIRED 자동 전환됨.\n"
            f"자동 STOPPED 전환 차단 — 사장님 명시적 확인 필요.\n"
            f"\n"
            f"조치:\n"
            f"  1) 대시보드의 「🛑 긴급 종료」 재시도\n"
            f"  2) 실패 시 Binance 거래소 UI 에서 직접 포지션 청산\n"
            f"  3) 완료 후 대시보드에서 「✅ 수동 청산 처리 완료」 클릭"
        )
        # MANUAL_CLEANUP_REQUIRED 전환 + 알림 + RiskEvent.
        s.status = MANUAL_CLEANUP_REQUIRED
        notif_svc.send_system_alert(title=title, body=body)
        db.add(RiskEvent(
            strategy_instance_id=s.id,
            event_type="STOPPING_STUCK_DETECTED",
            severity="CRITICAL",
            title=title,
            message=body,
            event_payload={
                "strategy_id": s.id,
                "age_seconds": age_seconds,
                "updated_at": updated_at.isoformat(),
                "previous_status": "STOPPING",
                "new_status": MANUAL_CLEANUP_REQUIRED,
            },
        ))
        logger.critical(
            "STOPPING stuck → MANUAL_CLEANUP_REQUIRED: strategy_id=%s symbol=%s side=%s age=%dmin",
            s.id, s.symbol, s.side, age_min,
        )

        if redis is not None:
            try:
                redis.setex(cooldown_key, STOPPING_STUCK_ALERT_COOLDOWN_SECONDS, "1")
            except Exception as e:
                logger.debug("STOPPING cooldown 저장 실패 (다음 사이클 재알림 가능): %s", e)
