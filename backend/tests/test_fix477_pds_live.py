"""Fix 477 실주문 경로 — 진입(가짜 서비스) · 정리 판정 · 정리 워커(가짜 세션)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

from app.services import pump_dump_short as P
from app.services import pump_dump_short_live as L

NOW = datetime(2026, 10, 22, 0, 20, tzinfo=timezone.utc)
ENTRY_DAY = int(datetime(2026, 10, 21, tzinfo=timezone.utc).timestamp() * 1000)     # 10/21 봉 → 10/22 00:00 마감


def _cand(sym, whale=False, surge=50.0, day=ENTRY_DAY):
    return {"symbol": sym, "whale": whale, "surge_pct": surge, "entry_ref": 1.0, "half": 0.8, "entry_day": day, "surge_day": day - 86400000}


class _DB:
    def __init__(self):
        self.added, self.commits, self.rollbacks = [], 0, 0

    def add(self, x):
        self.added.append(x)

    def flush(self):
        for i, x in enumerate(self.added):
            if getattr(x, "id", None) is None:
                x.id = 100 + i

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, *a, **k):
        pass


class _Svc:
    made: list = []
    fail: dict = {}

    def __init__(self, db):
        pass

    def create_strategy_instance(self, **kw):
        if kw["symbol"] in _Svc.fail:
            raise _Svc.fail[kw["symbol"]]
        si = NS(id=len(_Svc.made) + 1, **kw)
        _Svc.made.append(si)
        return si


@pytest.fixture(autouse=True)
def _reset():
    _Svc.made, _Svc.fail = [], {}


def _p(**kw):
    return {**P.params_from(), "mode": "on", **kw}


def test_off_or_shadow_opens_nothing():
    for mode in ("off", "shadow"):
        st = L.open_positions(_DB(), [_cand("AUSDT")], _p(mode=mode), svc_factory=_Svc, active_fn=lambda db: [], now=NOW)
        assert st["opened"] == [] and _Svc.made == []


def test_concurrency_dup_order_and_settings():
    active = [NS(symbol="BUSDT"), NS(symbol="CUSDT")]
    cands = [_cand("XUSDT", surge=40), _cand("BUSDT", whale=True), _cand("WUSDT", whale=True, surge=35), _cand("YUSDT", surge=90)]
    st = L.open_positions(_DB(), cands, _p(max_concurrent=3), svc_factory=_Svc, active_fn=lambda db: active, now=NOW)
    assert [o["symbol"] for o in st["opened"]] == ["WUSDT"]              # 🐋 먼저 · 이미 보유(B) 건너뜀 · 상한 3 - 활성 2 = 1
    si = _Svc.made[0]
    assert si.side == "SHORT" and si.leverage_override == 1 and si.capital_management_mode == "stage_ladder" and si.entry_origin == "auto_pds"
    assert si.force_sl_roi_override == Decimal("30.0") and si.tp1_pct_override == Decimal("0") and si.entry_signal == "pds"
    assert si.entry_signal_meta["plan"] == "a" and si.entry_signal_meta["half"] == 0.8 and si.entry_signal_meta["hold_days"] == 10
    assert st["skipped"] == {"이미 보유": 1, "동시 상한": 2}


def test_entry_window():
    late = L.open_positions(_DB(), [_cand("AUSDT")], _p(), svc_factory=_Svc, active_fn=lambda db: [], now=NOW + timedelta(hours=7))
    early = L.open_positions(_DB(), [_cand("AUSDT")], _p(), svc_factory=_Svc, active_fn=lambda db: [], now=NOW - timedelta(hours=1))
    assert late["opened"] == [] and early["opened"] == [] and late["skipped"] == {"진입 창 밖": 1}


def test_template_kwargs_plans():
    a = L.template_kwargs(P.PLANS["a"], _p(scale=0.5), "AUSDT", NOW)
    assert [a[f"stage{i}_capital"] for i in (1, 2, 3, 4)] == [Decimal("5.0"), Decimal("150.0"), Decimal("300.0"), Decimal("1000.0")]
    assert a["stage2_trigger_percent"] == a["stage4_trigger_percent"] == Decimal("15.0") and a["leverage"] == 1
    assert a["stages_config"]["last_stage_trigger_mode"] == "PRICE_UP_PCT" and a["stages_config"]["trigger_percents"] == [None, 15.0, 15.0, 15.0]
    b = L.template_kwargs(P.PLANS["b"], _p(), "BUSDT", NOW)
    assert b["stage4_capital"] is None and b["stage3_capital"] == Decimal("1000.0") and b["stage3_trigger_percent"] == Decimal("20.0")
    assert b["strategy_type"] == "pump_dump_short" and b["name"].startswith("PDS_B_BUSDT_")


def test_gate_error_skips_and_continues():
    from app.services import auto_family_registry as AF
    msg = "가족 하루 최대"
    _Svc.fail = {"AUSDT": ValueError(msg)}
    orig = AF.is_limit_error
    AF.is_limit_error = lambda e: str(e) == msg
    try:
        db = _DB()
        st = L.open_positions(db, [_cand("AUSDT", surge=99), _cand("BUSDT")], _p(), svc_factory=_Svc, active_fn=lambda db: [], now=NOW)
    finally:
        AF.is_limit_error = orig
    assert [o["symbol"] for o in st["opened"]] == ["BUSDT"] and st["skipped"] == {"생성 게이트": 1} and db.rollbacks == 1


def test_exit_decision():
    meta = {"half": 0.8, "hold_days": 10, "opened_at": NOW.isoformat()}
    assert L.exit_decision(meta, 1.0, 0.79, NOW)[:2] == (True, "익절")             # min(0.8, 0.995) = 0.8
    assert L.exit_decision(meta, 0.7, 0.70, NOW)[:2] == (False, "유지")            # min(0.8, 0.6965) = 0.6965
    assert L.exit_decision(meta, 0.7, 0.69, NOW)[:2] == (True, "익절")
    assert L.exit_decision(meta, 1.0, 1.2, NOW + timedelta(days=10))[:2] == (True, "기한")
    assert L.exit_decision({"opened_at": NOW.isoformat()}, 1.0, 0.99, NOW)[2] == pytest.approx(0.995)
    assert L.exit_decision(meta, None, 0.5, NOW)[:2] == (False, "모름")


def _si(**kw):
    base = dict(id=7, symbol="AUSDT", avg_entry_price=Decimal("1.0"), current_position_qty=Decimal("-10"), exchange_account_id=1,
                entry_signal_meta={"half": 0.8, "hold_days": 10, "opened_at": NOW.isoformat(), "keep": 1}, last_error_message=None)
    base.update(kw)
    return NS(**base)


def test_run_exit_once_paths():
    db = _DB()
    si = _si()
    closed = []
    st = L.run_exit_once(db, now=NOW, rows=[si], mark_price_of=lambda s, c: 0.75, closer=lambda d, s: closed.append(s.id))
    assert closed == [7] and st["closed"] == 1 and si.entry_signal_meta["exit_done"]["why"] == "익절" and si.entry_signal_meta["keep"] == 1
    # 이미 끝난 건 = 대상 아님
    assert L.run_exit_once(db, now=NOW, rows=[si], mark_price_of=lambda s, c: 0.1, closer=lambda d, s: closed.append(0))["targets"] == 0
    # 포지션 없음
    si2 = _si(id=8)

    def nopos(d, s):
        raise ValueError("Exchange has no SHORT position for AUSDT; cancelled pending orders and marked STOPPED.")
    st2 = L.run_exit_once(db, now=NOW, rows=[si2], mark_price_of=lambda s, c: 0.7, closer=nopos)
    assert st2["closed"] == 1 and si2.entry_signal_meta["exit_done"]["no_position"] is True
    # 현재가 실패 = 익절은 못 봄 · 기한 전이면 건너뜀, 기한 지났으면 그래도 정리
    si3 = _si(id=9)

    def boom(s, c):
        raise RuntimeError("timeout")
    st3 = L.run_exit_once(db, now=NOW + timedelta(days=3), rows=[si3], mark_price_of=boom, closer=lambda d, s: closed.append(9))
    assert st3["unknown"] == 1 and 9 not in closed and "exit_done" not in si3.entry_signal_meta
    st3b = L.run_exit_once(db, now=NOW + timedelta(days=11), rows=[si3], mark_price_of=boom, closer=lambda d, s: closed.append(9))
    assert st3b["closed"] == 1 and 9 in closed and si3.entry_signal_meta["exit_done"]["why"] == "기한"
    # 「does not match」 같은 다른 ValueError 는 포지션 없음이 아니다 = 표식 없이 재시도
    si5 = _si(id=11)

    def side_err(d, s):
        raise ValueError("Order's position side does not match user's setting.")
    st5 = L.run_exit_once(db, now=NOW, rows=[si5], mark_price_of=lambda s, c: 0.7, closer=side_err)
    assert st5["errors"] == 1 and "exit_done" not in si5.entry_signal_meta
    # 다른 예외 = rollback, 표식 없음
    si4 = _si(id=10)

    def err(d, s):
        raise RuntimeError("exchange 500")
    rb = db.rollbacks
    st4 = L.run_exit_once(db, now=NOW, rows=[si4], mark_price_of=lambda s, c: 0.7, closer=err)
    assert st4["errors"] == 1 and db.rollbacks == rb + 1 and "exit_done" not in si4.entry_signal_meta


@pytest.mark.parametrize("key", ["a", "b"])
def test_engine_stage_prices_match_plan(key):
    """실제 계산기가 사다리 가격을 「이어서 +g%」 로 만드는지 · 마지막 단계도 가격(청산가 기반 아님) · 수량 = 증거금 × 레버 / 가격."""
    from app.services.strategy_calculator import StrategyCalculator, SymbolRule
    plan = P.PLANS[key]
    kw = L.template_kwargs(plan, _p(), "AUSDT", NOW)
    calc = StrategyCalculator(SymbolRule(symbol="AUSDT", tick_size=Decimal("0.00001"), step_size=Decimal("0.001"), min_qty=Decimal("0.001"),
                                         price_precision=5, quantity_precision=3))
    pv = calc.calculate_preview(symbol="AUSDT", side="SHORT", start_price=Decimal("1.00000"), stages_config=kw["stages_config"],
                                leverage=1, total_capital=kw["total_capital"], tp1_percent=kw["tp1_percent"], tp2_percent=kw["tp2_percent"],
                                tp3_percent=kw["tp3_percent"], stop_loss_percent_of_capital=kw["stop_loss_percent_of_capital"])
    prices = [float(st.trigger_price) for st in pv.stages]
    want = list(plan.mults())
    assert len(prices) == len(want) and all(abs(a - b) < 2e-5 for a, b in zip(prices, want)), (prices, want)
    assert [float(st.planned_capital) for st in pv.stages] == list(plan.margins)


def test_tag_failure_stops_before_stage1(monkeypatch):
    class BadDB(_DB):
        def commit(self):
            raise RuntimeError("db down")
    stopped = []
    monkeypatch.setattr(L, "_stop_untagged", lambda si: stopped.append(si.symbol))
    st = L.open_positions(BadDB(), [_cand("AUSDT")], _p(), svc_factory=_Svc, active_fn=lambda db: [], now=NOW)
    assert st["opened"] == [] and stopped == ["AUSDT"] and st["skipped"] == {"표식 실패 → 멈춤": 1}


def test_no_position_error_precise():
    assert L.no_position_error(ValueError("Exchange has no SHORT position for X; cancelled"))
    assert not L.no_position_error(ValueError("Order's position side does not match user's setting."))
    assert not L.no_position_error(ValueError("Cannot close position: unknown"))
