"""Fix 488 — 방향 엔진 v1 그림자: 판정 함수 · 지정가 체결 · 기준선 행 지정가 엔진."""
from datetime import datetime, timedelta, timezone

from app.services import direction_engine as DE
from app.services import paper_trading as PT

D = datetime(2026, 11, 13, tzinfo=timezone.utc)


def _rows(side, n, roi, hours_before=1.0):
    return [(side, D - timedelta(hours=hours_before), roi) for _ in range(n)]


def test_picks_worse_side_contrarian():
    r = DE.decide(_rows("LONG", 25, 3.0) + _rows("SHORT", 25, -2.0), D)
    assert r["side"] == "SHORT"          # SHORT 가 졌다 → SHORT
    r = DE.decide(_rows("LONG", 25, -3.0) + _rows("SHORT", 25, 2.0), D)
    assert r["side"] == "LONG"


def test_rows_closed_at_or_after_day_start_are_ignored():
    base = _rows("LONG", 25, 3.0) + _rows("SHORT", 25, -2.0)
    future = [("SHORT", D, 99.0)] * 500 + [("LONG", D + timedelta(hours=3), -99.0)] * 500
    assert DE.decide(base + future, D)["side"] == DE.decide(base, D)["side"] == "SHORT"


def test_rows_older_than_window_are_ignored():
    base = _rows("LONG", 25, 3.0) + _rows("SHORT", 25, -2.0)
    old = [("SHORT", D - timedelta(hours=25), 99.0)] * 500
    assert DE.decide(base + old, D, window_h=24)["side"] == "SHORT"


def test_too_few_or_tie_is_none():
    assert DE.decide(_rows("LONG", 19, 3.0) + _rows("SHORT", 25, -2.0), D, min_n=20)["side"] is None
    assert DE.decide(_rows("LONG", 25, 1.0) + _rows("SHORT", 25, 1.0), D)["side"] is None
    assert DE.decide([], D)["side"] is None


def test_tiny_difference_not_rounded_to_tie():
    r = DE.decide(_rows("LONG", 20, 0.00001) + _rows("SHORT", 20, 0.00002), D)
    assert r["side"] == "LONG"


def test_set_limit_params_inf_nan_overflow_default():
    for bad in ("inf", "1e309", "nan", "-inf"):
        PT.set_limit_params(bad, bad)
        assert PT._LMT["valid"] == PT.LMT_VALID_BARS and PT._LMT["maker"] == PT.MAKER_FEE_PCT
    PT.set_limit_params(None, None)


def test_bad_roi_values_skipped():
    rows = _rows("LONG", 25, 3.0) + _rows("SHORT", 25, -2.0) + [("LONG", D - timedelta(hours=1), "nan"), ("SHORT", D - timedelta(hours=1), None)]
    r = DE.decide(rows, D)
    assert r["n_long"] == 25 and r["n_short"] == 25 and r["side"] == "SHORT"


def _bar(o, h, l, c):
    return [0, o, h, l, c]


def test_limit_fill_needs_trade_through():
    bars = [_bar(100, 101, 100, 100.5), _bar(100, 100.2, 99.9, 100)]
    assert PT.limit_fill("LONG", 100.0, bars, 1) is None        # 저가 = 가격 (닿기만) → 미체결
    assert PT.limit_fill("LONG", 100.0, bars, 2) == 1           # 2번째 봉에서 뚫음
    assert PT.limit_fill("SHORT", 100.0, bars, 1) == 0          # 고가 101 > 100


def test_run_limit_nofill_is_done_and_has_no_roi():
    PT.set_limit_params(1, 0.02)
    e = PT.run_limit("LONG", 100.0, [_bar(100, 101, 100, 100.5)] * 3)
    assert e["filled"] is False and e["done"] is True and "roi" not in e


def test_set_limit_params_out_of_range_defaults():
    PT.set_limit_params(99, -1)
    assert PT._LMT["valid"] == PT.LMT_VALID_BARS and PT._LMT["maker"] == PT.MAKER_FEE_PCT
    PT.set_limit_params("x", "y")
    assert PT._LMT["valid"] == PT.LMT_VALID_BARS
    PT.set_limit_params(4, 0.01)
    assert PT._LMT["valid"] == 4 and PT._LMT["maker"] == 0.01
    PT.set_limit_params(None, None)


def test_lmt_cost_default_is_024():
    PT.set_costs(None, None)
    PT.set_limit_params(None, None)
    assert abs(PT.lmt_cost_roi() - 0.24) < 1e-9
    assert abs(PT._COST[0] - 0.40) < 1e-9


def test_manage_trade_adds_lmt_engine_only_for_baseline():
    import inspect
    src = inspect.getsource(PT.manage_trade)
    assert 'str(trade.get("rule") or "") in BASELINE_KEYS' in src and "run_limit(side, entry, after)" in src
