"""Fix 409 채점 워커 교착 제거 — Duel_Lab chart-timing-deadlock Claude 초안 테스트."""
from __future__ import annotations

import logging
import os
import time
import types
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.sql.elements import TextClause

import app.services.chart_state as CS
import app.workers.chart_learning_worker as CLW
import app.workers.chart_timing_worker as W
from app.models.paper_trade import PaperTrade
from app.models.trade_learning_record import TradeLearningRecord

SET_SQL = "SET LOCAL lock_timeout = '3000ms'"


# ───────────────────────── 가짜 드라이버 오류 ─────────────────────────
class FakePgError(Exception):
    """psycopg2 오류 흉내: pgcode 속성."""
    def __init__(self, msg, pgcode):
        super().__init__(msg)
        self.pgcode = pgcode


class PlainDriverError(Exception):
    """pgcode 속성 자체가 없는 드라이버 오류 → 문자열 판정 경로."""


def db_error(msg, pgcode=None, *, cls=OperationalError):
    orig = FakePgError(msg, pgcode) if pgcode is not None else PlainDriverError(msg)
    return cls("UPDATE paper_trades SET snapshot=... WHERE id=%(rid)s", {"rid": 0}, orig)


# ───────────────────────── 가짜 문장 / 세션 ─────────────────────────
@dataclass(frozen=True)
class Sel:
    kind: str


@dataclass(frozen=True)
class Upd:
    model: object
    column: str
    key: str
    rid: object
    res: dict


class _Result:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


class FakeDB:
    """실행 순서(events)와 트랜잭션 상태를 기록. PostgreSQL 처럼 오류 뒤에는 rollback 전까지 막힌다."""

    def __init__(self, paper_rows=(), real_rows=(), dialect="postgresql",
                 update_errors=None, rollback_errors=None):
        self.paper_rows = list(paper_rows)
        self.real_rows = list(real_rows)
        self.dialect = dialect
        self.update_errors = dict(update_errors or {})      # n번째(1부터) UPDATE 시도 → 예외
        self.rollback_errors = list(rollback_errors or [])  # rollback 호출 시 차례로 예외
        self.events: list[tuple] = []
        self.updates: list[Upd] = []
        self.violations: list[str] = []
        self.in_tx = False
        self.aborted = False
        self.tx_updates = 0
        self.update_attempts = 0
        self.closed = False

    def get_bind(self):
        if isinstance(self.dialect, BaseException):
            raise self.dialect
        return types.SimpleNamespace(dialect=types.SimpleNamespace(name=self.dialect))

    def execute(self, stmt, *a, **k):
        if self.aborted:
            raise db_error("current transaction is aborted, commands ignored until end of transaction block",
                           "25P02")
        self.in_tx = True  # Session autobegin
        if isinstance(stmt, TextClause):
            self.events.append(("SET", stmt.text))
            return _Result()
        if isinstance(stmt, Sel):
            self.events.append(("SELECT", stmt.kind))
            return _Result(self.paper_rows if stmt.kind == "paper" else self.real_rows)
        if isinstance(stmt, Upd):
            self.update_attempts += 1
            err = self.update_errors.get(self.update_attempts)
            if err is not None:
                self.events.append(("UPDATE_FAIL", stmt.rid))
                self.aborted = True
                raise err
            self.tx_updates += 1
            if self.tx_updates > 1:
                self.violations.append(f"한 트랜잭션에 UPDATE {self.tx_updates}개 (rid={stmt.rid})")
            self.events.append(("UPDATE", stmt.rid))
            self.updates.append(stmt)
            return _Result()
        raise AssertionError(f"예상 못 한 문장: {stmt!r}")

    def _end_tx(self):
        self.in_tx = False
        self.aborted = False
        self.tx_updates = 0

    def commit(self):
        if self.aborted:
            self.violations.append("rollback 없이 commit")
        self.events.append(("commit",))
        self._end_tx()

    def rollback(self):
        self.events.append(("rollback",))
        if self.rollback_errors:
            raise self.rollback_errors.pop(0)
        self._end_tx()

    def close(self):
        self.closed = True

    @property
    def updated_rids(self):
        return [u.rid for u in self.updates]


def rows(*rids):
    t = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [(rid, f"S{rid}", "long", 100.0, t) for rid in rids]


