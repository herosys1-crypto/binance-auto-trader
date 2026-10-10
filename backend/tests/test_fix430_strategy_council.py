"""Fix 430 — 전략 운영팀 성적표·배치표 (분석 전용)."""
from __future__ import annotations

import json
import pathlib
import random
import time
from datetime import date, timedelta
from types import SimpleNamespace as NS

from app.services import strategy_council as SC
from app.services.strategy_council import Row

D0 = date(2026, 9, 1)
APP = pathlib.Path(SC.__file__).resolve().parents[1]


def _day(i: int) -> date:
    return D0 + timedelta(days=i)


def test_empty_input():
    rep = SC.build_report([])
    assert rep["A_rules"] == [] and rep["D_walk"]["n_days"] == 0 and rep["E_today"]["cells"] == []
    json.dumps(rep, allow_nan=False)


def test_edge_is_vs_same_day_same_side_baseline():
    rows = [Row("baseline_LONG", "LONG", _day(0), 1.0), Row("baseline_LONG", "LONG", _day(0), 3.0),   # 무작위 평균 2
            Row("baseline_SHORT", "SHORT", _day(0), -5.0),
            Row("r1", "LONG", _day(0), 5.0), Row("r1", "LONG", _day(0), 1.0),                        # 평균 3 → edge +1
            Row("r1", "LONG", _day(1), 9.0)]                                                         # 그 날 무작위 없음 → edge 제외
    a = {(x["rule"], x["side"]): x for x in SC.build_report(rows)["A_rules"]}[("r1", "LONG")]
    assert a["n"] == 3 and a["roi"] == 5.0 and a["edge"] == 1.0


def test_overlap_k_same_side_unique_excludes_baseline():
    rows = [Row("a", "LONG", _day(0), 1.0, rf=("a", "b", "b", "baseline_LONG", "s")),   # 같은 방향 a,b → 2 (s 는 SHORT)
            Row("b", "LONG", _day(0), 1.0, rf=None),                                      # 자기만 → 1
            Row("c", "LONG", _day(0), 1.0, rf=("x", "y")),                                # 모르는 이름 무시 → 1 (자기 포함)
            Row("d", "LONG", _day(0), 1.0, rf=("a", "b", "c", "d", "e")),                 # e 모름 → a,b,c,d = 4
            Row("s", "SHORT", _day(0), 1.0)]
    B = {(x["side"], x["k"]): x["n"] for x in SC.build_report(rows)["B_overlap"]}
    assert B == {("LONG", 1): 2, ("LONG", 2): 1, ("LONG", 4): 1, ("SHORT", 1): 1}


def test_bucket_and_none():
    assert SC.bucket(None, .4, .6) == "?" and SC.bucket(.39, .4, .6) == "low"
    assert SC.bucket(.4, .4, .6) == "mid" and SC.bucket(.6, .4, .6) == "mid" and SC.bucket(.61, .4, .6) == "high"


def test_params_bounds():
    assert SC.clean_params() == SC.DEFAULTS
    assert SC.clean_params(lo=.7, hi=.5) == SC.DEFAULTS                      # lo ≥ hi → 둘 다 기본
    assert SC.clean_params(train_days=2.5, gap=99, min_n="x") == SC.DEFAULTS
    assert SC.clean_params(gap=0)["gap"] == SC.DEFAULTS["gap"]                 # gap 0 = D 당일로 D 선택(미래 참조) → 거부
    p = SC.params_from(lambda k: {"council_min_n": "50", "council_breadth_lo": "0.3"}.get(k))
    assert p["min_n"] == 50 and p["lo"] == 0.3
    assert SC.params_from(lambda k: 1 / 0) == SC.DEFAULTS                    # 조회 실패 = 기본값


def _synthetic(n_days=30, seed=1):
    rnd = random.Random(seed)
    rows = []
    for i in range(n_days):
        d = _day(i)
        mb = 0.3 if i % 3 else 0.7
        for _ in range(20):
            rows.append(Row("baseline_LONG", "LONG", d, rnd.gauss(0, 1), mb))
            rows.append(Row("good", "LONG", d, rnd.gauss(1.0, 1), mb, ("good", "meh")))
            rows.append(Row("meh", "LONG", d, rnd.gauss(-0.5, 1), mb))
    return rows


