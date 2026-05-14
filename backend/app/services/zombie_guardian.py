"""Zombie Guardian — 좀비 strategy 통합 방어/감지/강제종료.

좀비 정의:
  - DB 의 strategy 상태와 거래소 실제 포지션이 일치하지 않는 모든 케이스
  - 또는 같은 거래소 포지션을 두 strategy 가 점유하는 케이스

본 모듈이 다루는 6가지 패턴:
  A. STOPPING stuck             — 「수동 정지」 후 청산 미완료
  B. *_OPEN_PENDING stuck       — LIMIT 진입 후 stream 이벤트 누락
  C. *_OPEN orphan              — DB 는 OPEN 인데 거래소 포지션 0 (외부 청산 등)
  D. 중복 active                 — 같은 (acc, sym, side) 에 active 2개+ (race)
  E. status-qty 불일치           — STOPPED/COMPLETED 인데 current_position_qty ≠ 0
  F. orphan exchange position   — 거래소엔 포지션 있는데 DB 매칭 active 없음

처리 정책:
  Phase 1 (자동 회복) — A/B/C/D/E 는 한 사이클 안에 자동 정리
  Phase 2 (안전망)    — 자동 회복 실패 시 (N 사이클 stuck) 또는 F 발생 시:
    1) 해당 strategy 강제 STOPPED + qty=0
    2) AccountKillSwitch.trigger()  → 신규 주문 차단
    3) Telegram CRITICAL 알림 + RiskEvent CRITICAL 기록
    4) 대시보드 배너 (frontend 가 RiskEvent CRITICAL 을 표시)

Redis 키:
  zombie:stuck_count:{strategy_id}  — 연속 mismatch 카운트 (TTL 5분)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.sentry import capture_strategy_event
from app.core.strategy_status import (
    ACTIVE_LIKE,
    ACTIVE_WAITING,
    ACTIVE_WITH_POSITION,
    TERMINAL_STATUSES,
)
from app.models.exchange_account import ExchangeAccount
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from app.observability.metrics import position_reconcile_total
from app.services.account_kill_switch_service import AccountKillSwitchService
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


# ===== 상태 분류 (2026-05-14 Phase 1: app.core.strategy_status 로 centralize) =====
# 이전엔 여기에 inline 으로 4곳 다 같은 패턴이 흩어져 있었고 (zombie / reconcile / daily_loss / orchestrator),
# 5-06 TP10 확장 시 3곳 누락 → recurring bug. 이제 1곳에서 single source.
# 변경 시 app/core/strategy_status.py 만 수정하면 모든 worker 자동 반영.
__all__ = ["ACTIVE_WITH_POSITION", "ACTIVE_WAITING", "ACTIVE_LIKE", "TERMINAL_STATUSES"]


# ===== Redis 키 =====
STUCK_COUNT_KEY = "zombie:stuck_count:{strategy_id}"
STUCK_COUNT_TTL_SEC = 300  # 5분 (10 cycles 헤드룸)
STUCK_THRESHOLD = 5         # 5 사이클 (~2.5분) 연속 mismatch 시 escalate


def _redis():
    """Redis client. 장애 시 None 반환 (zombie counter 비활성, fail-soft)."""
    try:
        from app.core.redis_client import get_redis_client
        return get_redis_client()
    except Exception as e:
        logger.warning("Zombie Guardian: Redis unavailable, stuck_count disabled: %s", e)
        return None


def _stuck_inc(strategy_id: int) -> int:
    """연속 mismatch 카운터 증가. 현재 값 반환. Redis 없으면 0."""
    r = _redis()
    if r is None:
        return 0
    key = STUCK_COUNT_KEY.format(strategy_id=strategy_id)
    try:
        n = r.incr(key)
        r.expire(key, STUCK_COUNT_TTL_SEC)
        return int(n)
    except Exception:
        return 0


def _stuck_clear(strategy_id: int) -> None:
    """카운터 리셋 (정합성 회복 시)."""
    r = _redis()
    if r is None:
        return
    try:
        r.delete(STUCK_COUNT_KEY.format(strategy_id=strategy_id))
    except Exception:
        pass


# ============================================================================
# Phase 1 — 자동 회복 (preventive)
# ============================================================================

def pre_pass_dedup(db: Session) -> int:
    """동일 (account, symbol, side) 중복 active → 가장 최근 1개만 남기고 STOPPED.

    반환: 강등된 좀비 strategy 수.
    """
    rows = db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.status.in_(ACTIVE_LIKE))
        .where(StrategyInstance.is_archived.is_(False))  # 2026-05-06 C-full
        .order_by(StrategyInstance.id.desc())
    ).scalars().all()
    seen: dict[tuple, int] = {}
    demoted = 0
    for s in rows:
        key = (s.exchange_account_id, s.symbol, s.side)
        if key not in seen:
            seen[key] = s.id
            continue
        keeper_id = seen[key]
        db.add(RiskEvent(
            strategy_instance_id=s.id,
            event_type="ZOMBIE_DUPLICATE_ACTIVE_DEMOTED",
            severity="WARN",
            title="🧹 동일 심볼+방향 중복 active — 좀비 강등",
            message=(
                f"#{s.id} {s.symbol} {s.side} ({s.status}) — 같은 키에 더 최근 #{keeper_id} 존재. "
                f"이쪽을 STOPPED 로 강등 (거래소 포지션은 #{keeper_id} 가 점유)."
            ),
            event_payload={
                "zombie_strategy_id": s.id,
                "keeper_strategy_id": keeper_id,
                "old_status": s.status,
                "symbol": s.symbol,
                "side": s.side,
            },
        ))
        s.status = "STOPPED"
        s.current_position_qty = Decimal("0")
        if not s.stopped_at:
            s.stopped_at = datetime.now(timezone.utc)
        position_reconcile_total.labels(status="duplicate_zombie_stopped").inc()
        _stuck_clear(s.id)
        demoted += 1
    return demoted


def enforce_terminal_qty_zero(db: Session) -> int:
    """TERMINAL 상태인데 current_position_qty != 0 → qty=0 강제.

    ex) #83 XNYUSDT STOPPED + qty=-60842 같은 케이스. UI/통계 오염 방지.
    """
    rows = db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.status.in_(TERMINAL_STATUSES))
        .where(StrategyInstance.current_position_qty.isnot(None))
    ).scalars().all()
    fixed = 0
    for s in rows:
        try:
            qty = Decimal(str(s.current_position_qty or 0))
        except Exception:
            qty = Decimal("0")
        if qty == 0:
            continue
        db.add(RiskEvent(
            strategy_instance_id=s.id,
            event_type="ZOMBIE_TERMINAL_QTY_RESET",
            severity="INFO",
            title="🧹 종료 상태 qty 잔재 정리",
            message=f"#{s.id} {s.symbol} {s.side} {s.status} — qty {qty} → 0 (UI/통계 정합성 보장)",
            event_payload={
                "strategy_id": s.id, "old_qty": str(qty), "status": s.status,
            },
        ))
        s.current_position_qty = Decimal("0")
        fixed += 1
    return fixed


# ============================================================================
# Phase 2 — 안전망 (escalation)
# ============================================================================

def escalate_stuck_strategy(
    db: Session,
    strategy: StrategyInstance,
    *,
    reason_code: str,
    reason_detail: str,
    exchange_snapshot: Optional[dict] = None,
) -> None:
    """N 사이클 stuck 좀비 → 강제 STOPPED + AccountKillSwitch + Telegram CRITICAL.

    호출 후 카운터는 리셋되며, RiskEvent CRITICAL 이 남아 대시보드에서 빨간 배너로 표시.
    """
    old_status = strategy.status
    old_qty = strategy.current_position_qty

    # 1) 강제 STOPPED + qty=0
    strategy.status = "STOPPED"
    strategy.current_position_qty = Decimal("0")
    if not strategy.stopped_at:
        strategy.stopped_at = datetime.now(timezone.utc)

    # 2) RiskEvent CRITICAL
    db.add(RiskEvent(
        strategy_instance_id=strategy.id,
        event_type="ZOMBIE_GUARDIAN_FORCE_STOP",
        severity="CRITICAL",
        title="🚨🔴 좀비 임계 초과 — 강제종료 + Kill-Switch 발동",
        message=(
            f"#{strategy.id} {strategy.symbol} {strategy.side} "
            f"({old_status}, qty={old_qty}) — {reason_code}: {reason_detail}. "
            f"강제 STOPPED + qty=0, 해당 계정 Kill-Switch 자동 발동."
        ),
        event_payload={
            "strategy_id": strategy.id,
            "old_status": old_status,
            "old_qty": str(old_qty),
            "reason_code": reason_code,
            "reason_detail": reason_detail,
            "exchange_snapshot": exchange_snapshot,
        },
    ))

    # 3) AccountKillSwitch 자동 발동 (해당 계정 신규 주문 전체 차단)
    try:
        AccountKillSwitchService(db).trigger(
            exchange_account_id=strategy.exchange_account_id,
            reason_code=f"ZOMBIE:{reason_code}",
            reason_message=f"좀비 strategy #{strategy.id} ({strategy.symbol} {strategy.side}) — {reason_detail}",
        )
    except Exception as e:
        logger.error("Zombie Guardian: kill-switch trigger 실패: %s", e)

    # 4) Telegram CRITICAL 알림
    try:
        notif = NotificationService(db)
        title = f"🚨🔴 [좀비 자동 강제종료] #{strategy.id} {strategy.symbol} {strategy.side}"
        body_lines = [
            f"⛔ 사유 코드   : {reason_code}",
            f"📝 상세        : {reason_detail}",
            f"📊 이전 상태   : {old_status}, qty={old_qty}",
            f"✅ 처리        : 강제 STOPPED + qty=0",
            f"🔒 Kill-Switch : 계정 #{strategy.exchange_account_id} 신규 주문 자동 차단됨",
            "",
        ]
        if exchange_snapshot:
            body_lines.append("📋 거래소 실제 포지션 스냅샷:")
            body_lines.append(
                f"   • amt={exchange_snapshot.get('positionAmt')}  "
                f"entry={exchange_snapshot.get('entryPrice')}  "
                f"mark={exchange_snapshot.get('markPrice')}  "
                f"uPnL={exchange_snapshot.get('unRealizedProfit')}"
            )
            body_lines.append("   ⚠️ 거래소 포지션은 자동 청산되지 않음 — 운영자가 직접 확인/처리 필요.")
        body_lines.append("")
        body_lines.append("👉 대시보드에서 거래소 실제 포지션 vs DB 비교 후, Kill-Switch 해제 + 수동 정리 권장.")
        notif.send_system_alert(title=title, body="\n".join(body_lines))
    except Exception as e:
        logger.error("Zombie Guardian: Telegram 알림 실패: %s", e)

    _stuck_clear(strategy.id)
    position_reconcile_total.labels(status="zombie_force_stop_escalation").inc()

    # Sentry 캡처 — 운영 알림 (DSN 설정 시 자동 전송, 미설정 시 no-op).
    capture_strategy_event(
        f"Zombie Guardian force-stop: {reason_code}",
        level="fatal",
        strategy_id=strategy.id, symbol=strategy.symbol, side=strategy.side,
        account_id=strategy.exchange_account_id,
        extras={
            "reason_code": reason_code,
            "reason_detail": reason_detail,
            "old_status": old_status,
            "old_qty": str(old_qty),
            "exchange_snapshot": exchange_snapshot,
        },
        tags={"event_type": "ZOMBIE_GUARDIAN_FORCE_STOP"},
    )


def detect_orphan_exchange_positions(
    db: Session,
    *,
    decrypt_func,
    positions_cache: dict[int, list[dict]] | None = None,
) -> int:
    """거래소엔 포지션 있는데 DB 에 매칭 active strategy 없음 → CRITICAL 알림 + Kill-Switch.

    이 케이스는 시스템 외부 장애 (사용자가 거래소에서 수동 진입, 또는 DB 손실 등) 의 강한 신호.

    2026-05-09 (rate limit 사후): positions_cache 인자로 main loop 가 이미 fetch 한
    bulk 결과를 받아 같은 cycle 안에서 거래소 호출 중복 제거. 키 = exchange_account_id.
    """
    accounts = db.execute(
        select(ExchangeAccount).where(ExchangeAccount.is_active.is_(True))
    ).scalars().all()
    found = 0
    for acc in accounts:
        try:
            # cache hit 시 거래소 재호출 X (rate limit 부담 감소)
            if positions_cache is not None and acc.id in positions_cache:
                risk = positions_cache[acc.id]
            else:
                from app.integrations.binance.client import BinanceClient
                client = BinanceClient(
                    api_key=decrypt_func(acc.api_key_enc),
                    api_secret=decrypt_func(acc.api_secret_enc),
                    is_testnet=acc.is_testnet,
                )
                # 거래소의 모든 포지션 (positionAmt != 0)
                risk = client.get_position_risk()
            if isinstance(risk, dict):
                risk = [risk]
            for p in risk:
                amt_str = p.get("positionAmt", "0")
                try:
                    amt = Decimal(str(amt_str))
                except Exception:
                    amt = Decimal("0")
                if amt == 0:
                    continue
                symbol = p.get("symbol")
                position_side = p.get("positionSide")
                # DB 에 매칭 active strategy 가 있는지 확인
                match = db.execute(
                    select(StrategyInstance)
                    .where(StrategyInstance.exchange_account_id == acc.id)
                    .where(StrategyInstance.symbol == symbol)
                    .where(StrategyInstance.side == position_side)
                    .where(StrategyInstance.status.in_(ACTIVE_LIKE))
                    .limit(1)
                ).scalar_one_or_none()
                if match:
                    continue
                # 2026-05-08 #120 fix: KS 발동 전 transition race 한 번 더 검증.
                # REENTRY_READY 는 exit FILLED 직후 transition status — 거래소 잔량이
                # 아직 정리 안 된 race window 가능. 같은 심볼/방향의 REENTRY_READY
                # strategy 가 최근 5분 내에 있으면 KS 보류 (reconcile 가 다음 cycle 에 정정).
                # STOPPED / COMPLETED / archived 는 정상 종료라 잔량 있으면 진짜 orphan.
                from datetime import datetime, timedelta, timezone
                recent_match = db.execute(
                    select(StrategyInstance)
                    .where(StrategyInstance.exchange_account_id == acc.id)
                    .where(StrategyInstance.symbol == symbol)
                    .where(StrategyInstance.side == position_side)
                    .where(StrategyInstance.is_archived.is_(False))
                    .where(StrategyInstance.status == "REENTRY_READY")
                    .where(StrategyInstance.updated_at >= datetime.now(timezone.utc) - timedelta(minutes=5))
                    .order_by(StrategyInstance.id.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if recent_match:
                    logger.warning(
                        "Orphan candidate %s %s amt=%s: recent strategy #%s (status=%s) — KS 보류 (race window)",
                        symbol, position_side, amt, recent_match.id, recent_match.status,
                    )
                    db.add(RiskEvent(
                        strategy_instance_id=recent_match.id,
                        event_type="ZOMBIE_ORPHAN_RACE_DEFERRED",
                        severity="WARN",
                        title="⚠️ Orphan 후보 — 최근 strategy 매칭으로 KS 보류",
                        message=(
                            f"거래소 {symbol} {position_side} amt={amt} 에 ACTIVE 매칭은 없으나 "
                            f"최근 5분 내 #{recent_match.id} (status={recent_match.status}) 가 같은 종목/방향. "
                            "transition window race 가능성 — KS 보류, 다음 sweep 에 재평가."
                        ),
                        event_payload={"account_id": acc.id, "exchange_snapshot": {
                            "symbol": symbol, "positionSide": position_side,
                            "positionAmt": str(amt),
                        }, "recent_strategy_id": recent_match.id, "recent_status": recent_match.status},
                    ))
                    db.commit()
                    continue  # KS 발동 안 함 — 다음 cycle 재평가
                # 매칭 없음 — orphan exchange position!
                found += 1
                snapshot = {
                    "symbol": symbol,
                    "positionSide": position_side,
                    "positionAmt": p.get("positionAmt"),
                    "entryPrice": p.get("entryPrice"),
                    "markPrice": p.get("markPrice"),
                    "unRealizedProfit": p.get("unRealizedProfit"),
                    "liquidationPrice": p.get("liquidationPrice"),
                }
                db.add(RiskEvent(
                    strategy_instance_id=None,
                    event_type="ZOMBIE_ORPHAN_EXCHANGE_POSITION",
                    severity="CRITICAL",
                    title="🚨🔴 거래소 orphan 포지션 감지 — Kill-Switch 발동",
                    message=(
                        f"계정 #{acc.id}: 거래소에 {symbol} {position_side} 포지션 amt={amt} 있는데 "
                        "DB 에 매칭 active strategy 없음. 외부 진입 또는 DB 손실 의심. "
                        "신규 주문 자동 차단 — 운영자 즉시 확인 필요."
                    ),
                    event_payload={"account_id": acc.id, "exchange_snapshot": snapshot},
                ))
                # AccountKillSwitch 자동 발동
                try:
                    AccountKillSwitchService(db).trigger(
                        exchange_account_id=acc.id,
                        reason_code="ZOMBIE:ORPHAN_EXCHANGE_POSITION",
                        reason_message=(
                            f"거래소 {symbol} {position_side} 포지션 (amt={amt}) 에 매칭 strategy 없음"
                        ),
                    )
                except Exception as e:
                    logger.error("Orphan exchange position: kill-switch 실패: %s", e)
                # Telegram CRITICAL
                try:
                    NotificationService(db).send_system_alert(
                        title=f"🚨🔴 [거래소 Orphan 포지션] account #{acc.id} {symbol} {position_side}",
                        body="\n".join([
                            f"⛔ 거래소엔 포지션 있는데 시스템 active strategy 매칭 없음",
                            f"📊 amt          : {p.get('positionAmt')}",
                            f"💵 entry        : {p.get('entryPrice')}",
                            f"💵 mark         : {p.get('markPrice')}",
                            f"💎 uPnL         : {p.get('unRealizedProfit')}",
                            f"💀 liq          : {p.get('liquidationPrice')}",
                            "",
                            f"🔒 Kill-Switch  : 계정 #{acc.id} 신규 주문 자동 차단",
                            "",
                            "원인 후보:",
                            "  • 사용자가 Binance UI 에서 직접 진입",
                            "  • DB 손상 / 마이그레이션 누락",
                            "  • 시스템 미인지 진입",
                            "",
                            "👉 대시보드 확인 후 거래소 직접 청산 + Kill-Switch 해제 권장.",
                        ]),
                    )
                except Exception as e:
                    logger.error("Orphan exchange position: Telegram 실패: %s", e)
                position_reconcile_total.labels(status="orphan_exchange_position").inc()
                # Sentry 캡처 — orphan 은 거래소-시스템 정합성 깨진 가장 위험한 신호.
                capture_strategy_event(
                    f"Zombie Guardian orphan exchange position: {symbol} {position_side}",
                    level="fatal",
                    symbol=symbol, side=position_side, account_id=acc.id,
                    extras={"exchange_snapshot": snapshot, "amount": str(amt)},
                    tags={"event_type": "ZOMBIE_ORPHAN_EXCHANGE_POSITION"},
                )
        except Exception as e:
            logger.error("Orphan exchange detect 실패 acc=%s: %s", acc.id, e)
            capture_strategy_event(
                "detect_orphan_exchange_positions failed",
                level="error",
                account_id=acc.id, error=e,
                tags={"event_type": "ORPHAN_DETECT_FAILED"},
            )
    return found