def row_block(rid, *, set_local=True):
    blk = [("label", f"S{rid}")]
    if set_local:
        blk.append(("SET", SET_SQL))
    return blk + [("UPDATE", rid), ("commit",), ("sleep",)]


# ───────────────────────── 실행 픽스처 ─────────────────────────
@pytest.fixture
def run(monkeypatch):
    def _run(db, label=None, bc=object()):
        def fake_open(decrypt_text):
            return db, bc

        def fake_label_one(bc_, cs_, th_, symbol, side, entry_price, entry_at, now_ms):
            db.events.append(("label", symbol))
            if db.in_tx:
                db.violations.append(f"거래소 조회 중 트랜잭션 열림: {symbol}")
            return label(symbol) if label else {"label": "good"}

        def fake_sleep(sec):
            db.events.append(("sleep",))
            if db.in_tx:
                db.violations.append("sleep 중 트랜잭션 열림")

        monkeypatch.setattr(CLW, "_open", fake_open)
        monkeypatch.setattr(CS, "setting_on", lambda db_, key, default=True: True)
        monkeypatch.setattr(CS, "thresholds", lambda db_: {"timing_after_bars": 48})
        monkeypatch.setattr(W, "_label_one", fake_label_one)
        monkeypatch.setattr(W, "paper_stmt", lambda **kw: Sel("paper"))
        monkeypatch.setattr(W, "real_stmt", lambda **kw: Sel("real"))
        monkeypatch.setattr(W, "_set_json_stmt",
                            lambda model, column, key, rid, res: Upd(model, column, key, rid, res))
        monkeypatch.setattr(W, "time", types.SimpleNamespace(
            sleep=fake_sleep, time=time.time, monotonic=time.monotonic))
        return W.run_chart_timing_once(lambda s: s)
    return _run


def fail_for(*symbols):
    def label(symbol):
        if symbol in symbols:
            raise RuntimeError(f"bybit 5m 조회 실패 {symbol}")
        return {"label": "good"}
    return label


# ───────────────────────── 1. 행마다 즉시 commit ─────────────────────────
def test_each_update_committed_immediately_and_fetch_outside_tx(run):
    assert W.LOCK_TIMEOUT_MS == 3000
    db = FakeDB(paper_rows=rows(1, 2, 3), real_rows=rows(10))
    stat = run(db, label=lambda s: {"label": None} if s == "S3" else {"label": "good"})

    expected = [("SELECT", "paper"), ("SELECT", "real"), ("commit",)]
    for rid in (1, 2, 3, 10):
        expected += row_block(rid)
    expected += [("commit",)]
    assert db.events == expected
    assert db.violations == []
    assert stat == {"paper": 2, "real": 1, "no_bars": 1, "fail": 0, "lock_skip": 0}
    assert [(u.model, u.column, u.key) for u in db.updates] == [
        (PaperTrade, "snapshot", "chart_timing")] * 3 + [(TradeLearningRecord, "insights", "chart_timing")]
    assert db.closed


# ───────────────────────── 2. 방언 판단 ─────────────────────────
@pytest.mark.parametrize("dialect", ["sqlite", "mysql", None, RuntimeError("unbound session")],
                         ids=["sqlite", "mysql", "name-None", "get_bind-raises"])
def test_no_set_local_unless_postgresql(run, dialect):
    db = FakeDB(paper_rows=rows(1, 2), dialect=dialect)
    stat = run(db)
    assert not any(e[0] == "SET" for e in db.events)
    expected = [("SELECT", "paper"), ("SELECT", "real"), ("commit",)]
    expected += row_block(1, set_local=False) + row_block(2, set_local=False) + [("commit",)]
    assert db.events == expected
    assert stat == {"paper": 2, "real": 0, "no_bars": 0, "fail": 0, "lock_skip": 0}
    assert db.violations == []


# ───────────────────────── 3. 잠금 충돌 → 그 행만 건너뜀 ─────────────────────────
LOCK_ERRORS = [
    pytest.param(db_error("canceling statement due to lock timeout", "55P03"), id="55P03"),
    pytest.param(db_error("deadlock detected\nDETAIL:  Process 1 waits for ShareLock", "40P01"), id="40P01"),
    pytest.param(db_error("ERROR:  canceling statement due to lock timeout"), id="text-lock-timeout"),
    pytest.param(db_error("ERROR:  deadlock detected\nDETAIL:  ..."), id="text-deadlock"),
    pytest.param(db_error("x", "55P03", cls=DBAPIError), id="DBAPIError-55P03"),
]


