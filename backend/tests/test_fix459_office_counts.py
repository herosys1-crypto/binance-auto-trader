"""🏢 Fix 459 — 사무실 화면 「최근 24시간 오류 n/실행 m」 · 「다음 실행」 · 일시 오류(blip) (사장님 10/15 「1번 2번 진행해줘」)."""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

from app.services import office_board as OB
from app.workers import scheduler_runner as SR

APP = pathlib.Path(OB.__file__).resolve().parents[1]
NOW = 1_800_000_000.0          # 2027-01-15 08:00 UTC


class Pipe:
    def __init__(self, r):
        self.r, self.ops = r, []

    def __getattr__(self, name):
        def call(*a, **k):
            self.ops.append((name, a, k))
            return self
        return call

    def execute(self):
        return [getattr(self.r, n)(*a, **k) for n, a, k in self.ops]


class FakeRedis:
    def __init__(self):
        self.h, self.ttl = {}, {}

    def pipeline(self, transaction=True):
        return Pipe(self)

    def hincrby(self, k, f, n):
        d = self.h.setdefault(k, {})
        d[f] = str(int(d.get(f, 0)) + n)
        return int(d[f])

    def expire(self, k, s):
        self.ttl[k] = s

    def delete(self, k):
        self.h.pop(k, None)

    def hset(self, k, f=None, v=None, mapping=None):
        d = self.h.setdefault(k, {})
        d.update(mapping or {f: v})

    def hgetall(self, k):
        return {f.encode(): str(v).encode() for f, v in self.h.get(k, {}).items()}


