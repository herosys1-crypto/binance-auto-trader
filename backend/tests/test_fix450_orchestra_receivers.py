"""📥 Fix 450 — 오케스트라 메시지 반응 (사장님 10/14 「전부 A로 진행해줘」, docs/spec/ORCHESTRA_EVENT_WIRING_2026-10-14.md)."""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from app.agents.orchestrator import EventType
from app.agents.orchestrator import event_bus as EB
from app.agents.orchestrator import receivers as RCV
from app.agents.orchestrator import team_lead_base as TLB

APP = pathlib.Path(RCV.__file__).resolve().parents[2]


class _R:
    def __init__(self):
        self.kv, self.h = {}, {}

    def setex(self, k, ttl, v):
        self.kv[k] = v

    def get(self, k):
        return self.kv.get(k)

    def hset(self, k, f, v):
        self.h.setdefault(k, {})[f] = v

    def hgetall(self, k):
        return dict(self.h.get(k, {}))

    def expire(self, k, ttl):
        pass

    def hdel(self, k, f):
        self.h.get(k, {}).pop(f, None)

    def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True


@pytest.fixture
def fake_redis(monkeypatch):
    r = _R()
    monkeypatch.setattr(RCV, "_redis", lambda: r)
    return r


def test_receivers_installed_once_on_new_bus(fake_redis, monkeypatch):
    monkeypatch.setattr(EB, "_bus_instance", None)
    bus = EB.get_event_bus()
    RCV.install(bus)                                         # 두 번째 설치 = 교체 (누적 없음)
    st = bus.get_stats()["subscribers_per_event"]
    assert st["orchestra.health_check"] == 1 and st["learning.daily_done"] == 1 and st["pattern_learning.done"] == 1
    bus.publish(EventType.ORCHESTRA_HEALTH_CHECK, {"checks": 4, "healthy": 4, "fixes": 0, "obj": object()})
    h = RCV.health_last()
    assert h["checks"] == 4 and "obj" not in h and h["at"]
    bus.publish(EventType.PATTERN_LEARNING_DONE, {"samples": 9})
    bus.publish(EventType.DAILY_LEARNING_DONE, {"team": "chart_pattern_learning"})
    bus.publish(EventType.DAILY_LEARNING_DONE, {"_from": "learning"})
    assert set(RCV.learning_last()) == {"pattern_learning", "chart_pattern_learning", "learning"}
    monkeypatch.setattr(EB, "_bus_instance", None)


