"""🧾 Fix 457 — 판정·중간 점검 보고서 자동 실행 (사장님 10/14 「판정 보고서 자동 실행 진행해줘」)."""
from __future__ import annotations

import pathlib
from datetime import datetime, timezone

import pytest

from app.workers import verdict_report_worker as V

APP = pathlib.Path(V.__file__).resolve().parents[1]


class _R:
    def __init__(self):
        self.kv = {}

    def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True

    def setex(self, k, ttl, v):
        self.kv[k] = v

    def get(self, k):
        return self.kv.get(k)

    def delete(self, k):
        self.kv.pop(k, None)

    def scan_iter(self, pat, count=None):
        return [k for k in self.kv if k.startswith("verdict:report:")]


class _DB:
    def __init__(self, value=None):
        self.value = value

    def get(self, model, key):
        class Row:
            pass
        if self.value is None:
            return None
        r = Row()
        r.value = self.value
        return r


def test_parse_schedule():
    assert V.parse_schedule(None) == {"2026-10-17": "midcheck", "2026-10-25": "verdict"}
    assert V.parse_schedule("off") == {}
    assert V.parse_schedule("2026-10-20=verdict, bad=verdict, 2026-10-21=nope,2026-10-22") == {"2026-10-20": "verdict"}


def test_runs_once_on_scheduled_day(monkeypatch):
    sent = []

    class _NS:
        def __init__(self, db):
            pass

        def send_system_alert(self, title, body):
            sent.append((title, body))
            return 1
    monkeypatch.setattr("app.services.notification_service.NotificationService", _NS)
    r = _R()
    now = datetime(2026, 10, 25, 1, 20, tzinfo=timezone.utc)       # KST 10:20
    rep = "| rf_x · 필터 안 | 40 | +1 | … | ✅ 통과 | 기준 |\n| y | 3 | … | ⏳ 보류 | 표본 |\n→ ⏳ 보류 — 시장폭"
    out = V.run_verdict_report_once(now=now, redis=r, db=_DB(), runner=lambda k: rep)
    assert out["ran"] and out["kind"] == "verdict" and out["sent"]
    assert r.get("verdict:report:2026-10-25:verdict") == rep
    assert "✅ 통과 1" in sent[0][1] and "rf_x · 필터 안" in sent[0][1] and "대표님 승인" in sent[0][1]
    again = V.run_verdict_report_once(now=now, redis=r, db=_DB(), runner=lambda k: 1 / 0)
    assert again["ran"] is False and len(sent) == 1                  # 같은 날 두 번 안 돈다


def test_not_scheduled_day_and_off():
    r = _R()
    out = V.run_verdict_report_once(now=datetime(2026, 10, 20, 1, 20, tzinfo=timezone.utc), redis=r, db=_DB(), runner=lambda k: "x")
    assert out["kind"] is None and not out["ran"]
    off = V.run_verdict_report_once(now=datetime(2026, 10, 25, 1, 20, tzinfo=timezone.utc), redis=r, db=_DB("off"), runner=lambda k: "x")
    assert off["kind"] is None


def test_failure_clears_done_mark_for_retry():
    r = _R()
    now = datetime(2026, 10, 17, 1, 20, tzinfo=timezone.utc)
    with pytest.raises(ZeroDivisionError):
        V.run_verdict_report_once(now=now, redis=r, db=_DB(), runner=lambda k: 1 / 0)
    assert "verdict:done:2026-10-17:midcheck" not in r.kv


def test_summaries():
    mid = "요약: ✅ 19 · ⚠️ 5 · — 10\n| emapb_long · 필터 안 | 1 | 1 | 1 | 1 | 5 | 3 | ⚠️ 부족 예상 |\n끝난 32건 평균 +10.94% · 이긴 비율 78%"
    s = V.summarize("midcheck", mid)
    assert "요약: ✅ 19" in s and "emapb_long" in s and "+10.94" in s
    v = V.summarize("verdict", "| a | 0 | — | ❌ 기각 | x |\n통과한 전략 없음 → 단계 0 유지")
    assert "❌ 기각 1" in v and "통과 없음" in v


def test_latest_report_and_wiring():
    r = _R()
    r.kv["verdict:report:2026-10-17:midcheck"] = "m"
    r.kv["verdict:report:2026-10-25:verdict"] = "v"
    assert V.latest_report(r)["kind"] == "verdict"
    assert V.latest_report(r, kind="midcheck")["report"] == "m"
    assert V.latest_report(r, day="2026-10-01") is None
    sch = (APP / "workers" / "scheduler_runner.py").read_text(encoding="utf-8")
    assert 'id="verdict_report"' in sch and "CronTrigger(hour=10, minute=20)" in sch
    api = (APP / "api" / "v1" / "strategy_council.py").read_text(encoding="utf-8")
    assert '@router.get("/verdict-report")' in api
    for name in V.SCRIPTS.values():
        assert (V._SCRIPT_DIR / name).exists()