def _hour(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y%m%d%H")


def test_record_job_count_ok_and_err():
    r = FakeRedis()
    SR.record_job_count(r, "a", True, NOW)
    SR.record_job_count(r, "a", False, NOW)
    h = _hour(NOW)
    assert r.h[f"sched:runs:{h}"]["a"] == "2" and r.h[f"sched:errs:{h}"]["a"] == "1"
    assert r.ttl[f"sched:runs:{h}"] == 26 * 3600 and r.ttl[f"sched:errs:{h}"] == 26 * 3600

    class Boom:
        def pipeline(self, **k):
            raise RuntimeError("down")
    SR.record_job_count(Boom(), "a", False, NOW)          # 예외 삼킴


def test_snapshot_next_runs():
    class Job:
        def __init__(self, i, t):
            self.id, self.next_run_time = i, t
    sch = type("S", (), {"get_jobs": lambda self: [Job("x", datetime.fromtimestamp(NOW + 120, timezone.utc)), Job("y", None)]})()
    r = FakeRedis()
    r.h["sched:next"] = {"old": "1"}
    assert SR.snapshot_next_runs(sch, r) == 2
    assert set(r.h["sched:next"]) == {"x", "y"} and json.loads(r.h["sched:next"]["y"]) is None
    assert json.loads(r.h["sched:next"]["x"]) == NOW + 120 and r.ttl["sched:next"] == 600
    assert SR.snapshot_next_runs(type("B", (), {"get_jobs": lambda self: 1 / 0})(), r) == 0
    # 잡 id 가 guarded_job 이름과 달라도 래퍼 이름으로 남는다(감사 지적)
    fn = lambda: None  # noqa: E731
    fn.job_name = "worker"
    j = Job("worker-v2", datetime.fromtimestamp(NOW + 60, timezone.utc))
    j.func = fn
    SR.snapshot_next_runs(type("S2", (), {"get_jobs": lambda self: [j]})(), r)
    assert set(r.h["sched:next"]) == {"worker"}


def test_parse_counts_and_hour_keys():
    c = OB.parse_counts([{b"a": b"3", "b": "x"}, {"a": "2"}, None], [{b"a": b"1"}])
    assert c == {"a": (5, 1)}
    ks = OB.hour_keys(datetime(2026, 10, 15, 1, 30, tzinfo=timezone.utc).timestamp())
    assert len(ks) == 24 and ks[0] == "2026101501" and ks[1] == "2026101500" and ks[2] == "2026101423"
    assert OB.parse_next_runs({b"x": b"12.5", "y": "null", "z": "{"}) == {"x": 12.5, "y": None}


def _rec(st, ago):
    return {"s": NOW - ago - 3, "e": NOW - ago, "st": st, "err": "TimeoutError: binance" if st == "err" else None}


def _desk(d, key):
    return next(k for r in d["rooms"] for k in r["desks"] if k["key"] == key)


def test_build_unchanged_without_new_inputs():
    recs = {"pump_dump_early_detector": _rec("err", 30)}
    d = OB.build(recs=recs, extras={}, now=NOW)
    k = _desk(d, "pump")
    assert k["status"] == "error" and k["runs_24h"] is None and k["errors_24h"] is None
    assert k["next_run"] == "—" and k["next_run_at"] is None


def test_blip_rules():
    recs = {"pump_dump_early_detector": _rec("err", 30)}
    st = lambda c: _desk(OB.build(recs=recs, extras={}, now=NOW, counts24=c), "pump")["status"]  # noqa: E731
    assert st({"pump_dump_early_detector": (288, 1)}) == "blip"
    assert st({"pump_dump_early_detector": (288, 2)}) == "error"
    assert st({"pump_dump_early_detector": (5, 1)}) == "error"
    assert st({"pump_dump_early_detector": (10, 0)}) == "blip"        # 오류 0 · 실행 10 도 일시 오류(요구사항 그대로)
    d = OB.build(recs=recs, extras={}, now=NOW, counts24={"pump_dump_early_detector": (200, 1), "pump_top_detector": (88, 0)})
    k = _desk(d, "pump")
    assert (k["runs_24h"], k["errors_24h"]) == (288, 1) and d["counts"]["blip"] == 1
    assert OB.STATUS_LABEL["blip"] == "일시 오류"


def test_next_run_earliest_future_and_past():
    nr = {"pump_dump_early_detector": NOW + 300, "pump_top_detector": NOW + 90, "silent_bug_detector": NOW - 5}
    d = OB.build(recs={}, extras={}, now=NOW, next_runs=nr)
    p = _desk(d, "pump")
    assert p["next_run"] == "2분 뒤" and p["next_run_at"] == datetime.fromtimestamp(NOW + 90, OB.KST).strftime("%H:%M")
    assert _desk(d, "silent_bug")["next_run"] == "곧"
    # 지난 시각과 미래가 섞이면 미래 중 가장 이른 것(감사 지적: now+0.5 도 미래)
    d = OB.build(recs={}, extras={}, now=NOW, next_runs={"pump_dump_early_detector": NOW - 30, "pump_top_detector": NOW + 0.5})
    assert _desk(d, "pump")["next_run"] == "곧" and _desk(d, "pump")["next_run_at"] is not None
    d = OB.build(recs={}, extras={}, now=NOW, next_runs={"pump_dump_early_detector": NOW - 30, "pump_top_detector": NOW + 600})
    assert _desk(d, "pump")["next_run"] == "10분 뒤"


def test_collect_reads_counts_and_next():
    r = FakeRedis()
    for _ in range(12):
        SR.record_job_count(r, "pump_dump_early_detector", True, NOW - 3600)
    SR.record_job_count(r, "pump_dump_early_detector", False, NOW)
    r.h["sched:last"] = {"pump_dump_early_detector": json.dumps(_rec("err", 20))}
    r.h["sched:next"] = {"pump_dump_early_detector": json.dumps(NOW + 240)}
    r.get = lambda k: None
    r.exists = lambda k: 0
    d = OB.collect(None, r, now=NOW)
    k = _desk(d, "pump")
    assert (k["runs_24h"], k["errors_24h"]) == (13, 1) and k["status"] == "blip" and k["next_run"] == "4분 뒤"


def test_wiring_in_sources():
    src = (APP / "workers" / "scheduler_runner.py").read_text(encoding="utf-8")
    i = src.index("def guarded_job")
    body = src[i:src.index("return _wrapped", i)]
    fin = body[body.index("finally:"):]
    assert "record_job_count(redis_client, job_name, _ok, _t1)" in fin and "raise" in body
    assert "_wrapped.job_name = job_name" in body
    assert "snapshot_next_runs(scheduler, redis_client) if guard.refresh_leader() else 0" in src
    assert 'id="sched_next_snapshot"' in src and "snapshot_next_runs(scheduler, redis_client)" in src
    html = (APP / "static" / "office.html").read_text(encoding="utf-8")
    assert "function meta(k)" in html and ".st.blip" in html and "24h 오류" in html and "다음 실행" in html
