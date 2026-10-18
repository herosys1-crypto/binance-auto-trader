"""🔧 Fix 468 — 볼밴 중단선 시간 초과 청산이 계정 키를 넘긴다 (예전엔 ExecutionService(db) → TypeError 로 청산이 한 번도 안 됨)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace


def _db(rows):
    class DB:
        commits = 0

        def execute(self, _q):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))

        def commit(self):
            DB.commits += 1

        def rollback(self):
            pass
    return DB()


def _row():
    return SimpleNamespace(id=7, symbol="AAAUSDT", side="LONG", current_position_qty=Decimal("-4"),
                           started_at=datetime.now(timezone.utc) - timedelta(hours=10), last_error_message=None)


def test_close_expired_passes_keys(monkeypatch):
    import app.services.execution_service as ES
    from app.workers.bb_mid_line_worker import _close_expired
    got = {}

    class FakeES:
        def __init__(self, db, *, api_key, api_secret, is_testnet=False):     # 실제 생성자와 같은 필수 인자
            got["keys"] = (api_key, api_secret, is_testnet)

        def emergency_close_position(self, sid, *, quantity):
            got["close"] = (sid, quantity)
    monkeypatch.setattr(ES, "ExecutionService", FakeES)
    row = _row()
    n = _close_expired(_db([row]), 4, {"api_key": "k", "api_secret": "s", "is_testnet": False})
    assert n == 1 and got["keys"] == ("k", "s", False) and got["close"] == (7, Decimal("4"))
    assert "Fix287" in row.last_error_message


def test_close_expired_without_keys_skips(monkeypatch):
    import app.services.execution_service as ES
    from app.workers.bb_mid_line_worker import _close_expired

    def boom(*a, **k):
        raise AssertionError("키 없이 주문 객체를 만들면 안 된다")
    monkeypatch.setattr(ES, "ExecutionService", boom)
    assert _close_expired(_db([_row()]), 4, None) == 0


def test_real_constructor_requires_keys():
    import inspect
    from app.services.execution_service import ExecutionService
    ps = inspect.signature(ExecutionService.__init__).parameters
    assert ps["api_key"].default is inspect.Parameter.empty and ps["api_secret"].default is inspect.Parameter.empty
