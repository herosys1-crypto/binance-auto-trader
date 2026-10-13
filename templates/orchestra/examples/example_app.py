"""예시 — 팀 2개(수집 팀 → 보고 팀) + 감사 팀(모든 이벤트 기록) + 규칙 1개.

실행:  cd templates/orchestra && python -m examples.example_app
"""
from __future__ import annotations

import logging
from enum import Enum

from orchestra import Agent, Conductor, Rulebook, SystemEvent, TeamLead, reset_event_bus


class AppEvent(str, Enum):               # 프로젝트 이벤트 = 한 곳에서만 정의
    DAY_CLOSED = "day.closed"
    DATA_COLLECTED = "data.collected"
    REPORT_READY = "report.ready"


rules = Rulebook()


@rules.rule("R01", "보고서에는 데이터가 1건 이상 있어야 한다", actions=["WRITE_REPORT"])
def has_rows(action, ctx):
    return None if ctx.get("rows", 0) > 0 else f"rows={ctx.get('rows')}"


# ── 수집 팀 ──
class Collector(Agent):
    TEAM, NAME = "collect", "collector"

    def execute(self, data):
        return {"day": data["day"], "rows": 42}


class CollectTeam(TeamLead):
    TEAM = "collect"
    AGENTS = [Collector]
    HANDLED_EVENTS = [AppEvent.DAY_CLOSED]

    def handle_event(self, event, data):
        self.publish(AppEvent.DATA_COLLECTED, self.agent(Collector).run(data))


# ── 보고 팀 ──
class ReportWriter(Agent):
    TEAM, NAME, ACTION = "report", "report_writer", "WRITE_REPORT"

    def execute(self, data):
        return {"day": data["day"], "summary": f"{data['rows']}건 처리"}


class ReportTeam(TeamLead):
    TEAM = "report"
    AGENTS = [ReportWriter]
    HANDLED_EVENTS = [AppEvent.DATA_COLLECTED]

    def handle_event(self, event, data):
        self.publish(AppEvent.REPORT_READY, self.agent(ReportWriter).run(data))


# ── 감사 팀 (모든 이벤트) ──
class AuditTeam(TeamLead):
    TEAM = "audit"
    HANDLED_EVENTS = ["*"]

    def __init__(self, **kw):
        self.log: list[str] = []
        super().__init__(**kw)

    def handle_event(self, event, data):
        self.log.append(event)


def build() -> tuple[Conductor, AuditTeam]:
    bus = reset_event_bus()
    c = Conductor(bus=bus, rules=rules)
    for t in (CollectTeam(bus=bus, rules=rules), ReportTeam(bus=bus, rules=rules)):
        c.register(t)
    audit = c.register(AuditTeam(bus=bus, rules=rules))
    return c, audit


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    c, audit = build()
    c.startup()
    c.dispatch(AppEvent.DAY_CLOSED, {"day": "2026-10-13"})
    print("이벤트 흐름:", " → ".join(audit.log))
    print("진단:", c.health_check())
    c.emergency_stop_all("예시 종료")
    print("정지 뒤 보냄:", c.dispatch(AppEvent.DAY_CLOSED, {"day": "2026-10-14"}), "팀")


if __name__ == "__main__":
    main()
    _ = SystemEvent  # 공용 이벤트도 같은 패키지에서 가져온다
