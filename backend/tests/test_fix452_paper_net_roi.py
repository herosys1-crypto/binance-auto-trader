"""💸 Fix 452 — 가상 엔진 순수익(수수료·슬리피지) 따로 기록 (사장님 10/14 「1번 진행해줘」)."""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

from app.services import paper_trading as PT
from app.services.chart_learning import MS_15M, MS_1H

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reset():
    PT.set_costs(None, None)
    yield
    PT.set_costs(None, None)


def test_cost_default_and_settings():
    assert PT.cost_roi() == 0.4                                   # 2 × (0.05 + 0.05) × 레버 2
    assert PT.set_costs("0.02", "0.0") == 0.08
    assert PT.set_costs("x", "5") == 0.4                          # 이상한 값·범위 밖 = 기본
    assert PT.set_costs(None, None) == 0.4


def test_add_net_keeps_gross_roi():
    eng = {"live": {"roi": 10.0}, "house": {"roi": -2.5}, "bad": {"roi": True}, "none": {}}
    PT.add_net(eng)
    assert eng["live"] == {"roi": 10.0, "roi_net": 9.6}
    assert eng["house"]["roi_net"] == -2.9
    assert "roi_net" not in eng["bad"] and "roi_net" not in eng["none"]


def test_manage_trade_records_net_for_every_engine():
    start = 1_760_000_000_000 // MS_1H * MS_1H
    allk = []
    for i in range(240):
        p = 100 + i * 0.05
        allk.append([start + i * MS_15M, p, p + 0.4, p - 0.4, p + 0.02, 10.0])
    s = PT.Series.build(allk, [])
    j = 100
    m = PT.manage_trade({"side": "LONG", "entry_price": allk[j][4], "entry_bar_ts": int(allk[j][0])}, s)
    for name, e in m["engines"].items():
        assert e["roi_net"] == pytest.approx(e["roi"] - 0.4, abs=1e-4), name


def test_verdict_net_column_and_fallback():
    p = ROOT / "scripts" / "entry_condition_study" / "verdict_2026_10_25.py"
    spec = importlib.util.spec_from_file_location("verdict_452", p)
    V = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(V)
    assert V.net_of({"roi": 5.0}) == pytest.approx(4.6)          # 옛 행 = roi − 0.4
    assert V.net_of({"roi": 5.0, "roi_net": 4.0}) == 4.0
    assert V.net_of({"roi": None}) is None
    from datetime import date
    rows = [{"d": date(2026, 10, 12), "side": "LONG", "symbol": "A", "ts": 1, "roi": 2.0}]
    ev = V.evaluate(rows, {})
    assert ev["net"] == pytest.approx(1.6) and "💸 순수익" in p.read_text(encoding="utf-8")
    assert V.line("x", ev).endswith("| +1.60 |")


def test_worker_sets_costs_each_cycle():
    src = (ROOT / "app" / "workers" / "paper_trading_worker.py").read_text(encoding="utf-8")
    assert 'PT.set_costs(_setting(db, "paper_fee_pct"), _setting(db, "paper_slip_pct"))' in src