def test_walk_forward_picks_good_and_no_lookahead():
    rows = _synthetic()
    rep = SC.build_report(rows, min_n=10)
    picked = {(c["rule"], c["side"]) for c in rep["E_today"]["cells"]}
    assert ("good", "LONG") in picked and ("meh", "LONG") not in picked
    st = {f["rule"]: f["status"] for f in rep["F_status"]}
    assert st["good"] == "사용 후보" and st["meh"] == "중지 후보"
    # D 이후 행을 바꿔도 D 의 칸 수는 그대로 (학습창은 D−gap 까지만)
    D = _day(20)
    changed = [r if r.d <= D - timedelta(days=SC.DEFAULTS["gap"]) else Row(r.rule, r.side, r.d, -r.roi * 7, r.mb, r.rf) for r in rows]
    a = {x["d"]: x["cells"] for x in rep["D_walk"]["days"]}
    b = {x["d"]: x["cells"] for x in SC.build_report(changed, min_n=10)["D_walk"]["days"]}
    assert a[D.isoformat()] == b[D.isoformat()]


def test_training_window_boundary():
    """학습창 = [D−gap−train+1, D−gap]. D−gap+1 의 행은 D 선택에 쓰이지 않는다."""
    rows = []
    for i in range(12):
        rows += [Row("baseline_LONG", "LONG", _day(i), 0.0, .3)] * 3 + [Row("r", "LONG", _day(i), 1.0, .3)] * 3
    rep = SC.build_report(rows, train_days=3, gap=2, min_n=5)
    days = {x["d"]: x["cells"] for x in rep["D_walk"]["days"]}
    # D=day4: 창 [day0, day2] (3일 × 3행 = 9 ≥ 5) → 칸 1
    assert days[_day(4).isoformat()] == 1
    # 워밍업: D=day2 의 창 [−2, 0] 은 하루뿐(< 2일) → 채점 안 함
    assert _day(2).isoformat() not in days


def test_json_safe_and_fast():
    rnd = random.Random(3)
    rows = []
    rules = [f"r{i}" for i in range(24)]
    for i in range(150_000):
        d = _day(i % 30)
        ru = rnd.choice(rules + ["baseline_LONG", "baseline_SHORT"])
        side = "SHORT" if ru.endswith("SHORT") or (ru[1:].isdigit() and int(ru[1:]) % 2) else "LONG"
        rows.append(Row(ru, side, d, rnd.gauss(0, 3), rnd.random() if i % 7 else None,
                        tuple(rnd.sample(rules, 3)) if i % 5 else None))
    t = time.monotonic()
    rep = SC.build_report(rows)
    assert time.monotonic() - t < 10
    json.dumps(rep, allow_nan=False)


def test_worker_row_parsing_and_summary():
    from app.workers import strategy_council_worker as W
    assert W.to_row(NS(rule="a", side="LONG", d=D0, roi="1.5", mb="0.7", rf=["x", 3])) == Row("a", "LONG", D0, 1.5, 0.7, ("x",))
    assert W.to_row(NS(rule="a", side="LONG", d=D0, roi="nan", mb=None, rf=None)) is None
    assert W.to_row(NS(rule="a", side="LONG", d=D0, roi=1, mb="2", rf="x")).mb is None
    assert W.council_days("7") == W.DEFAULT_DAYS and W.council_days("45") == 45
    title, body = W.summary_text(SC.build_report(_synthetic(), min_n=10))
    assert "전략 운영팀" in title and "주문·설정은 바꾸지 않습니다" in body


def test_worker_is_read_only():
    src = (APP / "workers" / "strategy_council_worker.py").read_text(encoding="utf-8")
    sql = src[src.index('SQL = text("""'):src.index('""")', src.index('SQL = text("""'))]
    assert "SELECT" in sql and not any(w in sql.upper() for w in ("UPDATE", "DELETE", "INSERT"))
    assert "db.commit" not in src and "create_surge_position" not in src


def test_today_param_sets_target_day():
    rep = SC.build_report(_synthetic(), min_n=10, today=_day(40))
    assert rep["E_today"]["d"] == _day(40).isoformat()


def test_worker_reads_roi_as_text():
    from app.workers import strategy_council_worker as W
    assert "::float AS roi" not in W.SQL.text and "stream_results" in pathlib.Path(W.__file__).read_text(encoding="utf-8")
    assert W.to_row(NS(rule="a", side="LONG", d=D0, roi="abc", mb="x", rf=None)) is None