def test_redis_failure_is_silent(monkeypatch):
    monkeypatch.setattr(RCV, "_redis", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    RCV.on_health(EventType.ORCHESTRA_HEALTH_CHECK, {"checks": 1})
    RCV.on_learning(EventType.DAILY_LEARNING_DONE, {"team": "x"})
    assert RCV.health_last() is None and RCV.learning_last() == {}


def test_stale_learning_threshold():
    now = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
    rec = {"a": {"at": (now - timedelta(hours=27)).isoformat()}, "b": {"at": (now - timedelta(hours=2)).isoformat()},
           "c": {"at": "broken"}}
    assert RCV.stale_learning(rec, now=now) == [("a", 27.0)]


def test_health_worker_learning_record_alert_dedup(fake_redis, monkeypatch):
    from app.workers import orchestra_health_worker as W
    now = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
    fake_redis.h[RCV.LEARNING_KEY] = {"learning": json.dumps({"at": (now - timedelta(hours=30)).isoformat()}),
                                      "pattern_learning": json.dumps({"at": now.isoformat()})}
    W._LAST_STALE_ALERT.clear()
    checks, alerts = [], []
    W._check_learning_record(checks, alerts, now=now)
    assert {c["team"]: c["status"] for c in checks} == {"learning_record:learning": "STALE", "learning_record:pattern_learning": "OK"}
    assert len(alerts) == 1 and "learning" in alerts[0]
    alerts2 = []
    W._check_learning_record([], alerts2, now=now + timedelta(hours=1))      # 12시간 안 = 다시 안 알림
    assert alerts2 == []
    alerts3 = []
    fake_redis.kv.pop("orchestra:learning:alerted:learning", None)     # Redis 12시간 만료 흉내
    W._check_learning_record([], alerts3, now=now + timedelta(hours=13))
    assert len(alerts3) == 1
    src = (APP / "workers" / "orchestra_health_worker.py").read_text(encoding="utf-8")
    assert "_check_learning_record(checks, alerts)" in src


def test_team_publish_adds_from():
    bus = EB.get_event_bus()
    bus.clear()
    got = []
    bus.subscribe(EventType.SUGGESTION_CREATED, lambda e, d: got.append(d))

    class L(TLB.BaseTeamLead):
        TEAM = "t450"

        def handle_event(self, e, d):
            pass
    L().publish(EventType.SUGGESTION_CREATED, {"x": 1})
    L().publish(EventType.SUGGESTION_CREATED, {"_from": "keep"})
    assert got == [{"_from": "t450", "x": 1}, {"_from": "keep"}]
    bus.clear()


def test_auto_execute_skips_when_halted(monkeypatch):
    from app.agents.strategy_suggestion_team.team_lead import StrategySuggestionTeamLead
    from app.services import auto_trading_halt as AH
    monkeypatch.setattr(AH, "FORCE_HALT", True)
    assert StrategySuggestionTeamLead().run_auto_execute(db=None) == {"skipped": "auto_trading_halt"}
    monkeypatch.setattr(AH, "FORCE_HALT", False)
    called = []
    from app.agents.strategy_suggestion_team import auto_manual_executor as AME
    monkeypatch.setattr(AME.AutoManualExecutor, "execute_auto_batch", lambda self, db: called.append(1) or {"ok": 1})
    assert StrategySuggestionTeamLead().run_auto_execute(db=None) == {"ok": 1} and called == [1]


def test_wiring_watchlist_briefing_api_ui():
    wl = (APP / "workers" / "realtime_watchlist_worker.py").read_text(encoding="utf-8")
    assert "WATCHLIST_UPDATED" not in wl.split("Fix 450")[0][-2000:] and "get_event_bus().publish(EventType.WATCHLIST_UPDATED" not in wl
    br = (APP / "agents" / "strategy_suggestion_team" / "daily_briefing_agent.py").read_text(encoding="utf-8")
    assert "now_utc - timedelta(hours=24)" in br and "created_at >= _today_start_utc" not in br
    api = (APP / "api" / "v1" / "orchestra_status.py").read_text(encoding="utf-8")
    assert "RCV.health_last()" in api and 'teams[f"learning:{t_}"]' in api
    ui = (APP / "static" / "realtime-monitor.html").read_text(encoding="utf-8")
    assert "if (t.detail)" in ui


def test_review_fixes_briefing_skip_prune_alert_persist(fake_redis):
    RCV.on_learning(EventType.DAILY_LEARNING_DONE, {"team": "strategy_suggestion:briefing", "briefing": True})
    assert RCV.learning_last() == {}                                    # 브리핑 = 학습 아님
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    fake_redis.h[RCV.LEARNING_KEY] = {"gone_team": json.dumps({"at": old}), "bad": "x"}
    RCV.on_learning(EventType.DAILY_LEARNING_DONE, {"team": "strategy_suggestion"})
    assert set(RCV.learning_last()) == {"strategy_suggestion"}          # 7일 지난 칸·깨진 칸 지움
    assert RCV.alert_once("t", 3600) is True and RCV.alert_once("t", 3600) is False   # 재시작해도 Redis 가 기억


def test_health_event_counts_exclude_learning_record(monkeypatch):
    from app.workers import orchestra_health_worker as W
    got = []
    bus = EB.get_event_bus()
    bus.clear()
    bus.subscribe(EventType.ORCHESTRA_HEALTH_CHECK, lambda e, d: got.append(d))
    W._publish_health_event([{"team": "a", "status": "OK"}, {"team": "learning_record:x", "status": "STALE"}], [])
    assert got[0]["checks"] == 1 and got[0]["healthy"] == 1 and got[0]["learning_stale"] == 1
    bus.clear()


def test_direct_publishers_name_their_team():
    for rel, team in (("agents/strategy_suggestion_team/pump_dump_predictor.py", '"team": "strategy_suggestion",'),
                      ("agents/strategy_suggestion_team/daily_briefing_agent.py", '"team": "strategy_suggestion:briefing",')):
        assert team in (APP / rel).read_text(encoding="utf-8")
