"""💾 Fix 451 — 열린 가상 포지션은 N분마다만 저장 (저장 방식 A, 사장님 10/14 「1번 진행해줘」)."""
from __future__ import annotations

import pathlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import paper_trading as PT
from app.workers import paper_trading_worker as W

NOW = datetime(2026, 10, 14, 1, 0, tzinfo=timezone.utc)


def _row(age_min=10, engines=True, version=None, ua=True, naive=False):
    t = NOW - timedelta(minutes=age_min)
    if naive:
        t = t.replace(tzinfo=None)
    return SimpleNamespace(engines={"live": {}} if engines else None, version=PT.VERSION if version is None else version,
                           updated_at=t if ua else None)


def test_skip_only_recent_open_rows():
    open_res = {"status": "OPEN"}
    assert W._open_skip_write(_row(10), open_res, NOW, 3600) is True           # 10분 전 저장 = 건너뜀
    assert W._open_skip_write(_row(61), open_res, NOW, 3600) is False          # 60분 지남 = 저장
    assert W._open_skip_write(_row(10, naive=True), open_res, NOW, 3600) is True


def test_always_write_cases():
    open_res = {"status": "OPEN"}
    assert W._open_skip_write(_row(1), {"status": "CLOSED"}, NOW, 3600) is False   # 마감 = 바로 저장
    assert W._open_skip_write(_row(1), open_res, NOW, 0) is False                  # 끄기 = 예전 동작
    assert W._open_skip_write(_row(1, engines=False), open_res, NOW, 3600) is False
    assert W._open_skip_write(_row(1, version=PT.VERSION - 1), open_res, NOW, 3600) is False
    assert W._open_skip_write(_row(1, ua=False), open_res, NOW, 3600) is False
    assert W._open_skip_write(_row(-5), open_res, NOW, 3600) is False              # 시계 역행 = 저장


def test_worker_wiring():
    src = (pathlib.Path(W.__file__)).read_text(encoding="utf-8")
    assert 'OPEN_WRITE_KEY = "paper_open_write_minutes"' in src
    i_skip = src.index("if _open_skip_write(row, res, now, _open_write_s):")
    i_assign = src.index('row.engines = res["engines"]')
    assert i_skip < i_assign                                                     # 저장 전에 판단
    assert "저장 생략 %d" in src and '"write_skipped": write_skipped' in src
