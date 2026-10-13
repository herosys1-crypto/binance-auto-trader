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
import threading
from typing import Any

from app.agents.base import BaseAgent
from app.agents.orchestrator.event_bus import EventBus, get_event_bus
from app.agents.orchestrator.event_types import EventType

logger = logging.getLogger(__name__)

# 🎼 Fix 449: 정지 상태는 **프로세스 단위·팀 이름별** — 팀 리더 인스턴스는 스케줄마다 새로 만들어지므로 인스턴스에 두면 사라진다.
_STOPPED: dict[str, str] = {}
_STOP_LOCK = threading.Lock()


def stopped_reason(team: str) -> str | None:
    with _STOP_LOCK:
        return _STOPPED.get(team)


def resume_team(team: str | None = None) -> list[str]:
    """정지 해제 (None = 전부). 풀린 팀 이름 목록."""
    with _STOP_LOCK:
        names = list(_STOPPED) if team is None else ([team] if team in _STOPPED else [])
        for n in names:
            _STOPPED.pop(n, None)
    for n in names:
        logger.warning("[%s Lead] ▶️ 정지 해제", n)
    return names


def stoppable(fn):
    """🎼 Fix 449: 팀 run_* 진입점 장식 — 팀이 정지 중이면 일을 하지 않고 {"skipped": "stopped", "reason": ...} 를 돌려준다."""
    import functools

    @functools.wraps(fn)
    def wrapper(self, *a, **kw):
        why = stopped_reason(self.TEAM)
        if why is not None:
            logger.warning("[%s Lead] ⏸ 정지 중 → %s 건너뜀 (%s)", self.TEAM, fn.__name__, why)
            return {"skipped": "stopped", "reason": why}
        return fn(self, *a, **kw)
    return wrapper


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
        self._skipped_while_stopped = 0

    def _subscribe_events(self) -> None:
        """HANDLED_EVENTS = 자동 구독!"""
        for event in self.HANDLED_EVENTS:
            # 🎼 Fix 449: 팀 이름 key → 새 팀 리더가 옛 인스턴스 구독을 교체 (누적 방지)
            self.event_bus.subscribe(event, self._on_event, key=f"team:{self.TEAM}")
        if self.HANDLED_EVENTS:
            logger.debug(
                "[%s Lead] %d 이벤트 구독!",
                self.TEAM, len(self.HANDLED_EVENTS),
            )

    def _on_event(self, event: EventType, data: dict) -> None:
        """이벤트 수신 → handle_event 호출!"""
        if event == EventType.EMERGENCY_STOP_ALL:
            # 🎼 Fix 449: 서브클래스가 emergency_stop 을 덮어써도(super 미호출) 정지 표시는 여기서 확실히
            with _STOP_LOCK:
                _STOPPED[self.TEAM] = str((data or {}).get("reason") or "EMERGENCY_STOP_ALL")
        elif self.is_stopped():
            self._skipped_while_stopped += 1
            return
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
            "stopped": stopped_reason(self.TEAM),                    # 🎼 Fix 449
            "skipped_while_stopped": self._skipped_while_stopped,
        }

    def is_stopped(self) -> bool:
        """🎼 Fix 449: 정지 중이면 팀의 run_* 진입점이 일을 건너뛴다."""
        return stopped_reason(self.TEAM) is not None

    def emergency_stop(self, reason: str) -> None:
        """🚨 팀 전체 정지 (Kill-switch!)."""
        logger.warning(
            "[%s Lead] 🚨 EMERGENCY STOP! reason=%s",
            self.TEAM, reason,
        )
        with _STOP_LOCK:                                             # 🎼 Fix 449: 실제로 멈춘다 (run_* 가 건너뜀)
            if reason or self.TEAM not in _STOPPED:                  # 빈 사유로 앞선 사유를 덮지 않는다
                _STOPPED[self.TEAM] = reason or "emergency_stop"

    def execute(self):
        """Team Lead = 이벤트 기반! execute 필요 X!"""
        pass
