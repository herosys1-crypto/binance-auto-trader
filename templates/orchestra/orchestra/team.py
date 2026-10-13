"""👤 TeamLead — 팀 하나의 관리자. 이벤트를 받아 소속 에이전트에게 일을 나눈다.

    class ReportTeam(TeamLead):
        TEAM = "report"
        AGENTS = [ReportWriter, ReportMailer]
        HANDLED_EVENTS = [AppEvent.DAY_CLOSED]

        def handle_event(self, event, data):
            result = self.agent(ReportWriter).run(data)
            self.publish(AppEvent.REPORT_READY, result)

정지(emergency_stop) 뒤에는 이벤트를 받아도 처리하지 않는다. 다시 켜려면 resume().
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any

from orchestra.agent import Agent
from orchestra.bus import EventBus, get_event_bus
from orchestra.events import event_name
from orchestra.rules import Rulebook

logger = logging.getLogger(__name__)


class TeamLead:
    TEAM: str = "unknown"
    AGENTS: list[type[Agent]] = []
    HANDLED_EVENTS: list[str | Enum] = []

    def __init__(self, *, bus: EventBus | None = None, rules: Rulebook | None = None) -> None:
        self.bus = bus or get_event_bus()
        self.rules = rules
        self._agents: dict[str, Agent] = {}
        self.stopped = False
        self.stop_reason: str | None = None
        self.handled = 0
        self.errors = 0
        self.last_error: str | None = None
        self.skipped_while_stopped = 0
        for ev in self.HANDLED_EVENTS:
            self.bus.subscribe(ev, self._on_event)

    def _on_event(self, event: str, data: dict) -> None:
        if self.stopped:
            self.skipped_while_stopped += 1
            return
        try:
            self.handle_event(event, data)
            self.handled += 1
        except Exception as e:  # noqa: BLE001 — 버스로 퍼지지 않게 여기서 센다
            self.errors += 1
            self.last_error = f"{event}: {type(e).__name__}: {e}"
            logger.error("[%s] %s 처리 실패: %s", self.TEAM, event, e)

    def handle_event(self, event: str, data: dict) -> None:
        raise NotImplementedError(f"{type(self).__name__}.handle_event() 를 구현하라")

    def agent(self, cls: type[Agent]) -> Agent:
        """소속 에이전트 (처음 부를 때 만든다). AGENTS 에 없는 클래스는 거부 — 팀 경계를 지킨다."""
        if cls not in self.AGENTS:
            raise ValueError(f"{cls.__name__} 는 {self.TEAM} 팀 소속이 아니다")
        key = cls.__name__
        if key not in self._agents:
            self._agents[key] = cls(self.rules)
        return self._agents[key]

    def publish(self, event: str | Enum, data: dict[str, Any] | None = None) -> int:
        return self.bus.publish(event, {"_from": self.TEAM, **(data or {})})

    def emergency_stop(self, reason: str) -> None:
        self.stopped, self.stop_reason = True, reason
        logger.warning("[%s] 🚨 정지: %s", self.TEAM, reason)
        self.on_stop(reason)

    def on_stop(self, reason: str) -> None:
        """팀별 정지 동작(진행 중 작업 취소 등) — 필요하면 덮어쓴다."""

    def resume(self) -> None:
        self.stopped, self.stop_reason = False, None

    def status(self) -> dict[str, Any]:
        return {
            "team": self.TEAM, "stopped": self.stopped, "stop_reason": self.stop_reason,
            "events": [event_name(e) for e in self.HANDLED_EVENTS],
            "handled": self.handled, "errors": self.errors, "last_error": self.last_error,
            "skipped_while_stopped": self.skipped_while_stopped,
            "agents": {k: a.status() for k, a in self._agents.items()},
            "agents_registered": [c.__name__ for c in self.AGENTS],
        }
