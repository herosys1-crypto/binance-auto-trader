from datetime import datetime, timezone
from decimal import Decimal
import logging
from sqlalchemy import select
from app.core.database import SessionLocal
from app.core.redis_client import get_redis_client
from app.core.redis_lock import redis_lock, RedisLockError
from app.integrations.binance.client import BinanceClient
from app.models.exchange_account import ExchangeAccount
from app.models.position import Position
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from app.observability.metrics import position_reconcile_total, position_qty_mismatch_total

logger = logging.getLogger(__name__)

# A07 fix (audit 2026-05-02): 다중 instance / re-entrant 호출 방지.
# distributed_scheduler_guard 가 이미 있지만, ad-hoc 호출 (admin endpoint 등) 도 있을 수 있어
# 한 번에 한 reconcile 사이클만 실행되도록 redis lock 추가.
RECONCILE_LOCK_KEY = "lock:reconcile_worker"
RECONCILE_LOCK_TTL = 60  # 한 사이클 최대 60초 (정상 30초 cycle 의 2배 헤드룸)


def run_position_reconcile_once(decrypt_func) -> None:
    try:
        redis_client = get_redis_client()
    except Exception:
        # Redis 장애 시 lock 없이 진행 (기존 동작 유지)
        return _do_reconcile(decrypt_func)
    try:
        with redis_lock(redis_client, RECONCILE_LOCK_KEY, ttl_seconds=RECONCILE_LOCK_TTL, wait_timeout_seconds=0):
            _do_reconcile(decrypt_func)
    except RedisLockError:
        # 다른 인스턴스가 동시에 reconcile 중 — skip (정상)
        logger.debug("reconcile_worker skip — another instance holds lock")


