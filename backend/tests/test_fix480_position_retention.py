"""Fix 480 — 보관 일수 지난 포지션 스냅샷 지우기 (전략별 최신 행은 어느 정렬이든 남긴다). 사장님 10/22 「다음으로 진행」."""
from __future__ import annotations

import itertools
import pathlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.workers import position_retention_worker as W

APP = pathlib.Path(W.__file__).resolve().parents[1]
NOW = datetime(2026, 12, 31, tzinfo=timezone.utc)


def ago(d):
    return NOW - timedelta(days=d)


@pytest.mark.parametrize("raw, want", [("0", None), (0, None), ("30", 30), ("7", 14), ("99999", 3650), ("1.5", 30), ("abc", 30),
                                      (None, 30), ("inf", 30), ("nan", 30), ("45.0", 45), (True, 30), ("-5", 14)])
def test_retention_days(raw, want):
    assert W.retention_days(raw) == want


@pytest.fixture
def mk(monkeypatch):
    eng = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with eng.begin() as c:
        c.execute(text("create table positions (id integer primary key, strategy_instance_id integer, snapshot_time timestamp, symbol text)"))
    S = sessionmaker(bind=eng, future=True)
    monkeypatch.setattr(W, "SessionLocal", S)
    monkeypatch.setattr(W, "_setting", lambda db: "30")

    def put(rows):                                    # (id, 전략, 며칠 전)
        with eng.begin() as c:
            for i, sid, d in rows:
                c.execute(text("insert into positions values (:i, :s, :t, 'X')"), {"i": i, "s": sid, "t": None if d is None else ago(d)})

    def ids():
        with eng.connect() as c:
            return {r[0] for r in c.execute(text("select id from positions")).all()}
    return put, ids


def test_old_rows_go_latest_stays(mk):
    put, ids = mk
    put([(1, 1, 40), (2, 1, 40), (3, 1, 39), (4, 1, 1),        # 전략 1: 오래된 3 지움 · 최신 남김
         (5, 2, 40), (6, 2, 35),                               # 전략 2: 오래된 것만 → 최신(최대 id) 남김
         (7, 3, 10), (8, 3, 5)])                               # 전략 3: 보관 일수 안 = 그대로
    st = W.run_position_retention_once(now=NOW)
    assert st["deleted"] == 4 and st["days"] == 30
    assert ids() == {4, 6, 7, 8}
    assert W.run_position_retention_once(now=NOW)["deleted"] == 0     # 두 번째 = 할 일 없음


def test_two_orderings_disagree_both_kept(mk):
    put, ids = mk
    put([(1, 5, 50), (2, 5, 40), (3, 5, 45)])                  # 최대 id = 3(45일 전) · 최신 시각 = 2(40일 전)
    W.run_position_retention_once(now=NOW)
    assert ids() == {2, 3}


def test_null_rows_untouched(mk):
    put, ids = mk
    put([(1, None, 90), (2, 7, None), (3, 7, 90), (4, 7, 80)])
    W.run_position_retention_once(now=NOW)
    assert ids() == {1, 2, 4}                                  # 전략 NULL · 시각 NULL 은 남김


def test_exhaustive_latest_preserved(mk):
    """전략 하나에 4행 × 시각 3가지 = 81가지 — 두 정렬의 최신 행은 언제나 남고, 그 밖의 오래된 행은 지워진다."""
    put, ids = mk
    times = (60, 45, 31)
    nid = itertools.count(1)
    expect_keep = set()
    rows = []
    for sid, combo in enumerate(itertools.product(times, repeat=4), start=1):
        mine = [(next(nid), sid, d) for d in combo]
        rows += mine
        latest_id = max(i for i, _s, _d in mine)
        newest = min(d for _i, _s, d in mine)
        expect_keep |= {latest_id} | {i for i, _s, d in mine if d == newest}
    put(rows)
    W.BATCH, old = 7, W.BATCH                                  # 여러 묶음
    try:
        st = W.run_position_retention_once(now=NOW)
    finally:
        W.BATCH = old
    assert ids() == expect_keep and st["batches"] > 1
    for sid in range(1, 82):                                   # 두 정렬로 읽어도 지우기 전과 같은 행
        mine = [r for r in rows if r[1] == sid]
        assert max(i for i, *_ in mine) in ids()
        assert max(mine, key=lambda r: (-r[2], r[0]))[0] in ids()


def test_max_batches_cap(mk, monkeypatch):
    put, ids = mk
    put([(i, 1, 40) for i in range(1, 51)] + [(99, 1, 1)])
    monkeypatch.setattr(W, "BATCH", 10)
    monkeypatch.setattr(W, "MAX_BATCHES", 2)
    st = W.run_position_retention_once(now=NOW)
    assert st["deleted"] == 20 and st["batches"] == 2 and len(ids()) == 31   # 남은 건 다음 실행에


def test_off_when_zero(mk, monkeypatch):
    put, ids = mk
    put([(1, 1, 90), (2, 1, 1)])
    monkeypatch.setattr(W, "_setting", lambda db: "0")
    assert W.run_position_retention_once(now=NOW) == {"days": None, "deleted": 0, "batches": 0, "skipped_lock": 0}
    assert ids() == {1, 2}


def test_setting_failure_skips(mk, monkeypatch):
    put, ids = mk
    put([(1, 1, 90), (2, 1, 1)])

    def boom(db):
        raise W.SettingReadError("db down")
    monkeypatch.setattr(W, "_setting", boom)
    st = W.run_position_retention_once(now=NOW)
    assert st["error"] == "setting" and st["deleted"] == 0 and ids() == {1, 2}


def test_lock_code_yields(monkeypatch):
    class Orig(Exception):
        pgcode = "55P03"

    class Err(Exception):
        orig = Orig()
    assert W._pgcode(Err()) == "55P03"

    class Psy3(Exception):
        sqlstate = "40P01"
    assert W._pgcode(Psy3()) == "40P01"


def test_postgres_sql_shape():
    sql = W.DELETE_SQL.format(lock="FOR UPDATE SKIP LOCKED")
    assert "snapshot_time < :cutoff" in sql and "id NOT IN :keep" in sql and "LIMIT :n" in sql and "SKIP LOCKED" in sql
    assert "strategy_instance_id IS NOT NULL" in sql
    keep = str(W.KEEP_SQL)
    assert "max(id)" in keep and "max(snapshot_time)" in keep and "UNION" in keep
    src = pathlib.Path(W.__file__).read_text(encoding="utf-8")
    assert "lock_timeout" in src and "db.commit()" in src and "VACUUM" not in src.split('"""', 2)[2] and "TRUNCATE" not in src


def test_scheduled():
    sr = (APP / "workers" / "scheduler_runner.py").read_text(encoding="utf-8")
    assert 'guarded_job("position_retention"' in sr and 'CronTrigger(hour=12, minute=50, timezone="Asia/Seoul")' in sr
