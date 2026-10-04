"""Fix 417 — reconcile 의 실자금 경로 결함 2건 (운영 실측으로 확인).

① 단계 승격: 2단계+ 는 거래소 포지션이 「이전 단계 합」이라 != 0 이 당연한데, v133 자동 회복이 그걸 체결로 보고
   미체결 LIMIT 단계를 STAGE_N_OPEN 으로 올렸다 (2단계+ 자동 회복 22건 중 미체결 승격 3 · 체결 전 승격 3, #4527 POWERUSDT 4단계 포함).
   → 그 단계 ENTRY 주문의 체결 증거(DB 체결 수량/상태 → 없으면 거래소 주문 조회)가 있을 때만 승격.
② STOPPING 갇힘 감지: 기준 시각 updated_at 을 같은 reconcile 사이클이 미실현 손익 등을 쓰며 지금으로 바꿔
   포지션이 남은 갇힘이 영영 5분을 못 넘었다 → 사이클 시작 스냅샷 + Redis 「처음 본 시각」.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import itertools
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

from app.models.order import Order
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_stage_plan import StrategyStagePlan
from app.workers import reconcile_worker as RW
from app.workers.reconcile_worker import _do_reconcile


def _plans(db, sid, triggered):
    for stage_no, trig in triggered:
        db.add(StrategyStagePlan(
            strategy_instance_id=sid, stage_no=stage_no, side="LONG",
            trigger_mode="PRICE_DOWN_PCT", trigger_percent=Decimal("5"),
            trigger_price=Decimal("100"), planned_capital=Decimal("10"),
            planned_qty=Decimal("1"), is_triggered=trig,
        ))


_seq = itertools.count(1)


def _order(db, sid, stage_no, *, status="NEW", executed="0", ex_id=111):
    n = next(_seq)
    db.add(Order(
        strategy_instance_id=sid, stage_no=stage_no, purpose="ENTRY", symbol="BTCUSDT", side="BUY",
        position_side="LONG", order_type="LIMIT", time_in_force="GTC", client_order_id=f"t417-{n}",
        exchange_order_id=ex_id, price=Decimal("100"), orig_qty=Decimal("1"),
        executed_qty=Decimal(executed), status=status,
    ))


@pytest.fixture
def stage2_pending(db_session, make_strategy, fake_binance):
    s = make_strategy(symbol_str="BTCUSDT", side="LONG", status="STAGE2_OPEN_PENDING",
                      current_position_qty=Decimal("1"), current_stage=2)
    _plans(db_session, s.id, [(1, True), (2, False)])
    db_session.commit()
    fake_binance.set_position("BTCUSDT", position_amt="1", entry_price="100", mark_price="99", position_side="LONG")
    return s


def _status(db, sid):
    db.expire_all()
    return db.get(StrategyInstance, sid).status


def _recovered(db, sid):
    return db.query(RiskEvent).filter(RiskEvent.strategy_instance_id == sid,
                                      RiskEvent.event_type == "RECONCILE_TRIGGER_RECOVERED").count()


def test_unfilled_limit_not_promoted(db_session, stage2_pending, fake_binance, identity_decrypt, patched_sessionlocal, monkeypatch):
    """운영 龙虾USDT 유형: 2단계 LIMIT 체결 0 → 승격 금지 (거래소 조회도 미체결)."""
    _order(db_session, stage2_pending.id, 2)
    db_session.commit()
    monkeypatch.setattr(fake_binance, "get_order", lambda self, **kw: {"executedQty": "0", "status": "NEW"}, raising=False)
    _do_reconcile(identity_decrypt)
    assert _status(db_session, stage2_pending.id) == "STAGE2_OPEN_PENDING"
    assert _recovered(db_session, stage2_pending.id) == 0


def test_stream_missed_fill_is_recovered_via_exchange(db_session, stage2_pending, fake_binance, identity_decrypt, patched_sessionlocal, monkeypatch):
    """v133 의 원래 목적은 유지: DB 는 NEW(스트림 놓침)지만 거래소가 체결이라고 하면 승격 + 회복 이벤트."""
    _order(db_session, stage2_pending.id, 2)
    db_session.commit()
    monkeypatch.setattr(fake_binance, "get_order", lambda self, **kw: {"executedQty": "1", "status": "FILLED"}, raising=False)
    _do_reconcile(identity_decrypt)
    assert _status(db_session, stage2_pending.id) == "STAGE2_OPEN"
    assert _recovered(db_session, stage2_pending.id) == 1


def test_db_fill_evidence_promotes_without_exchange_call(db_session, stage2_pending, fake_binance, identity_decrypt, patched_sessionlocal, monkeypatch):
    _order(db_session, stage2_pending.id, 2, status="PARTIALLY_FILLED", executed="0.4")
    db_session.commit()
    monkeypatch.setattr(fake_binance, "get_order", lambda self, **kw: pytest.fail("DB 증거가 있으면 거래소 조회 불필요"), raising=False)
    _do_reconcile(identity_decrypt)
    assert _status(db_session, stage2_pending.id) == "STAGE2_OPEN"


def test_exchange_query_failure_keeps_pending(db_session, stage2_pending, fake_binance, identity_decrypt, patched_sessionlocal, monkeypatch):
    _order(db_session, stage2_pending.id, 2)
    db_session.commit()

    def boom(self, **kw):
        raise RuntimeError("timeout")
    monkeypatch.setattr(fake_binance, "get_order", boom, raising=False)
    _do_reconcile(identity_decrypt)
    assert _status(db_session, stage2_pending.id) == "STAGE2_OPEN_PENDING"


def test_evidence_values_directly(db_session, stage2_pending):
    """감사 지적: 통합 테스트만으로는 not_filled/unknown 구분이 안 보인다 → 반환값을 직접 확인."""
    sid = stage2_pending.id
    assert RW._stage_fill_evidence(db_session, stage2_pending, 2, None) == "no_order"
    _order(db_session, sid, 2, ex_id=501)
    db_session.commit()
    calls = []

    class Cli:
        def __init__(self, filled_ids):
            self.filled = filled_ids

        def get_order(self, *, symbol, order_id):
            calls.append(order_id)
            return {"executedQty": "1" if order_id in self.filled else "0"}
    assert RW._stage_fill_evidence(db_session, stage2_pending, 2, Cli(set())) == "not_filled"
    assert RW._stage_fill_evidence(db_session, stage2_pending, 2, None) == "unknown"
    # 재주문: 앞선 주문(501)이 놓친 체결, 새 주문(502)은 미체결 → 둘 다 물어 filled
    _order(db_session, sid, 2, ex_id=502)
    db_session.commit()
    calls.clear()
    assert RW._stage_fill_evidence(db_session, stage2_pending, 2, Cli({501})) == "filled"
    assert 501 in calls                                   # 체결을 찾으면 거기서 멈춘다(순서는 생성 시각)
    assert RW._stage_fill_evidence(db_session, stage2_pending, 1, None) == "stage1"


def test_evidence_never_raises():
    class Boom:
        def execute(self, *a, **k):
            raise RuntimeError("db gone")

        @property
        def no_autoflush(self):
            import contextlib
            return contextlib.nullcontext()
    assert RW._stage_fill_evidence(Boom(), NS(id=1, symbol="X"), 2, None) == "unknown"


def test_no_order_record_keeps_pending(db_session, stage2_pending, identity_decrypt, patched_sessionlocal):
    _do_reconcile(identity_decrypt)
    assert _status(db_session, stage2_pending.id) == "STAGE2_OPEN_PENDING"


def test_stage1_recovery_unchanged(db_session, make_strategy, fake_binance, identity_decrypt, patched_sessionlocal):
    """1단계는 기존 v133 그대로 — 포지션이 있으면 그게 1단계 체결이다."""
    s = make_strategy(symbol_str="BTCUSDT", side="LONG", status="STAGE1_OPEN_PENDING",
                      current_position_qty=Decimal("0"), current_stage=1)
    _plans(db_session, s.id, [(1, False)])
    db_session.commit()
    fake_binance.set_position("BTCUSDT", position_amt="1", entry_price="100", mark_price="99", position_side="LONG")
    _do_reconcile(identity_decrypt)
    assert _status(db_session, s.id) == "STAGE1_OPEN"


# ── ② STOPPING 기준 시각 ──────────────────────────────────────────────────
class FakeRedis:
    def __init__(self):
        self.d = {}

    def set(self, k, v, nx=False, ex=None):
        if nx and k in self.d:
            return False
        self.d[k] = v
        return True

    def get(self, k):
        return self.d.get(k)

    def delete(self, *keys):
        for k in keys:
            self.d.pop(k, None)


NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def test_stopping_since_uses_snapshot_before_cycle_updates():
    old = NOW - timedelta(minutes=10)
    assert RW._stopping_since(None, 7, NOW, {7: old}) == old           # Redis 없어도 이 사이클 스냅샷으로


def test_stopping_since_remembers_first_seen_across_cycles():
    r = FakeRedis()
    first = NOW - timedelta(minutes=3)
    assert RW._stopping_since(r, 7, first) == first                          # 처음 본 사이클
    later = NOW + timedelta(minutes=4)
    assert RW._stopping_since(r, 7, later) == first                   # updated_at 이 계속 밀려도 처음 시각 유지


def test_stopping_since_redis_error_falls_back():
    class Bad:
        def set(self, *a, **k):
            raise RuntimeError("down")
    assert RW._stopping_since(Bad(), 7, NOW) == NOW


def test_snapshot_only_stopping_rows_and_seeds_redis():
    r = FakeRedis()
    old = NOW - timedelta(minutes=9)
    rows = [(NS(id=1, status="STOPPING", updated_at=old.replace(tzinfo=None)), None),
            (NS(id=2, status="STAGE1_OPEN", updated_at=old), None)]
    snap = RW._snapshot_stopping(rows, r)
    assert snap == {1: old} and f"{RW.STOPPING_FIRST_SEEN_REDIS_PREFIX}1" in r.d and len(r.d) == 1


def test_stuck_with_live_position_detected_even_when_pnl_moves(db_session, make_strategy, fake_binance, identity_decrypt, patched_sessionlocal, monkeypatch):
    """#77 PHB 유형(가장 위험): STOPPING + 거래소 포지션 잔재 + 미실현 손익이 매 사이클 바뀜 → 그래도 감지."""
    from sqlalchemy import update
    s = make_strategy(symbol_str="PHBUSDT", side="LONG", status="STOPPING",
                      current_position_qty=Decimal("100"), avg_entry_price=Decimal("0.06"))
    fake_binance.set_position("PHBUSDT", position_amt="100", entry_price="0.06", mark_price="0.0612",
                              position_side="LONG", unrealized_pnl="0.12")
    db_session.execute(update(StrategyInstance).where(StrategyInstance.id == s.id)
                       .values(updated_at=datetime.now(timezone.utc) - timedelta(minutes=10)))
    db_session.commit()
    _do_reconcile(identity_decrypt)
    assert _status(db_session, s.id) == "MANUAL_CLEANUP_REQUIRED"