@pytest.mark.parametrize("err", LOCK_ERRORS)
def test_lock_conflict_skips_only_that_row(run, caplog, err):
    caplog.set_level(logging.WARNING, logger=W.logger.name)
    db = FakeDB(paper_rows=rows(1, 2, 3, 4, 5), update_errors={3: err})
    stat = run(db)

    assert "error" not in stat
    assert stat == {"paper": 4, "real": 0, "no_bars": 0, "fail": 0, "lock_skip": 1}
    assert db.updated_rids == [1, 2, 4, 5]
    i = db.events.index(("UPDATE_FAIL", 3))
    assert db.events[i - 1] == ("SET", SET_SQL)
    assert db.events[i + 1] == ("rollback",)
    assert db.events[i + 2:i + 3] == [("sleep",)]
    assert db.violations == []

    warns = [r for r in caplog.records
             if r.name == W.logger.name and r.levelno == logging.WARNING and "건너뜀" in r.getMessage()]
    assert len(warns) == 1
    assert "\n" not in warns[0].getMessage()
    assert "#3" in warns[0].getMessage()


def test_lock_skip_does_not_count_toward_consec(run):
    # 행1 잠금 건너뜀 → 행2·3 조회 실패. lock_skip 이 consec 에 들어가면 여기서 3회 → 중단된다.
    db = FakeDB(paper_rows=rows(1, 2, 3, 4, 5),
                update_errors={1: db_error("canceling statement due to lock timeout", "55P03")})
    stat = run(db, label=fail_for("S2", "S3"))
    assert "error" not in stat
    assert stat == {"paper": 2, "real": 0, "no_bars": 0, "fail": 2, "lock_skip": 1}
    assert db.updated_rids == [4, 5]
    assert db.violations == []


def test_lock_skip_but_rollback_fails_ends_cycle(run):
    db = FakeDB(paper_rows=rows(1, 2, 3),
                update_errors={2: db_error("canceling statement due to lock timeout", "55P03")},
                rollback_errors=[db_error("server closed the connection unexpectedly", "08006")])
    stat = run(db)
    assert "error" in stat
    assert db.updated_rids == [1]
    assert ("label", "S3") not in db.events
    assert db.closed


# ───────────────────────── 4. 그 밖의 DB 오류 → 사이클 오류 ─────────────────────────
OTHER_ERRORS = [
    pytest.param(db_error("server closed the connection unexpectedly", "08006"), id="08006"),
    pytest.param(db_error("canceling statement due to statement timeout", "57014"), id="57014-statement-timeout"),
    pytest.param(db_error("weird message mentioning lock timeout", "23505"), id="pgcode-wins-over-text"),
    pytest.param(db_error("connection reset by peer"), id="no-pgcode-no-marker"),
    pytest.param(ValueError("non-DB bug"), id="non-DBAPI"),
]


@pytest.mark.parametrize("err", OTHER_ERRORS)
def test_other_db_error_rolls_back_and_ends_cycle(run, caplog, err):
    caplog.set_level(logging.ERROR, logger=W.logger.name)
    db = FakeDB(paper_rows=rows(1, 2, 3, 4, 5), update_errors={3: err})
    stat = run(db)

    assert "error" in stat
    assert stat["lock_skip"] == 0 and stat["paper"] == 2
    assert db.updated_rids == [1, 2]
    assert db.update_attempts == 3
    i = db.events.index(("UPDATE_FAIL", 3))
    assert db.events[i + 1] == ("rollback",)
    assert ("label", "S4") not in db.events
    assert ("commit",) not in db.events[i:]
    assert db.closed
    assert any("타이밍 채점 워커 오류" in r.getMessage() for r in caplog.records)


def test_invalid_lock_timeout_constant_fails_loudly(run, monkeypatch):
    monkeypatch.setattr(W, "LOCK_TIMEOUT_MS", 0)  # 0 = PG 무한 대기 → 금지
    db = FakeDB(paper_rows=rows(1, 2))
    stat = run(db)
    assert "error" in stat
    assert db.updated_rids == []


