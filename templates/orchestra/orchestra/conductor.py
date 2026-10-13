"""🎩 Conductor — 총괄 지휘자 (원본 GrandOrchestrator).

    conductor = Conductor(rules=rules)
    conductor.register(ReportTeam(rules=rules))
    conductor.startup()
    conductor.dispatch(AppEvent.DAY_CLOSED, {"day": "2026-10-13"})
    conductor.health_check()           # 오류가 난 팀 · 정지된 팀 · 이벤트를 하나도 못 받은 팀
    conductor.emergency_stop_all("운영자 요청")

dispatch 는 규칙집에 `EVENT:<이벤트이름>` 행동으로 검사한 뒤 보낸다(규칙이 없으면 그냥 보낸다).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from orchestra.bus import EventBus, get_event_bus
from orchestra.events import SystemEvent, event_name
from orchestra.rules import Rulebook, RuleViolation
from orchestra.team import TeamLead

logger = logging.getLogger(__name__)


class Conductor:
    def __init__(self, *, bus: EventBus | None = None, rules: Rulebook | None = None) -> None:
        self.bus = bus or get_event_bus()
        self.rules = rules
        self.teams: dict[str, TeamLead] = {}
        self.started_at: datetime | None = None
        self.stopped = False
        self.bus.subscribe(SystemEvent.EMERGENCY_STOP_ALL, self._on_emergency_stop)

    def register(self, team: TeamLead) -> TeamLead:
        if team.TEAM in self.teams:
            raise ValueError(f"team {team.TEAM!r} already registered")
        if team.bus is not self.bus:
            raise ValueError(f"team {team.TEAM!r} uses a different bus")
        self.teams[team.TEAM] = team
        return team

    def startup(self) -> None:
        self.started_at = datetime.now(timezone.utc)
        self.stopped = False
        self.bus.publish(SystemEvent.SYSTEM_STARTED, {"at": self.started_at.isoformat(), "teams": list(self.teams)})

    def shutdown(self) -> None:
        self.bus.publish(SystemEvent.SYSTEM_STOPPING, {"teams": list(self.teams)})

    def dispatch(self, event: str | Enum, data: dict[str, Any] | None = None) -> int:
        name = event_name(event)
        if self.stopped and name != SystemEvent.EMERGENCY_STOP_ALL.value:
            logger.warning("[Conductor] 정지 중 — %s 보내지 않음", name)
            return 0
        if self.rules is not None:
            try:
                self.rules.check(f"EVENT:{name}", data)
            except RuleViolation as v:
                self.bus.publish(SystemEvent.RULE_VIOLATED, {"rule": v.rule_id, "action": v.action, "reason": v.reason})
                raise
        return self.bus.publish(name, data)

    def _on_emergency_stop(self, event: str, data: dict) -> None:
        reason = str(data.get("reason") or "unknown")
        for name, team in self.teams.items():
            try:
                team.emergency_stop(reason)
            except Exception as e:  # noqa: BLE001
                logger.error("[Conductor] %s 정지 실패: %s", name, e)
        self.stopped = True

    def emergency_stop_all(self, reason: str) -> None:
        self.bus.publish(SystemEvent.EMERGENCY_STOP_ALL, {"reason": reason})

    def resume_all(self) -> None:
        for team in self.teams.values():
            team.resume()
        self.stopped = False

    def health_check(self) -> dict[str, Any]:
        """원본 orchestra_health_worker 의 뼈대 — 문제 팀을 골라 HEALTH_CHECK 이벤트로도 알린다."""
        problems = []
        for name, t in self.teams.items():
            s = t.status()
            if s["stopped"]:
                problems.append({"team": name, "issue": "stopped", "detail": s["stop_reason"]})
            if s["errors"]:
                problems.append({"team": name, "issue": "errors", "detail": f"{s['errors']}건 · {s['last_error']}"})
            if s["events"] and s["handled"] == 0 and s["errors"] == 0:
                problems.append({"team": name, "issue": "idle", "detail": "구독 이벤트를 아직 하나도 처리 안 함"})
        report = {"ok": not problems, "problems": problems, "teams": len(self.teams)}
        self.bus.publish(SystemEvent.HEALTH_CHECK, report)
        return report

    def status(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "stopped": self.stopped,
            "teams": {n: t.status() for n, t in self.teams.items()},
            "bus": self.bus.stats(),
            "rules": self.rules.summary() if self.rules else [],
        }
