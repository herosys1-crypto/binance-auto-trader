"""🎩 GrandOrchestrator = 최상위 총괄 지휘자!

사장님 요구 (2026-08-11):
"현재 개별 에이전트를 총괄지휘하는 지휘자가 있는지?"

역할:
- 전체 시스템 상태 관리!
- 13 팀 리더 관리!
- 이벤트 방송 (Event Bus!)
- 우선순위 결정!
- Kill-switch 총괄!
- 감사 (Audit!)

Usage:
    orchestrator = GrandOrchestrator()
    orchestrator.startup()
    # → 13 팀 = 모두 활성!
    # → 이벤트 버스 = 시작!

    orchestrator.emergency_stop_all("사장님 요청!")
    # → 모든 팀 = 정지!
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.agents.base import BaseAgent
from app.agents.orchestrator.event_bus import EventBus, get_event_bus
from app.agents.orchestrator.event_types import EventType

logger = logging.getLogger(__name__)


class GrandOrchestrator(BaseAgent):
    """최상위 총괄 지휘자!"""
    TEAM = "orchestrator"
    AGENT_NAME = "grand_orchestrator"

    def __init__(self):
        super().__init__()
        # 이벤트 버스!
        self.event_bus: EventBus = get_event_bus()
        # 13 팀 리더 (lazy 로드!)
        self._team_leads: dict[str, Any] = {}
        # 시스템 상태!
        self.started_at: datetime | None = None
        self.stopped = False
        # Kill-switch 이벤트 = 최우선 구독!
        self.event_bus.subscribe(
            EventType.EMERGENCY_STOP_ALL,
            self._on_emergency_stop,
        )

    def register_team(self, team_name: str, team_lead) -> None:
        """팀 리더 등록!"""
        self._team_leads[team_name] = team_lead
        logger.info("[Grand] 팀 등록: %s", team_name)

    def startup(self) -> None:
        """시스템 시작!"""
        self.started_at = datetime.now(timezone.utc)
        self.stopped = False
        logger.info("[Grand] 🎩 시스템 시작! %s", self.started_at.isoformat())
        self.event_bus.publish(
            EventType.SYSTEM_STARTED,
            {"timestamp": self.started_at.isoformat()},
        )

    def dispatch_event(self, event: EventType, data: dict | None = None) -> int:
        """이벤트 발신 (모든 구독 팀!)."""
        # 헌법 자동 검증!
        try:
            self.validate(f"EVENT_{event.name}")
        except Exception as e:
            logger.error("[Grand] 헌법 위반! %s", e)
            raise
        # 발신!
        return self.event_bus.publish(event, data or {})

    def _on_emergency_stop(self, event: EventType, data: dict) -> None:
        """🚨 Kill-switch = 모든 팀 정지!"""
        reason = data.get("reason", "사장님 결정!")
        logger.warning("[Grand] 🚨 EMERGENCY STOP ALL! reason=%s", reason)
        for name, lead in self._team_leads.items():
            try:
                lead.emergency_stop(reason)
            except Exception as e:
                logger.error("[Grand] 팀 %s 정지 실패: %s", name, e)
        self.stopped = True

    def emergency_stop_all(self, reason: str) -> None:
        """🚨 직접 호출로 = 전체 정지!"""
        self.dispatch_event(
            EventType.EMERGENCY_STOP_ALL,
            {"reason": reason},
        )

    def get_system_status(self) -> dict[str, Any]:
        """전체 시스템 상태 = 대시보드용!"""
        return {
            "orchestrator": {
                "started_at": self.started_at.isoformat() if self.started_at else None,
                "stopped": self.stopped,
            },
            "teams": {
                name: lead.report_status()
                for name, lead in self._team_leads.items()
            },
            "event_bus": self.event_bus.get_stats(),
            "memory": self.memory.summary(),
        }

    def execute(self):
        """Orchestrator = 이벤트 기반! execute 필요 X!"""
        pass