def _do_reconcile(decrypt_func) -> None:
    db = SessionLocal()
    try:
        # 활성 전략 조회. *_PENDING 상태도 포함 — user-stream 이 죽어 체결 이벤트를
        # 놓친 경우 reconcile 이 거래소 상태를 보고 PENDING -> OPEN 으로 자가 회복할 수 있게.
        rows = db.execute(
            select(StrategyInstance, ExchangeAccount)
            .join(ExchangeAccount, StrategyInstance.exchange_account_id == ExchangeAccount.id)
            .where(StrategyInstance.status.in_([
                "STAGE1_OPEN_PENDING", "STAGE2_OPEN_PENDING", "STAGE3_OPEN_PENDING", "STAGE4_OPEN_PENDING",
                "STAGE1_OPEN", "STAGE2_OPEN", "STAGE3_OPEN", "STAGE4_OPEN",
                "TP1_DONE_PARTIAL", "TP2_DONE_PARTIAL",
                # 좀비 STOPPING 자동 정리 — 거래소 포지션 0 이면 STOPPED 로 전환 (stream 이벤트 놓친 안전망)
                "STOPPING",
            ]))
            .where(ExchangeAccount.is_active.is_(True))
        ).all()
        for strategy, account in rows:
            try:
                client = BinanceClient(api_key=decrypt_func(account.api_key_enc), api_secret=decrypt_func(account.api_secret_enc), is_testnet=account.is_testnet)
                position_risk = client.get_position_risk(symbol=strategy.symbol)
                if isinstance(position_risk, dict):
                    position_risk = [position_risk]
                matched = None
                for item in position_risk:
                    if item.get("symbol") == strategy.symbol and item.get("positionSide") == strategy.side:
                        matched = item
                        break
                if not matched:
                    # 좀비 STOPPING 자동 정리: status=STOPPING + 거래소 포지션 0 → STOPPED 로 승격.
                    # 사용자가 「수동 정지」 누른 후 stream 이벤트 (EXIT FILLED) 를 놓치면 좀비
                    # 발생. reconcile 한 사이클 안에 자동 회복.
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
                        continue
                    # Bug #10 fix (2026-04-29): DB-only 잔재 자동 정리 — 단, 보수적으로
                    # *_OPEN 상태(이미 체결되었던 상태)만 처리. PENDING 은 limit 주문이
                    # 아직 미체결일 가능성이 있어 자동 STOPPED 하면 위험.
                    _OPEN_STATES = {"STAGE1_OPEN", "STAGE2_OPEN", "STAGE3_OPEN", "STAGE4_OPEN",
                                    "TP1_DONE_PARTIAL", "TP2_DONE_PARTIAL"}
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
                        position_reconcile_total.labels(status="orphan_stopped").inc()
                    else:
                        # PENDING 등 — 단순 RiskEvent 만 (사용자 모니터링용)
                        db.add(RiskEvent(
                            strategy_instance_id=strategy.id,
                            event_type="POSITION_RECONCILE_MISS",
                            severity="WARN",
                            title="⚠️ 거래소에 매칭 포지션 없음",
                            message=f"{strategy.symbol} {strategy.side} — DB 는 active 인데 거래소엔 포지션 없음 (확인 필요)",
                            event_payload={"strategy_id": strategy.id},
                        ))
                        position_reconcile_total.labels(status="miss").inc()
                    continue
                exchange_position_amt = Decimal(str(matched.get("positionAmt", "0")))
                exchange_entry_price = Decimal(str(matched.get("entryPrice", "0")))
                exchange_mark_price = Decimal(str(matched.get("markPrice", "0")))
                exchange_unrealized_pnl = Decimal(str(matched.get("unRealizedProfit", "0")))
                exchange_liquidation_price = Decimal(str(matched.get("liquidationPrice", "0")))
                db.add(Position(strategy_instance_id=strategy.id, symbol=strategy.symbol, side=strategy.side, position_side=strategy.side, entry_price=exchange_entry_price if exchange_entry_price > 0 else None, break_even_price=Decimal(str(matched.get("breakEvenPrice", "0"))) or None, mark_price=exchange_mark_price if exchange_mark_price > 0 else None, liquidation_price=exchange_liquidation_price if exchange_liquidation_price > 0 else None, position_amt=exchange_position_amt, isolated_margin=Decimal(str(matched.get("isolatedMargin", "0"))), unrealized_pnl=exchange_unrealized_pnl, margin_type=matched.get("marginType"), leverage=int(matched.get("leverage", strategy.leverage)) if matched.get("leverage") else strategy.leverage, source="POSITION_RISK_SYNC"))
                local_qty = Decimal(str(strategy.current_position_qty or 0))
                if local_qty != exchange_position_amt:
                    db.add(RiskEvent(strategy_instance_id=strategy.id, event_type="POSITION_QTY_MISMATCH", severity="WARN", title="⚠️ 포지션 수량 불일치 (DB ↔ 거래소)", message=f"시스템 기록 {local_qty} vs 거래소 실 포지션 {exchange_position_amt} — reconcile 이 자동 동기화함", event_payload={"local_qty": str(local_qty), "exchange_qty": str(exchange_position_amt)}))
                    position_qty_mismatch_total.labels(symbol=strategy.symbol, side=strategy.side).inc()
                strategy.avg_entry_price = exchange_entry_price if exchange_entry_price > 0 else strategy.avg_entry_price
                strategy.current_position_qty = exchange_position_amt
                strategy.unrealized_pnl = exchange_unrealized_pnl
                strategy.liquidation_price = exchange_liquidation_price if exchange_liquidation_price > 0 else strategy.liquidation_price
                # 자가 회복: *_OPEN_PENDING 상태인데 거래소에 실제 포지션이 있으면 -> *_OPEN 으로 전이.
                # user-stream 이 죽어서 체결 이벤트를 놓친 케이스를 보완한다.
                _PENDING_TO_OPEN = {
                    "STAGE1_OPEN_PENDING": "STAGE1_OPEN",
                    "STAGE2_OPEN_PENDING": "STAGE2_OPEN",
                    "STAGE3_OPEN_PENDING": "STAGE3_OPEN",
                    "STAGE4_OPEN_PENDING": "STAGE4_OPEN",
                }
                if strategy.status in _PENDING_TO_OPEN and exchange_position_amt != 0:
                    new_status = _PENDING_TO_OPEN[strategy.status]
                    db.add(RiskEvent(
                        strategy_instance_id=strategy.id,
                        event_type="RECONCILE_RECOVERED_PENDING",
                        severity="WARN",
                        title="Reconciled stuck PENDING -> OPEN",
                        message=f"status {strategy.status} -> {new_status} (exchange position={exchange_position_amt})",
                        event_payload={"strategy_id": strategy.id, "old_status": strategy.status, "new_status": new_status, "position_amt": str(exchange_position_amt)},
                    ))
                    strategy.status = new_status
                position_reconcile_total.labels(status="success").inc()
            except Exception as e:
                db.add(RiskEvent(strategy_instance_id=strategy.id, event_type="POSITION_RECONCILE_ERROR", severity="ERROR", title="Position reconcile failed", message=str(e), event_payload={"strategy_id": strategy.id}))
                position_reconcile_total.labels(status="error").inc()
        db.commit()
    finally:
        db.close()