# ───────────────────────── 5. 기존 의미 유지 ─────────────────────────
def test_three_consecutive_fetch_failures_stop_cycle(run, caplog):
    caplog.set_level(logging.WARNING, logger=W.logger.name)
    db = FakeDB(paper_rows=rows(1, 2, 3, 4, 5))
    stat = run(db, label=fail_for("S1", "S2", "S3"))
    assert stat == {"paper": 0, "real": 0, "no_bars": 0, "fail": 3, "lock_skip": 0}
    assert db.events == [("SELECT", "paper"), ("SELECT", "real"), ("commit",),
                         ("label", "S1"), ("label", "S2"), ("label", "S3"), ("commit",)]
    assert any("연속 실패" in r.getMessage() and r.levelno == logging.ERROR for r in caplog.records)


def test_consec_resets_on_success(run):
    db = FakeDB(paper_rows=rows(1, 2, 3, 4, 5, 6))
    stat = run(db, label=fail_for("S1", "S2", "S4", "S5"))
    assert stat == {"paper": 2, "real": 0, "no_bars": 0, "fail": 4, "lock_skip": 0}
    assert db.updated_rids == [3, 6]


def test_no_account(run):
    assert run(None) == {"error": "no account"}


# ───────────────────────── 6. (선택) 실제 PostgreSQL 통합 ─────────────────────────
PG_URL = os.environ.get("CHART_TIMING_PG_URL")


@pytest.mark.skipif(not PG_URL, reason="CHART_TIMING_PG_URL 미설정 — 실제 PostgreSQL 통합 테스트 생략")
def test_pg_locked_row_skipped_after_lock_timeout(monkeypatch):
    pytest.importorskip("psycopg2")
    import json
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    engine = create_engine(PG_URL)
    table = f"ct_lock_probe_{uuid.uuid4().hex[:12]}"
    with engine.begin() as c:
        c.execute(text(f"CREATE TABLE {table} (id int PRIMARY KEY, "
                       f"snapshot jsonb NOT NULL DEFAULT CAST('{{}}' AS jsonb))"))
        c.execute(text(f"INSERT INTO {table} (id) VALUES (1), (2), (3)"))
    holder = None
    try:
        with engine.connect() as c:
            before = c.execute(text("SHOW lock_timeout")).scalar()

        def set_json(model, column, key, rid, res):
            return text(f"UPDATE {table} SET snapshot = snapshot || "
                        f"jsonb_build_object(CAST(:key AS text), CAST(:val AS jsonb)) WHERE id = :rid"
                        ).bindparams(key=key, val=json.dumps(res), rid=rid)

        monkeypatch.setattr(CLW, "_open", lambda d: (Session(engine), object()))
        monkeypatch.setattr(CS, "setting_on", lambda db_, key, default=True: True)
        monkeypatch.setattr(CS, "thresholds", lambda db_: {"timing_after_bars": 48})
        monkeypatch.setattr(W, "_label_one", lambda *a: {"label": "good"})
        monkeypatch.setattr(W, "paper_stmt", lambda **kw: text(
            f"SELECT id, 'S' || id, 'long', 100.0, now() FROM {table} ORDER BY id"))
        monkeypatch.setattr(W, "real_stmt", lambda **kw: text(
            f"SELECT id, 'S' || id, 'long', 100.0, now() FROM {table} WHERE false"))
        monkeypatch.setattr(W, "_set_json_stmt", set_json)
        monkeypatch.setattr(W, "SLEEP_SEC", 0)

        # 다른 커넥션이 행 2 를 잡고 놓지 않는다 (가상매매 워커 흉내)
        holder = engine.connect()
        tx = holder.begin()
        holder.execute(text(f"SELECT 1 FROM {table} WHERE id = 2 FOR UPDATE"))

        t0 = time.monotonic()
        stat = W.run_chart_timing_once(lambda s: s)
        elapsed = time.monotonic() - t0
        tx.rollback()

        assert "error" not in stat, stat
        assert stat["lock_skip"] == 1 and stat["paper"] == 2
        assert elapsed >= W.LOCK_TIMEOUT_MS / 1000 * 0.9
        with engine.connect() as c:
            got = dict(c.execute(text(
                f"SELECT id, (snapshot -> 'chart_timing') IS NOT NULL FROM {table}")).all())
            assert got == {1: True, 2: False, 3: True}
            assert c.execute(text("SHOW lock_timeout")).scalar() == before  # SET LOCAL 누수 없음
    finally:
        if holder is not None:
            holder.close()
        with engine.begin() as c:
            c.execute(text(f"DROP TABLE IF EXISTS {table}"))
        engine.dispose()