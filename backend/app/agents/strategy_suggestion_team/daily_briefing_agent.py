"""🌅 DailyBriefingAgent = 매일 아침 학습 브리핑!

Team: Strategy Suggestion
실행: 매일 22:30 UTC = 07:30 KST (한국 아침!)

사장님 요구 (2026-08-11):
"학습한 내용을 매일 아침에 간략하게 요점정리해서 브리핑해줘"

브리핑 내용:
1. 신 학습 결과 (오늘 예측 개수!)
2. 급등 top 5 심볼!
3. 급락 top 5 심볼!
4. 지속 하락 확정 심볼!
5. 신 제안 개수 (사장님 대기중!)
6. 사장님 활성 전략 상태!
7. 전날 실현 손익 (요약!)

발송:
- Telegram (사장님 알림!)
- Notification (대시보드 표시!)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from sqlalchemy import select, func

from app.agents.base import BaseAgent
from app.agents.orchestrator import EventType, get_event_bus

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


class DailyBriefingAgent(BaseAgent):
    TEAM = "strategy_suggestion"
    AGENT_NAME = "daily_briefing_agent"

    def execute(self, db) -> dict:
        """매일 아침 브리핑 = 학습 결과 요약!"""
        self.validate("DAILY_BRIEFING")

        from app.models.strategy_suggestion import StrategySuggestion
        from app.models.strategy_instance import StrategyInstance
        from app.core.strategy_status import TERMINAL_STATUSES

        # 오늘 KST 아침 = UTC 기준 어제 오후 시작!
        now_utc = datetime.now(timezone.utc)
        today_kst = now_utc.astimezone(KST).date()
        # UTC 06:00 이후 = 오늘 학습!
        _today_start_utc = datetime.combine(
            today_kst, datetime.min.time(),
        ).replace(tzinfo=KST).astimezone(timezone.utc)

        # 1. 오늘 신 제안 (PENDING!)
        pending = db.execute(
            select(StrategySuggestion)
            .where(StrategySuggestion.status == "PENDING")
            .where(StrategySuggestion.created_at >= _today_start_utc)
            .order_by(StrategySuggestion.confidence_score.desc())
        ).scalars().all()

        # 2. 급등/급락 요약!
        pumps = [s for s in pending if s.suggestion_type == "pump_end"]
        dumps = [s for s in pending if s.suggestion_type == "dump_continuation"]
        top_pumps = pumps[:5]
        top_dumps = dumps[:5]

        # 3. 지속 하락 확정!
        confirmed_dumps = [
            s for s in dumps
            if (s.strategy_config or {}).get("descent_confirmed")
        ]

        # 4. 활성 전략 상태!
        active_strategies = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.status.notin_(TERMINAL_STATUSES))
            .where(StrategyInstance.is_archived.is_(False))
        ).scalars().all()
        active_count = len(active_strategies)
        total_pnl_active = sum(
            Decimal(str(s.realized_pnl or 0)) + Decimal(str(s.unrealized_pnl or 0))
            for s in active_strategies
        )

        # 5. 전날 종료 전략 손익!
        _yesterday_start = _today_start_utc - timedelta(days=1)
        closed_yesterday = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.stopped_at >= _yesterday_start)
            .where(StrategyInstance.stopped_at < _today_start_utc)
        ).scalars().all()
        yesterday_pnl = sum(
            Decimal(str(s.realized_pnl or 0)) for s in closed_yesterday
        )
        yesterday_count = len(closed_yesterday)

        # 브리핑 텍스트 조립!
        _kst_str = now_utc.astimezone(KST).strftime("%Y-%m-%d %H:%M KST")

        _lines = [
            f"🌅 매일 아침 브리핑 - {_kst_str}",
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            "📊 오늘 학습 결과",
            f"  • 신 전략 제안: {len(pending)}건",
            f"  • 급등 감지: {len(pumps)} 심볼",
            f"  • 급락 감지: {len(dumps)} 심볼",
            f"  • 지속 하락 확정: {len(confirmed_dumps)} 심볼",
            "",
            "🐻 상위 급락 심볼 (Top 5):",
        ]
        for s in top_dumps:
            _cnf = f"{float(s.confidence_score or 0) * 100:.0f}%"
            _lines.append(
                f"  • {s.symbol} = 신뢰도 {_cnf}"
            )
        _lines.append("")
        _lines.append("🐂 상위 급등 심볼 (Top 5):")
        for s in top_pumps:
            _cnf = f"{float(s.confidence_score or 0) * 100:.0f}%"
            _lines.append(
                f"  • {s.symbol} = 신뢰도 {_cnf}"
            )
        _lines += [
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            "💼 사장님 활성 전략",
            f"  • 진행 중: {active_count}건",
            f"  • 미실현 PnL: {total_pnl_active:+.2f} USDT",
            "",
            "📈 전날 종료 요약",
            f"  • 종료 전략: {yesterday_count}건",
            f"  • 실현 손익: {yesterday_pnl:+.2f} USDT",
            "",
            "━━━━━━━━━━━━━━━━━━━━",
            "🎯 사장님 액션",
            f"  대시보드 → 「🎯 자동 전략 제안」 카드!",
            f"  = {len(pending)}건 대기 중 → 검토 후 실행!",
        ]

        briefing = "\n".join(_lines)

        # Telegram + Notification 발송!
        try:
            from app.services.notification_service import NotificationService
            NotificationService(db).send_system_alert(
                title=f"🌅 [매일 브리핑] {_kst_str}",
                body=briefing,
            )
        except Exception as e:
            logger.warning("[%s] 알림 실패: %s", self.AGENT_NAME, e)

        # 이벤트 발신!
        get_event_bus().publish(EventType.DAILY_LEARNING_DONE, {
            "briefing": True,
            "pending_count": len(pending),
            "active_strategies": active_count,
            "yesterday_pnl": str(yesterday_pnl),
        })

        logger.info(
            "[%s] 브리핑 발송! pending=%d, active=%d",
            self.AGENT_NAME, len(pending), active_count,
        )
        return {
            "briefing_sent": True,
            "pending_count": len(pending),
            "active_strategies": active_count,
            "yesterday_pnl": str(yesterday_pnl),
        }
