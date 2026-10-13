"""🎼 Fix 449 — 오케스트라 팀에 범용 템플릿 개선 반영 (2026-10-13 사장님 「AGENT_TEAM_GUIDE 가져와 적용해줘」).

10/13 운영 로그(48h): 버스 이벤트 870여 건이 전부 「0 subscribers」 · 전략 제안 팀 리더가 51번 새로 만들어지며 구독이 쌓임.
"""
from __future__ import annotations

import logging

import pytest

from app.agents import constitution_validator as CV
from app.agents.orchestrator import EventType, get_event_bus
from app.agents.orchestrator import team_lead_base as TLB
from app.agents.orchestrator.event_bus import EventBus


class _Lead(TLB.BaseTeamLead):
    TEAM = "t449"
    AGENT_NAME = "t449_lead"
    HANDLED_EVENTS = [EventType.EMERGENCY_STOP_ALL, EventType.WATCHLIST_UPDATED]

    def __init__(self):
        self.got = []
        super().__init__()

    def handle_event(self, event, data):
        self.got.append(event)

    def emergency_stop(self, reason):          # 운영 팀들처럼 super() 를 부르지 않는 덮어쓰기
        pass

    @TLB.stoppable
    def run_job(self):
        return {"done": True}


@pytest.fixture(autouse=True)
def _clean():
    get_event_bus().clear()
    TLB.resume_team()
    yield
    get_event_bus().clear()
    TLB.resume_team()


def test_keyed_subscribe_replaces_instead_of_accumulating():
    bus = get_event_bus()
    for _ in range(5):                            # 스케줄마다 팀 리더를 새로 만든다
        _Lead()
    assert bus.get_stats()["subscribers_per_event"][EventType.WATCHLIST_UPDATED.value] == 1
    last = _Lead()
    assert bus.publish(EventType.WATCHLIST_UPDATED, {"count": 1}) == 1
    assert last.got == [EventType.WATCHLIST_UPDATED]


def test_unkeyed_subscribe_still_dedups_same_handler():
    bus = EventBus()
    h = lambda e, d: None  # noqa: E731
    bus.subscribe(EventType.SYSTEM_STARTED, h)
    bus.subscribe(EventType.SYSTEM_STARTED, h)
    assert bus.get_stats()["subscribers_per_event"]["system.started"] == 1
    bus.unsubscribe(EventType.SYSTEM_STARTED, h)
    assert bus.publish(EventType.SYSTEM_STARTED) == 0


def test_zero_subscriber_publish_is_debug_and_recorded(caplog):
    bus = EventBus()
    with caplog.at_level(logging.INFO, logger="app.agents.orchestrator.event_bus"):
        assert bus.publish(EventType.ORCHESTRA_HEALTH_CHECK, {"x": 1}) == 0
    assert not [r for r in caplog.records if "subscribers" in r.getMessage()]
    st = bus.get_stats()
    assert st["recent"][-1][1:] == ("orchestra.health_check", 0)
    bus.subscribe(EventType.ORCHESTRA_HEALTH_CHECK, lambda e, d: 1 / 0)
    bus.publish(EventType.ORCHESTRA_HEALTH_CHECK)
    assert bus.get_stats()["handler_failures"] == {"orchestra.health_check": 1}


def test_emergency_stop_really_stops_even_with_override_then_resume():
    lead = _Lead()
    get_event_bus().publish(EventType.EMERGENCY_STOP_ALL, {"reason": "테스트"})
    assert TLB.stopped_reason("t449") == "테스트"
    assert lead.run_job() == {"skipped": "stopped", "reason": "테스트"}
    fresh = _Lead()                                  # 새 팀 리더도 정지 상태를 본다 (프로세스 단위)
    assert fresh.is_stopped() and fresh.report_status()["stopped"] == "테스트"
    get_event_bus().publish(EventType.WATCHLIST_UPDATED)
    assert fresh.got == [] and fresh.report_status()["skipped_while_stopped"] == 1
    assert TLB.resume_team("t449") == ["t449"]
    assert fresh.run_job() == {"done": True}


def test_constitution_register_check_blocks_and_default_unchanged():
    v = CV.ConstitutionValidator({})
    assert v.check("ANY_ACTION_449") is True                      # 등록 0개 = 예전과 같음
    CV.register_check("X449", ["ACT449"], lambda a, c: None if c.get("ok") else "not ok")
    CV.register_check("Y449", ["ACT449"], lambda a, c: 1 / 0, fail_open=True)
    try:
        assert v.check("ACT449", {"ok": True}) is True
        with pytest.raises(CV.ConstitutionViolationError):
            v.check("ACT449", {"ok": False})
        with pytest.raises(ValueError):
            CV.register_check("X449", ["ACT449"], lambda a, c: None)
        assert CV.registered_checks()["ACT449"] == ["X449", "Y449"]
    finally:
        CV._CHECKS.pop("ACT449", None)


def test_active_team_runs_are_stoppable():
    import pathlib
    root = pathlib.Path(CV.__file__).resolve().parent
    for rel, n in (("learning_team/team_lead.py", 1), ("chart_pattern_learning_team/team_lead.py", 1),
                   ("strategy_suggestion_team/team_lead.py", 4)):
        src = (root / rel).read_text(encoding="utf-8")
        assert src.count("@stoppable") == n, rel
