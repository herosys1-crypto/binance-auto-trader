"""👤 BaseTeamLead = 각 팀 리더 기반 클래스!

Team Lead 역할:
- 팀 내 에이전트 관리!
- 이벤트 수신 → 담당 에이전트 배정!
- 팀 지표 = Orchestrator 리포트!
- Kill-switch 처리!

각 팀 = 이 클래스 상속!

예:
    class EntryTeamLead(BaseTeamLead):
        TEAM = "entry"
        AGENTS = [StageTriggerAgent, RetryReentryAgent, ...]
        HANDLED_EVENTS = [EventType.STRATEGY_CREATED, ...]

        def handle_event(self, event, data):
            if event == EventType.STRATEGY_CREATED:
                self.agents[0].execute(data)
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.orchestrator.event_bus import EventBus, get_event_bus
from app.agents.orchestrator.event_types import EventType

logger = logging.getLogger(__name__)


class BaseTeamLead(BaseAgent):
    """각 팀의 관리자!"""
    TEAM: str = "unknown"
    AGENT_NAME: str = "team_lead"
    AGENTS: list[type] = []           # 소속 에이전트 클래스 리스트!
    HANDLED_EVENTS: list[EventType] = []  # 처리 이벤트!

    def __init__(self):
        super().__init__()
        # 소속 에이전트 인스턴스화!
        self._agent_classes = self.AGENTS
        self._agent_instances: dict[str, BaseAgent] = {}
        # EventBus 자동 구독!
        self.event_bus: EventBus = get_event_bus()
        self._subscribe_events()
        # 통계!
        self._events_handled = 0
        self._errors = 0

    def _subscribe_events(self) -> None:
        """HANDLED_EVENTS = 자동 구독!"""
        for event in self.HANDLED_EVENTS:
            self.event_bus.subscribe(event, self._on_event)
        if self.HANDLED_EVENTS:
            logger.info(
                "[%s Lead] %d 이벤트 구독!",
                self.TEAM, len(self.HANDLED_EVENTS),
            )

    def _on_event(self, event: EventType, data: dict) -> None:
        """이벤트 수신 → handle_event 호출!"""
        try:
            self.handle_event(event, data)
            self._events_handled += 1
        except Exception as e:
            self._errors += 1
            logger.error(
                "[%s Lead] handle_event 실패 event=%s: %s",
                self.TEAM, event.value, e,
            )

    def handle_event(self, event: EventType, data: dict) -> None:
        """이벤트 처리 = 서브클래스에서 구현!"""
        raise NotImplementedError(
            f"{self.__class__.__name__}.handle_event() = 서브클래스에서 구현 필수!"
        )

    def get_agent(self, agent_class: type) -> BaseAgent:
        """소속 에이전트 인스턴스 반환 (lazy!)."""
        key = agent_class.__name__
        if key not in self._agent_instances:
            self._agent_instances[key] = agent_class()
        return self._agent_instances[key]

    def publish(self, event: EventType, data: dict | None = None) -> int:
        """팀에서 이벤트 발신!"""
        return self.event_bus.publish(event, data or {})

    def report_status(self) -> dict[str, Any]:
        """팀 상태 = Orchestrator 리포트!"""
        return {
            "team": self.TEAM,
            "agents_registered": len(self._agent_classes),
            "agents_active": len(self._agent_instances),
            "events_handled": self._events_handled,
            "errors": self._errors,
        }

    def emergency_stop(self, reason: str) -> None:
        """🚨 팀 전체 정지 (Kill-switch!)."""
        logger.warning(
            "[%s Lead] 🚨 EMERGENCY STOP! reason=%s",
            self.TEAM, reason,
        )
        # 서브클래스에서 = 실제 정지 로직 구현!

    def execute(self):
        """Team Lead = 이벤트 기반! execute 필요 X!"""
        pass
