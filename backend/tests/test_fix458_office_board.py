"""🏢 Fix 458 — 자동매매 사무실 화면 (사장님 10/14 「사무실 탭 진행해줘」)."""
from __future__ import annotations

import json
import pathlib

from app.services import office_board as OB

APP = pathlib.Path(OB.__file__).resolve().parents[1]
NOW = 1_800_000_000.0


def _rec(st, ago_s, err=None):
    r = {"s": NOW - ago_s - 5, "st": st}
    if st != "run":
        r["e"] = NOW - ago_s
    if err:
        r["err"] = err
    return r


def test_job_status_rules():
    recs = {"a": _rec("run", 1), "b": _rec("err", 30, "Boom: x"), "c": _rec("ok", 4000), "d": _rec("ok", 100)}
    assert OB.job_status(recs, ("a",), 300, NOW)[0] == "working"
    assert OB.job_status(recs, ("b",), 300, NOW)[0] == "error"
    assert OB.job_status(recs, ("c",), 300, NOW)[0] == "stale"          # 300 × 3 = 900초 넘음
    assert OB.job_status(recs, ("d",), 300, NOW)[0] == "waiting"
    assert OB.job_status(recs, ("zz",), 300, NOW)[0] == "unknown"
    st, rec = OB.job_status(recs, ("c", "d"), 300, NOW)                  # 가장 최근 시작 잡으로
    assert st == "waiting" and rec["job"] == "d"


def test_build_rooms_and_extras():
    recs = {"orchestra_health": _rec("ok", 60), "rule_families": _rec("run", 2), "paper_trading": _rec("ok", 120),
            "pattern_learning": _rec("ok", 600), "learning_team_cycle": _rec("ok", 3600), "silent_bug_detector": _rec("err", 20, "X")}
    extras = {"halt": False, "modes": {"rf_bottom_long": "on", "rf_zone_s4": "off"}, "active": {"rf_bottom_long": 2},
              "health": {"checks": 4, "healthy": 4, "fixes": 0}, "pattern_no_data": {"newest_outcome": "2026-09-12T22:15"},
              "paper_last": {"symbols": 608, "opened": 3, "managed": 9000, "closed": 20, "regime": "MKT_UP", "breadth": 0.6, "seconds": 300},
              "learning": {"learning": {"at": "2026-10-14T12:38:13+00:00"}}, "council_today": True,
              "verdict_latest": {"day": "2026-10-17", "kind": "midcheck"}}
    d = OB.build(recs=recs, extras=extras, now=NOW)
    desks = {k["key"]: k for r in d["rooms"] for k in r["desks"]}
    assert [r["label"] for r in d["rooms"]] == ["지휘실", "실주문 매매실", "가상매매 연구실", "학습실", "감시실"]
    assert desks["halt"]["status"] == "on" and "정상" in desks["halt"]["detail"]
    assert desks["rf_bottom_long"]["status"] == "working" and "진행 중 2건" in desks["rf_bottom_long"]["detail"]
    assert desks["rf_zone_s4"]["status"] == "off"
    assert desks["pattern_learning"]["status"] == "nodata" and "2026-09-12" in desks["pattern_learning"]["detail"]
    assert desks["silent_bug"]["status"] == "error" and desks["silent_bug"]["error"] == "X"
    assert "감시 608" in desks["paper"]["detail"] and "오늘 성적표 있음" in desks["council"]["detail"]
    assert "마지막 학습 완료 10-14 12:38" in desks["learning_team"]["detail"]
    assert "중간 점검" in desks["verdict"]["detail"]
    assert d["counts"]["error"] == 1 and json.dumps(d, ensure_ascii=False)


def test_halt_and_health_error():
    d = OB.build(recs={"orchestra_health": _rec("ok", 30)}, extras={"halt": True, "health": {"checks": 4, "healthy": 3, "fixes": 1}}, now=NOW)
    desks = {k["key"]: k for r in d["rooms"] for k in r["desks"]}
    assert desks["halt"]["status"] == "error" and "전면 중단" in desks["halt"]["detail"]
    assert desks["conductor"]["status"] == "error" and "3/4" in desks["conductor"]["detail"]


def test_other_errors_listed_and_parse():
    recs = OB.parse_job_records({b"x_job": json.dumps(_rec("err", 5, "e")), "bad": "{"})
    assert set(recs) == {"x_job"}
    assert OB.build(recs=recs, extras={}, now=NOW)["other_errors"] == ["x_job"]


def test_collect_survives_broken_redis_and_db():
    class Boom:
        def __getattr__(self, n):
            raise RuntimeError("down")
    d = OB.collect(Boom(), Boom(), now=NOW)
    assert d["rooms"] and d["jobs_recorded"] == 0


def test_scheduler_recorder_and_wiring():
    from app.workers import scheduler_runner as SR

    class R:
        def __init__(self):
            self.h = {}

        def hset(self, k, f, v):
            self.h[(k, f)] = json.loads(v)
    r = R()
    SR._record_job(r, "job1", {"s": 1.0, "st": "run"})
    assert r.h[("sched:last", "job1")]["st"] == "run"
    SR._record_job(None, "job1", {"s": 1})                              # 실패해도 예외 없음(기본 클라이언트 오류 삼킴)
    src = (APP / "workers" / "scheduler_runner.py").read_text(encoding="utf-8")
    i = src.index("def guarded_job")
    body = src[i:src.index("return _wrapped", i)]
    assert '_record_job(redis_client, job_name, {"s": round(_t0, 1), "st": "run"})' in body
    assert "raise" in body and '"st": "ok" if _ok else "err"' in body
    api = (APP / "api" / "v1" / "orchestra_status.py").read_text(encoding="utf-8")
    assert '@router.get("/office")' in api and "OFFICE_CACHE_TTL = 20" in api
    html = (APP / "static" / "index.html").read_text(encoding="utf-8")
    assert "openOffice()" in html and "/static/office.html" in html
    assert (APP / "static" / "office.html").exists()
