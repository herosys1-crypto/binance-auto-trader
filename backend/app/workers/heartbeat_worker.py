"""Heartbeat worker — 24/7 운영 신뢰성 알림.

배경 (2026-05-07 사용자 운영 요청):
VPS 에서 24/7 운영 중 시스템이 정상인지 사용자가 알 수 있는 정기 신호 필요.
ngrok 폐지 + 노트북 종료 후 시스템 상태 가시성이 떨어지는 문제 해결.

동작:
- 6시간마다 1회 텔레그램 「💚 [System Heartbeat]」 알림 발송
- 메시지에 다음 포함:
  * 활성 strategy 수 / 활성 KS 수 / 좀비 stuck 카운트
  * 최근 1시간 CRITICAL RiskEvent 수
  * 직전 6시간 텔레그램 발송 (SENT/FAILED) 카운트
- 시스템 정상이면 「✅」, 문제 있으면 「⚠️」

설정:
- settings.heartbeat_interval_hours (default 6, 0/None 이면 비활성)
- 비활성 시 worker 자체가 no-op (스케줄러 등록 안 함)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.strategy_status import TERMINAL_STATUSES
from app.models.account_kill_switch import AccountKillSwitch
from app.models.notification import Notification
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance

logger = logging.getLogger(__name__)


def run_heartbeat_once() -> None:
    """6시간마다 1회 — 시스템 상태 요약 텔레그램 발송."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        cutoff_1h = now - timedelta(hours=1)
        cutoff_6h = now - timedelta(hours=6)

        # 1) 활성 strategy 수
        active_count = db.execute(
            select(func.count())
            .select_from(StrategyInstance)
            .where(StrategyInstance.status.notin_(TERMINAL_STATUSES))
            .where(StrategyInstance.is_archived.is_(False))
        ).scalar() or 0

        # 2) 활성 Kill-Switch
        ks_active = db.execute(
            select(func.count())
            .select_from(AccountKillSwitch)
            .where(AccountKillSwitch.is_enabled.is_(True))
        ).scalar() or 0

        # 3) 최근 1시간 CRITICAL RiskEvent
        recent_critical = db.execute(
            select(func.count())
            .select_from(RiskEvent)
            .where(RiskEvent.event_type.like("%CRITICAL%"))
            .where(RiskEvent.created_at >= cutoff_1h)
        ).scalar() or 0

        # 4) 직전 6시간 알림 발송 통계
        sent_count = db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.send_status == "SENT")
            .where(Notification.created_at >= cutoff_6h)
        ).scalar() or 0
        failed_count = db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.send_status == "FAILED")
            .where(Notification.created_at >= cutoff_6h)
        ).scalar() or 0

        is_healthy = ks_active == 0 and recent_critical == 0
        status_emoji = "💚" if is_healthy else "⚠️"
        status_text = "정상" if is_healthy else "주의 필요"

        title = f"{status_emoji} [System Heartbeat] {status_text}"
        body = "\n".join([
            f"⏱ 시각        : {now.strftime('%Y-%m-%d %H:%M UTC')}",
            f"📊 활성 strategy : {active_count}",
            f"🔒 Kill-Switch  : {ks_active}건 활성" if ks_active else "🔒 Kill-Switch  : 모두 비활성 ✓",
            f"🚨 최근 1h CRITICAL: {recent_critical}건" if recent_critical else "🚨 최근 1h CRITICAL: 0",
            f"📨 6h 알림: {sent_count} sent / {failed_count} failed",
        ])

        from app.services.notification_service import NotificationService
        NotificationService(db).send_system_alert(title=title, body=body)
        logger.info(
            "Heartbeat sent: active=%s ks=%s critical=%s sent=%s failed=%s",
            active_count, ks_active, recent_critical, sent_count, failed_count,
        )
    except Exception as e:
        logger.exception("Heartbeat send failed: %s", e)
    finally:
        db.close()


__all__ = ["run_heartbeat_once"]
