"""Daily report worker — 일일 운영 자동 보고 (텔레그램).

배경 (2026-05-09 사용자 요청 — Layer 3):
1인 운영자가 매일 health_check 명령 실행 안 해도 자동으로 「전일 운영 요약」
받아서 1분 안에 시스템 상태 파악 가능하게 한다. 모니터링 fatigue 줄이고
중요한 변화만 인지.

동작:
- 매일 KST 09:00 (UTC 00:00) 1회 자동 발송
- 직전 24시간 (KST 어제 09:00 ~ 오늘 09:00) 데이터 집계
- 메시지 포함:
  * 거래 활동 (진입/청산/신규 strategy)
  * 텔레그램 발송 (성공/실패)
  * 위험 이벤트 (CRITICAL/ERROR/WARN — 검토 필요 분류)
  * 빈도 top 3 이벤트 (정상 패턴 마커)
  * 자동 권장 조치 (rate limit / orphan / mismatch 패턴)
  * 누적 손익 (실현 + 미실현 + 종합)

설정:
- settings.daily_report_enabled (default True, False 면 worker 자체 no-op)
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.core.strategy_status import TERMINAL_STATUSES
from app.models.notification import Notification
from app.models.order import Order
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance

logger = logging.getLogger(__name__)


# health_check.py 와 같은 정의 (BENIGN — 정상 이벤트)
_BENIGN_EVENT_TYPES = {
    "ORDER_TRADE_UPDATE",
    "ZOMBIE_ORPHAN_RACE_DEFERRED",
    "RECONCILE_RECOVERED_PENDING",
    "RECONCILE_AUTO_STOP_ORPHAN",
    "RECONCILE_STOPPING_ZOMBIE_CLEANUP",
}


def run_daily_report_once() -> None:
    """매일 1회 — 전일 운영 요약 텔레그램 발송."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=24)

        # ===== 거래 활동 =====
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

        # ===== 손익 (24h 변동 + 누적) =====
        # 24h realized 변동: updated_at 이 24h 내 + realized != 0 인 strategy 의 합
        # (정확한 일일 손익은 daily_loss_aggregator 가 별도 추적; 여기선 간이값)
        recent_realized_strategies = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.updated_at >= since)
            .where(StrategyInstance.realized_pnl != 0)
        ).scalars().all()
        realized_24h = sum(Decimal(str(s.realized_pnl or 0)) for s in recent_realized_strategies)

        # 전체 누적 realized
        total_realized = db.execute(
            select(func.sum(StrategyInstance.realized_pnl))
        ).scalar() or Decimal("0")

        # 진행 중 미실현
        active_strategies = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.status.notin_(TERMINAL_STATUSES))
            .where(StrategyInstance.is_archived.is_(False))
        ).scalars().all()
        unrealized = sum(Decimal(str(s.unrealized_pnl or 0)) for s in active_strategies)

        # ===== 텔레그램 =====
        notif_total = db.execute(
            select(func.count(Notification.id)).where(Notification.created_at >= since)
        ).scalar() or 0
        notif_failed = db.execute(
            select(func.count(Notification.id))
            .where(Notification.created_at >= since)
            .where(Notification.send_status != "SENT")
        ).scalar() or 0

        # ===== 위험 이벤트 =====
        events = db.execute(
            select(RiskEvent).where(RiskEvent.created_at >= since)
        ).scalars().all()
        sev_counts: Counter[str] = Counter()
        type_counts: Counter[str] = Counter()
        action_needed_count = 0
        for e in events:
            sev_counts[e.severity] += 1
            type_counts[e.event_type] += 1
            if e.severity in ("CRITICAL", "ERROR") and e.event_type not in _BENIGN_EVENT_TYPES:
                action_needed_count += 1

        # ===== 권장 조치 도출 =====
        recommendations = []
        rl = type_counts.get("POSITION_RECONCILE_FAILED", 0) + type_counts.get("POSITION_RECONCILE_ERROR", 0)
        if rl >= 5:
            recommendations.append(f"⚙️ Reconcile 실패 {rl}회 — rate limit 의심")
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

        # ===== 메시지 조립 =====
        is_healthy = action_needed_count == 0 and notif_failed == 0
        emoji = "📊" if is_healthy else "⚠️"
        title = f"{emoji} [일일 운영 보고] {now.strftime('%m-%d')} (직전 24h)"

        # 손익 라벨 + 부호
        def _fmt_pnl(v: Decimal) -> str:
            sign = "+" if v >= 0 else ""
            return f"{sign}{v:.2f}"

        lines = [
            "🎯 거래 활동",
            f"  • 신규 strategy: {new_strategies}건",
            f"  • 진입 체결:    {entry_count}건",
            f"  • 청산 체결:    {exit_count}건",
            "",
            "💰 손익",
            f"  • 24h 실현:    {_fmt_pnl(realized_24h)} USDT",
            f"  • 미실현:       {_fmt_pnl(unrealized)} USDT (진행 {len(active_strategies)}건)",
            f"  • 누적 (전체):  {_fmt_pnl(total_realized)} USDT",
            "",
            "📡 텔레그램",
            f"  • 발송:    {notif_total}건  (실패 {notif_failed}건)",
            "",
            "⚠️ 위험 이벤트",
        ]
        if not events:
            lines.append("  ✅ 0건 — 운영 정상")
        else:
            for sev in ("CRITICAL", "ERROR", "WARN", "INFO"):
                cnt = sev_counts.get(sev, 0)
                if cnt > 0:
                    lines.append(f"  • {sev}: {cnt}건")
            if action_needed_count > 0:
                lines.append(f"  🚨 검토 필요: {action_needed_count}건")
            else:
                lines.append("  ✅ 검토 필요 없음 (모두 정상 패턴)")

        if type_counts:
            lines.append("")
            lines.append("📋 빈도 top 3")
            for et, cnt in type_counts.most_common(3):
                marker = " (정상)" if et in _BENIGN_EVENT_TYPES else ""
                lines.append(f"  {cnt}건  {et}{marker}")

        if recommendations:
            lines.append("")
            lines.append("💡 권장 조치")
            for r in recommendations:
                lines.append(f"  {r}")
        else:
            lines.append("")
            lines.append("💡 권장 조치 없음 — 그대로 운영")

        body = "\n".join(lines)

        from app.services.notification_service import NotificationService
        NotificationService(db).send_system_alert(title=title, body=body)
        logger.info(
            "Daily report sent: entry=%s exit=%s realized_24h=%s critical=%s action_needed=%s",
            entry_count, exit_count, realized_24h, sev_counts.get("CRITICAL", 0), action_needed_count,
        )
    except Exception as e:
        logger.exception("Daily report send failed: %s", e)
    finally:
        db.close()


__all__ = ["run_daily_report_once"]
