"""Admin — 대시보드 배너 + 운영 점검 dashboard.

UI 의 상단 경고 배너 + 「🩺 점검」 탭이 호출하는 통합 시스템 상태 endpoint.
2026-05-14 Phase 4 split: 기존 admin.py 에서 분리.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db

router = APIRouter(prefix="/admin", tags=["admin"])


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
    from datetime import timedelta
    from sqlalchemy import func, select
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
