"""orchestra 템플릿 테스트 — cd templates/orchestra && python -m pytest -q"""
from __future__ import annotations

import pytest

from examples.example_app import AppEvent, ReportWriter, build, rules
from orchestra import Agent, Conductor, EventBus, Rulebook, RuleViolation, SystemEvent, TeamLead, get_event_bus, reset_event_bus


def test_bus_isolates_failures_and_wildcard():
    bus = EventBus()
    got = []
    bus.subscribe("a", lambda e, d: (_ for _ in ()).throw(RuntimeError("x")))
    bus.subscribe("a", lambda e, d: got.append(("ok", e, d["n"])))
    bus.subscribe("*", lambda e, d: got.append(("all", e)))
    assert bus.publish("a", {"n": 1}) == 2               # 실패 1 · 성공 1 · 와일드카드 1 → 성공 2
    assert ("ok", "a", 1) in got and ("all", "a") in got
    s = bus.stats()
    assert s["published"] == {"a": 1} and s["failures"] == {"a": 1}
    with pytest.raises(ValueError):
        bus.publish("  ")


def test_enum_and_string_are_same_event():
    bus = EventBus()
    seen = []
    bus.subscribe(SystemEvent.SYSTEM_STARTED, lambda e, d: seen.append(e))
    bus.publish("system.started")
    assert seen == ["system.started"]


def test_singleton_and_reset():
    a = get_event_bus()
    assert get_event_bus() is a
    b = reset_event_bus()
    assert b is not a and get_event_bus() is b


def test_rulebook_fail_closed_and_open():
    rb = Rulebook()
    rb.add("R1", "양수", lambda a, c: None if c.get("x", 0) > 0 else "x<=0", actions=["DO"])
    rb.add("R2", "보조 · 오류 무시", lambda a, c: 1 / 0, actions=["DO"], fail_open=True)
    assert rb.check("DO", {"x": 1}) is True
    assert rb.check("OTHER", {"x": -1}) is True          # 관련 규칙 없음
    with pytest.raises(RuleViolation) as e:
        rb.check("DO", {"x": 0})
    assert e.value.rule_id == "R1"
    rb.add("R3", "오류 = 위반", lambda a, c: 1 / 0, actions=["*"])
    with pytest.raises(RuleViolation, match="검사 오류"):
        rb.check("ANY")
    with pytest.raises(ValueError):
        rb.add("R1", "중복", lambda a, c: None)


def test_example_flow_end_to_end():
    c, audit = build()
    c.startup()
    c.dispatch(AppEvent.DAY_CLOSED, {"day": "d"})
    assert audit.log == ["system.started", "day.closed", "data.collected", "report.ready"]
    st = c.status()
    assert st["teams"]["report"]["agents"]["ReportWriter"]["runs"] == 1
    assert c.health_check()["ok"] is True


def test_rule_violation_inside_team_is_counted_not_propagated():
    c, audit = build()
    c.dispatch(AppEvent.DATA_COLLECTED, {"day": "d", "rows": 0})      # R01 위반 → 보고 팀 오류 1
    rep = c.teams["report"].status()
    assert rep["errors"] == 1 and "RuleViolation" in rep["last_error"]
    assert rep["agents"]["ReportWriter"]["failures"] == 1
    h = c.health_check()
    assert not h["ok"] and any(p["team"] == "report" and p["issue"] == "errors" for p in h["problems"])


def test_emergency_stop_blocks_then_resume():
    c, audit = build()
    c.emergency_stop_all("테스트")
    assert c.stopped and all(t.stopped for t in c.teams.values())
    assert c.dispatch(AppEvent.DAY_CLOSED, {"day": "d"}) == 0
    c.bus.publish(AppEvent.DAY_CLOSED, {"day": "d"})                 # 버스로 직접 보내도 팀은 처리 안 함
    assert c.teams["collect"].status()["skipped_while_stopped"] == 1
    c.resume_all()
    c.dispatch(AppEvent.DAY_CLOSED, {"day": "d"})
    assert c.teams["report"].status()["handled"] == 1


def test_team_boundary_and_registration_guards():
    bus = reset_event_bus()

    class Other(Agent):
        def execute(self, data):
            return 1

    class T(TeamLead):
        TEAM = "t"
        AGENTS = [ReportWriter]

    t = T(bus=bus)
    with pytest.raises(ValueError):
        t.agent(Other)
    c = Conductor(bus=bus)
    c.register(t)
    with pytest.raises(ValueError):
        c.register(T(bus=bus))                                    # 같은 이름
    with pytest.raises(ValueError):
        c.register(type("U", (TeamLead,), {"TEAM": "u"})(bus=EventBus()))   # 다른 버스


def test_dispatch_rule_on_event():
    bus = reset_event_bus()
    rb = Rulebook()
    rb.add("E1", "주말 마감 금지", lambda a, c: "weekend" if c.get("weekend") else None, actions=["EVENT:day.closed"])
    c = Conductor(bus=bus, rules=rb)
    seen = []
    bus.subscribe(SystemEvent.RULE_VIOLATED, lambda e, d: seen.append(d["rule"]))
    with pytest.raises(RuleViolation):
        c.dispatch(AppEvent.DAY_CLOSED, {"weekend": True})
    assert seen == ["E1"]
    assert rules.summary()[0]["id"] == "R01"
