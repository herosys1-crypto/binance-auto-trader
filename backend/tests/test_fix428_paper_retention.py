"""Fix 428 — 진입 60일 지난 가상매매 마감 행의 snapshot·adds 비우기 (결과는 남긴다). 사장님 10/10 「5번 진행」."""
from __future__ import annotations

import pathlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.workers import paper_retention_worker as W

APP = pathlib.Path(W.__file__).resolve().parents[1]
NOW = datetime(2026, 12, 31, tzinfo=timezone.utc)


@pytest.mark.parametrize("raw, want", [(60, 60), ("90", 90), ("30", 60), ("0", None), ("abc", 60), (None, 60), ("365.0", 365),
                                      ("0.5", 60), ("inf", 60), ("nan", 60), ("1000000000", 3650), ("-5", 60)])
def test_retention_days(raw, want):
    assert W.retention_days(raw) == want                               # 60일 아래로 못 내림 · 0 = 끔


def test_report_window_never_reaches_cleared_rows():
    import app.api.v1.paper_trading as API
    assert API._REPORT_V3_MAX_DAYS <= W.MIN_DAYS                      # 보고서가 읽는 창 ⊂ 남긴 창
    src = (APP / "api" / "v1" / "paper_trading.py").read_text(encoding="utf-8")
    assert "def paper_trading_report_legacy(days: int = 60" in src


@pytest.fixture
def db(monkeypatch):
    eng = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with eng.begin() as c:
        c.execute(text("""create table paper_trades (id integer primary key, status text, opened_at timestamp,
                          snapshot text, adds text, engines text, mfe real, rule text)"""))
        rows = [
            (1, "CLOSED", NOW - timedelta(days=90), '{"a":1}', '{"x":1}', '{"house":1}', 1.5, "r"),   # 대상
            (2, "CLOSED", NOW - timedelta(days=62), '{"a":1}', None, '{"house":2}', 2.0, "r"),        # 대상 (60 + 하루 여유 넘음)
            (3, "CLOSED", NOW - timedelta(days=59), '{"a":1}', '{"x":1}', '{"house":3}', 3.0, "r"),   # 60일 안 = 남김
            (4, "OPEN", NOW - timedelta(days=200), '{"a":1}', '{"x":1}', '{"house":4}', 4.0, "r"),    # 열린 거래 = 남김
        ]
        for r in rows:
            c.execute(text("insert into paper_trades values (:a,:b,:c,:d,:e,:f,:g,:h)"),
                      dict(zip("abcdefgh", r)))
    S = sessionmaker(bind=eng, future=True)
    monkeypatch.setattr(W, "SessionLocal", S)
    monkeypatch.setattr(W, "_setting", lambda db: "60")
    return S


def test_clears_only_old_closed_rows_and_keeps_results(db):
    st = W.run_paper_retention_once(now=NOW)
    assert st["cleared"] == 2 and st["days"] == 60
    s = db()
    rows = {r[0]: r for r in s.execute(text("select id, snapshot, adds, engines, mfe from paper_trades")).all()}
    assert rows[1][1] is None and rows[1][2] is None and rows[2][1] is None
    assert rows[1][3] == '{"house":1}' and rows[1][4] == 1.5           # 엔진 결과·mfe 는 남김 (판정 보고서)
    assert rows[3][1] is not None and rows[4][1] is not None           # 60일 안 · 열린 거래는 그대로
    assert W.run_paper_retention_once(now=NOW)["cleared"] == 0          # 두 번째 실행 = 할 일 없음


def test_off_when_zero(db, monkeypatch):
    monkeypatch.setattr(W, "_setting", lambda db: "0")
    assert W.run_paper_retention_once(now=NOW) == {"days": None, "cleared": 0, "batches": 0, "skipped_lock": 0}


def test_sql_safety_pins():
    sql = str(W.UPDATE_SQL)
    assert "status = 'CLOSED'" in sql and "opened_at < :cutoff" in sql and "FOR UPDATE SKIP LOCKED" in sql
    assert "SET snapshot = NULL, adds = NULL" in sql and "engines" not in sql.split("WHERE")[0]   # engines 는 건드리지 않는다
    assert "DELETE" not in sql.upper()                                  # 행은 지우지 않는다
    src = pathlib.Path(W.__file__).read_text(encoding="utf-8")
    assert "lock_timeout" in src and "db.commit()" in src and "LIMIT :n" in sql


def test_scheduled():
    sr = (APP / "workers" / "scheduler_runner.py").read_text(encoding="utf-8")
    assert 'guarded_job("paper_retention"' in sr and "CronTrigger(hour=12, minute=40)" in sr


def test_margin_keeps_rows_just_past_60_days(db):
    """보고서 창 60일 + 하루 여유: 진입 60일 10시간 된 행은 아직 비우지 않는다."""
    s = db()
    s.execute(text("insert into paper_trades values (9, 'CLOSED', :t, '{}', '{}', '{}', 0, 'r')"),
              {"t": NOW - timedelta(days=60, hours=10)})
    s.commit()
    W.run_paper_retention_once(now=NOW)
    assert db().execute(text("select snapshot from paper_trades where id=9")).scalar() is not None


def test_setting_read_failure_skips_destructive_run(db, monkeypatch):
    def boom(_db):
        raise W.SettingReadError("db down")
    monkeypatch.setattr(W, "_setting", boom)
    st = W.run_paper_retention_once(now=NOW)
    assert st["cleared"] == 0 and st.get("error") == "setting"
    assert db().execute(text("select count(*) from paper_trades where snapshot is null")).scalar() == 0   # 아무것도 안 비움


def test_setting_missing_row_uses_default_but_error_raises():
    from types import SimpleNamespace as NS
    assert W._setting(NS(get=lambda m, k: None)) == W.DEFAULT_DAYS
    with pytest.raises(W.SettingReadError):
        W._setting(NS(get=lambda m, k: (_ for _ in ()).throw(RuntimeError("x")), rollback=lambda: None))


def test_non_lock_error_is_reported_not_hidden(db, monkeypatch):
    """Gemini: 잠금 막힘이 아닌 오류(제약 위반 등)는 skipped_lock 으로 숨기지 않는다."""
    import logging
    class E(Exception):
        orig = type("O", (), {"pgcode": "23502"})()      # not_null_violation
    orig_exec = W.SessionLocal
    def factory():
        s = orig_exec()
        real = s.execute
        def execute(stmt, *a, **k):
            if "UPDATE paper_trades" in str(stmt):
                raise E("null value violates not-null constraint")
            return real(stmt, *a, **k)
        s.execute = execute
        return s
    monkeypatch.setattr(W, "SessionLocal", factory)
    st = W.run_paper_retention_once(now=NOW)
    assert st["skipped_lock"] == 0 and st.get("error") == "E"


def test_lock_error_counts_as_skip(db, monkeypatch):
    class E(Exception):
        orig = type("O", (), {"pgcode": "55P03"})()
    orig_exec = W.SessionLocal
    def factory():
        s = orig_exec()
        real = s.execute
        s.execute = lambda stmt, *a, **k: (_ for _ in ()).throw(E("lock timeout")) if "UPDATE paper_trades" in str(stmt) else real(stmt, *a, **k)
        return s
    monkeypatch.setattr(W, "SessionLocal", factory)
    st = W.run_paper_retention_once(now=NOW)
    assert st["skipped_lock"] == 1 and "error" not in st


def test_one_line_safe_for_empty_message():
    assert W._one_line(RuntimeError(""), 50) == "RuntimeError"
    assert W._one_line(RuntimeError("a\nb"), 50) == "a"