def test_reentering_stopping_starts_fresh_count():
    """감사 지적: STOPPING 에서 빠졌다 다시 들어오면 옛 「처음 본 시각」을 쓰면 안 된다 (즉시 오탐)."""
    r = FakeRedis()
    old = NOW - timedelta(hours=2)
    RW._snapshot_stopping([(NS(id=5, status="STOPPING", updated_at=old), None)], r)
    RW._snapshot_stopping([(NS(id=5, status="STAGE1_OPEN", updated_at=NOW), None)], r)     # 빠져나감 → 키 정리
    assert f"{RW.STOPPING_FIRST_SEEN_REDIS_PREFIX}5" not in r.d
    snap = RW._snapshot_stopping([(NS(id=5, status="STOPPING", updated_at=NOW), None)], r)
    assert RW._stopping_since(r, 5, NOW, snap) == NOW


def test_detector_multi_cycle_with_moving_updated_at(monkeypatch):
    """운영 결함 재현: updated_at 이 매 사이클 「지금」으로 밀려도 처음 본 시각부터 5분이 지나면 감지한다."""
    r = FakeRedis()
    t0 = NOW
    for minute in (0, 2, 4):                         # 2분 주기 — 5분 미만
        t = t0 + timedelta(minutes=minute)
        snap = RW._snapshot_stopping([(NS(id=9, status="STOPPING", updated_at=t), None)], r)
        since = RW._stopping_since(r, 9, t, snap)
        assert (t - since).total_seconds() < RW.STOPPING_STUCK_THRESHOLD_SECONDS
    t = t0 + timedelta(minutes=6)
    snap = RW._snapshot_stopping([(NS(id=9, status="STOPPING", updated_at=t), None)], r)
    assert (t - RW._stopping_since(r, 9, t, snap)).total_seconds() >= RW.STOPPING_STUCK_THRESHOLD_SECONDS
