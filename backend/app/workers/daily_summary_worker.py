"""일일 운영 요약 worker — 매일 00:00 KST 사장님 텔레그램.

2026-06-03 신설:
- 사장님 운영 추적 가시화 — 매일 자동 발송
- 내용: 어제 신규/종료 strategy, 실현 손익 합, SL/TP 발동, 현재 활성/잔액
- 사장님이 매일 아침 한눈에 운영 현황 파악

스케줄: scheduler_runner.py 에 CronTrigger(hour=15, minute=0) 등록 (UTC 15:00 = KST 00:00).
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, and_, or_

from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_WITH_POSITION, TERMINAL_STATUSES
from app.models.notification import Notification
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance

logger = logging.getLogger(__name__)

# KST = UTC+9. 자정 KST = 15:00 UTC.
_KST_OFFSET = timedelta(hours=9)


def _kst_today_window() -> tuple[datetime, datetime]:
    """어제 KST 00:00 ~ 오늘 KST 00:00 (UTC 변환)."""
    now_kst = datetime.now(timezone.utc) + _KST_OFFSET
    today_midnight_kst = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_midnight_kst = today_midnight_kst - timedelta(days=1)
    # UTC 로 변환 (KST → UTC 는 -9시간)
    start_utc = (yesterday_midnight_kst - _KST_OFFSET).replace(tzinfo=timezone.utc)
    end_utc = (today_midnight_kst - _KST_OFFSET).replace(tzinfo=timezone.utc)
    return start_utc, end_utc, yesterday_midnight_kst.strftime("%Y-%m-%d")


def run_daily_summary_once() -> None:
    """1회 실행 — 어제 (KST 기준) 운영 요약 + 현재 상태 → 사장님 텔레그램.

    scheduler 가 매일 UTC 15:00 (KST 00:00) 호출.
    """
    from app.services.notification_service import NotificationService

    start_utc, end_utc, date_label = _kst_today_window()
    db = SessionLocal()
    try:
        # 어제 신규 strategy
        new_strategies = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.created_at >= start_utc)
            .where(StrategyInstance.created_at < end_utc)
        ).scalars().all()
        new_count = len(new_strategies)

        # 어제 종료 strategy (stopped_at)
        stopped_strategies = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.stopped_at >= start_utc)
            .where(StrategyInstance.stopped_at < end_utc)
        ).scalars().all()
        stopped_count = len(stopped_strategies)

        # 어제 종료 분류 (status 기반)
        stopped_by_sl = sum(1 for s in stopped_strategies if (s.status or "").upper() in {"STOPPED_BY_SL", "CLOSED_BY_SL"})
        stopped_completed = sum(1 for s in stopped_strategies if (s.status or "").upper() in {"COMPLETED", "REENTRY_READY"})
        stopped_manual = sum(1 for s in stopped_strategies if (s.status or "").upper() == "STOPPED")

        # 어제 종료 실현 손익 합 (positive + negative 분리)
        realized_total = Decimal("0")
        realized_profit = Decimal("0")
        realized_loss = Decimal("0")
        for s in stopped_strategies:
            r = Decimal(str(s.realized_pnl or 0))
            realized_total += r
            if r > 0:
                realized_profit += r
            elif r < 0:
                realized_loss += r

        # 어제 RiskEvent 분류 (SL/CRISIS/MISMATCH 등)
        risk_events_yday = db.execute(
            select(RiskEvent)
            .where(RiskEvent.ts >= start_utc)
            .where(RiskEvent.ts < end_utc)
        ).scalars().all()
        sl_triggered = sum(1 for r in risk_events_yday if r.event_type == "STOP_LOSS_TRIGGERED")
        crisis_entered = sum(1 for r in risk_events_yday if r.event_type == "CRISIS_MODE_ENTERED")
        qty_mismatch = sum(1 for r in risk_events_yday if r.event_type == "POSITION_QTY_MISMATCH")

        # 어제 발송 알림 수
        notif_yday_count = db.execute(
            select(Notification.id)
            .where(Notification.ts >= start_utc)
            .where(Notification.ts < end_utc)
        ).all()

        # 현재 활성 strategy + 미실현 합
        active_strategies = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.is_archived.is_(False))
            .where(StrategyInstance.status.in_(ACTIVE_WITH_POSITION))
        ).scalars().all()
        active_count = len(active_strategies)
        unrealized_total = sum((Decimal(str(s.unrealized_pnl or 0)) for s in active_strategies), Decimal("0"))

        # 메시지 작성
        title = f"📊 일일 운영 요약 — {date_label} (KST)"
        body_lines = [
            f"📅 기간: {date_label} 00:00 ~ 24:00 (KST)",
            "",
            "━━━━━━━━━ 📈 어제 운영 ━━━━━━━━━",
            f"  • 신규 strategy: {new_count}건",
            f"  • 종료 strategy: {stopped_count}건",
            f"      - 🎯 자동익절 (COMPLETED/REENTRY): {stopped_completed}건",
            f"      - 🤖 자동손절 (SL): {stopped_by_sl}건",
            f"      - ✋ 수동종료 (STOPPED): {stopped_manual}건",
            "",
            "━━━━━━━━━ 💰 실현 손익 ━━━━━━━━━",
            f"  • 합계: {realized_total:+.2f} USDT",
            f"  • 익절: +{realized_profit:.2f} USDT",
            f"  • 손절: {realized_loss:.2f} USDT",
            "",
            "━━━━━━━━━ ⚠️ 리스크 이벤트 ━━━━━━━━━",
            f"  • SL 발동: {sl_triggered}건",
            f"  • 크라이시스 진입: {crisis_entered}건",
            f"  • 포지션 수량 불일치: {qty_mismatch}건",
            f"  • 알림 발송: {len(notif_yday_count)}건",
            "",
            "━━━━━━━━━ 📊 현재 상태 ━━━━━━━━━",
            f"  • 활성 strategy: {active_count}건",
            f"  • 미실현 손익: {unrealized_total:+.2f} USDT",
        ]
        body = "\n".join(body_lines)

        ns = NotificationService(db)
        ns.send_system_alert(title=title, body=body)
        logger.info(
            "[daily-summary] %s sent — new=%d stopped=%d realized=%s active=%d",
            date_label, new_count, stopped_count, realized_total, active_count,
        )
    except Exception as e:
        logger.exception("[daily-summary] failed: %s", e)
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    run_daily_summary_once()
    sys.exit(0)
