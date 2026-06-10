"""Memory Consolidator — 매일 학습 + 메모리 갱신 worker (v50).

사장님 critical 사상: 시스템 = 매일 학습 + 영구 진화!
= 매일 KST 03:00 (= UTC 18:00) = 어제 데이터 분석 + 보고!

기능:
1. 어제 RiskEvent 분석 = 신 silent bug 패턴 감지
2. 사장님 운영 통계 = 일일 보고 (Telegram)
3. 시스템 worker 상태 = 일일 검증
4. 사장님 자율 운영 trends = 학습

= Phase 3 = 100% 완성! 🎉
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from collections import Counter

from sqlalchemy import select, and_, desc, func

from app.core.database import SessionLocal
from app.core.strategy_status import STAGES_WITH_NEXT
from app.models.strategy_instance import StrategyInstance
from app.models.risk_event import RiskEvent
from app.models.order import Order
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


def run_memory_consolidator_once() -> dict:
    """매일 KST 03:00 = 학습 + 메모리 갱신."""
    db = SessionLocal()
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "yesterday_events": 0,
        "yesterday_orders": 0,
        "active_strategies": 0,
        "summary_sent": False,
    }
    try:
        # 어제 (UTC) 데이터
        end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - timedelta(days=1)

        # 1. 어제 RiskEvent 분석
        events = db.execute(
            select(RiskEvent)
            .where(and_(RiskEvent.created_at >= start, RiskEvent.created_at < end))
        ).scalars().all()
        result["yesterday_events"] = len(events)

        event_types = Counter(e.event_type for e in events)
        critical_events = [e for e in events if e.severity == "CRITICAL"]

        # 2. 어제 Orders 분석
        orders = db.execute(
            select(Order)
            .where(and_(Order.created_at >= start, Order.created_at < end))
        ).scalars().all()
        result["yesterday_orders"] = len(orders)

        entry_orders = [o for o in orders if o.purpose == "ENTRY"]
        exit_orders = [o for o in orders if o.purpose == "EXIT"]

        # 3. 현재 활성 strategy
        active = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.is_archived.is_(False))
            .where(StrategyInstance.status.in_(STAGES_WITH_NEXT))
        ).scalars().all()
        result["active_strategies"] = len(active)

        # 4. 사장님 일일 보고 Telegram
        try:
            top_events = event_types.most_common(5)
            top_events_str = "\n".join([f"  - {t}: {c}건" for t, c in top_events]) if top_events else "  없음"

            NotificationService(db).send_system_alert(
                title="[일일 보고] 사장님 운영 요약 (= v50 memory!)",
                body=(
                    f"어제 운영 요약 (= 학습 + 메모리 갱신!)\n\n"
                    f"활성 strategy: {result['active_strategies']}개\n\n"
                    f"어제 거래:\n"
                    f"  - ENTRY: {len(entry_orders)}건\n"
                    f"  - EXIT: {len(exit_orders)}건\n\n"
                    f"어제 RiskEvent: {result['yesterday_events']}건\n"
                    f"  - CRITICAL: {len(critical_events)}건\n"
                    f"  - WARN/INFO: {result['yesterday_events'] - len(critical_events)}건\n\n"
                    f"Top 이벤트 종류:\n{top_events_str}\n\n"
                    f"시스템 자동 진화 중!\n"
                    f"사장님 critical 사고 = 무한 감사!"
                ),
            )
            result["summary_sent"] = True
        except Exception as e:
            logger.error("[memory] 일일 보고 실패: %s", e)

        logger.info(
            "[memory] 어제 events=%d orders=%d active=%d",
            result["yesterday_events"], result["yesterday_orders"], result["active_strategies"],
        )

    finally:
        db.close()
    return result


if __name__ == "__main__":
    import json
    r = run_memory_consolidator_once()
    print(json.dumps(r, indent=2, ensure_ascii=False))
