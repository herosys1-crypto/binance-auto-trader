"""Fix 439 — 🧭 장세 필터: 모든 규칙 가족 공통 — LONG 은 시장폭 < 0.4 · SHORT 은 24h ≥ +10% 일 때만 (진입을 줄이기만 한다)."""
from __future__ import annotations

import json

import tests.test_queue3_rule_families as Q
from app.services import rule_families as RF


def _snap(b):
    return {**Q._PASS_SNAP, "market_breadth": b}


def test_regime_check_long_short_and_unknown():
    db = Q._DB(rf_regime_filter="on")
    assert RF.regime_check(db, "LONG", _snap(0.3), None)["ok"] is True
    assert RF.regime_check(db, "LONG", _snap(0.4), None)["ok"] is False          # 0.4 는 낮음 아님
    assert RF.regime_check(db, "LONG", {}, None)["why"] == "시장폭 모름"           # 모르면 막는다
    assert RF.regime_check(db, "LONG", _snap(True), None)["ok"] is False           # bool 은 숫자 아님
    assert RF.regime_check(db, "SHORT", {}, 10.0)["ok"] is True                    # +10 이상
    assert RF.regime_check(db, "SHORT", {}, 9.99)["ok"] is False
    assert RF.regime_check(db, "SHORT", {}, None)["why"] == "24h 등락 모름"
    db2 = Q._DB(rf_regime_filter="on", rf_long_breadth_max="0.5", rf_short_chg24_min="20")
    assert RF.regime_check(db2, "LONG", _snap(0.45), None)["ok"] is True
    assert RF.regime_check(db2, "SHORT", {}, 15)["ok"] is False


def test_mode_default_on_and_bad_value():
    assert RF.SETTINGS["rf_regime_filter"][0] == "on"
    assert RF.regime_filter_mode(Q._DB(rf_regime_filter="maybe")) == "on"
    assert RF.regime_filter_mode(Q._DB(rf_regime_filter="OFF")) == "off"


def test_worker_on_blocks_out_of_regime(monkeypatch):
    calls = []

    def _create(db, **k):
        calls.append(k["symbol"])
        return type("SI", (), {"id": 500 + len(calls)})()
    monkeypatch.setattr("app.services.surge_ladder_entry.create_surge_position", _create)
    rows = [Q._row(61, "bottom_331", "LONG", ["LIVE_OK"], sym="LOWUSDT", snapshot=_snap(0.3)),
            Q._row(62, "bottom_331", "LONG", ["LIVE_OK"], sym="MIDUSDT", snapshot=_snap(0.5)),
            Q._row(63, "bottom_331", "LONG", ["LIVE_OK"], sym="UNKUSDT", snapshot=Q._PASS_SNAP)]
    _, st = Q._run(monkeypatch, Q._DB(rf_regime_filter="on", rf_bottom_long_mode="on", rf_bottom_long_entry="single"), rows)
    assert calls == ["LOWUSDT"]                                                       # 시장폭 낮음만 진입
    assert st["fam"]["rf_bottom_long"] == {"entered": 1, "regime_filter": 2}


def test_worker_short_needs_pump(monkeypatch):
    calls = []
    monkeypatch.setattr("app.services.surge_ladder_entry.create_surge_position",
                        lambda db, **k: calls.append(k["symbol"]) or type("SI", (), {"id": 9})())
    rows = [Q._row(71, "zone_s4_spike_top_short", "SHORT", ["UP"], sym="PUMPUSDT", chg_24h=35.0),
            Q._row(72, "zone_s4_spike_top_short", "SHORT", ["UP"], sym="FLATUSDT", chg_24h=3.0)]
    _, st = Q._run(monkeypatch, Q._DB(rf_regime_filter="on", rf_zone_s4_mode="on"), rows)
    assert calls == ["PUMPUSDT"] and st["fam"]["rf_zone_s4"].get("regime_filter") == 1


def test_shadow_mode_records_only(monkeypatch):
    Q._no_orders(monkeypatch)
    rows = [Q._row(81, "surge_start_346", "LONG", ["DOWN"], snapshot=_snap(0.7))]
    red, st = Q._run(monkeypatch, Q._DB(rf_regime_filter="shadow"), rows)
    p = json.loads(red.store["rf:shadow:rf_surge_long:AAAUSDT:81"])
    assert p["would_enter"] is True and p["regime_filter"]["ok"] is False and p["regime_filter"]["mode"] == "shadow"
    red2, _ = Q._run(monkeypatch, Q._DB(rf_regime_filter="on"), [Q._row(82, "surge_start_346", "LONG", ["DOWN"], snapshot=_snap(0.7))])
    p2 = json.loads(red2.store["rf:shadow:rf_surge_long:AAAUSDT:82"])
    assert p2["would_enter"] is False and "regime_filter" in p2["blocks"]           # 그림자 가족의 would_enter 도 정확해진다


def test_out_of_range_settings_fall_back():
    db = Q._DB(rf_regime_filter="on", rf_short_chg24_min="0.1", rf_long_breadth_max="1.5")
    assert RF.regime_check(db, "SHORT", {}, 5.0)["ok"] is False and RF.regime_check(db, "SHORT", {}, 5.0)["limit"] == 10.0
    assert RF.regime_check(db, "LONG", _snap(0.5), None)["limit"] == 0.4
