"""⏸ Fix 455 — 패턴 학습 「재료 없음」 표시 · 헛 재실행 중단 (2026-10-14).

실측: 결과 난 마지막 전략 제안 = 9/12 → 10/12 부터 no data · 감시 진단이 「지연」으로 24h 46번 헛 재실행.
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone

from app.workers import orchestra_health_worker as W
from app.workers import pattern_learning_worker as PL

APP = pathlib.Path(PL.__file__).resolve().parents[1]


class _R:
    def __init__(self):
        self.kv = {}

    def setex(self, k, ttl, v):
        self.kv[k] = v

    def get(self, k):
        return self.kv.get(k)


def test_no_data_state_roundtrip(monkeypatch):
    r = _R()
    monkeypatch.setattr("app.core.redis_client.get_redis_client", lambda: r)
    assert PL.no_data_state() is None
    r.kv[PL.NO_DATA_KEY] = json.dumps({"at": "x", "newest_outcome": "2026-09-12T22:15:04"})
    assert PL.no_data_state()["newest_outcome"].startswith("2026-09-12")


def test_no_data_state_redis_failure_is_none(monkeypatch):
    monkeypatch.setattr("app.core.redis_client.get_redis_client", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert PL.no_data_state() is None


def _insights(hours_old):
    return {"generated_at": (datetime.now(timezone.utc) - timedelta(hours=hours_old)).isoformat(), "total_samples": 1}


def test_health_skips_futile_rerun_when_no_data(monkeypatch):
    calls = []
    monkeypatch.setattr(PL, "get_learning_insights", lambda db: _insights(40))
    monkeypatch.setattr(PL, "run_pattern_learning", lambda: calls.append(1) or {"note": "no data"})
    monkeypatch.setattr(PL, "no_data_state", lambda: {"newest_outcome": "2026-09-12"})
    W._LAST_FIX_ATTEMPTS.clear()
    checks, fixes, alerts = [], [], []
    W._check_and_fix_learning(None, checks, fixes, alerts)
    assert checks[0]["status"] == "OK" and checks[0]["note"] == "no_data" and calls == [] and fixes == []


def test_health_still_reruns_when_really_stale(monkeypatch):
    calls = []
    monkeypatch.setattr(PL, "get_learning_insights", lambda db: _insights(40))
    monkeypatch.setattr(PL, "run_pattern_learning", lambda: calls.append(1) or {"ok": 1})
    monkeypatch.setattr(PL, "no_data_state", lambda: None)
    W._LAST_FIX_ATTEMPTS.clear()
    checks, fixes, alerts = [], [], []
    W._check_and_fix_learning(None, checks, fixes, alerts)
    assert checks[0]["status"] == "STALE" and calls == [1]


def test_wiring():
    pl = (APP / "workers" / "pattern_learning_worker.py").read_text(encoding="utf-8")
    assert "_mark_no_data(db)" in pl and pl.index("_mark_no_data(db)") < pl.index('return {"note": "no data"')
    sb = (APP / "workers" / "silent_bug_detector.py").read_text(encoding="utf-8")
    assert "no_data_state() is None" in sb
    api = (APP / "api" / "v1" / "orchestra_status.py").read_text(encoding="utf-8")
    assert "⏸ 재료 없음" in api
