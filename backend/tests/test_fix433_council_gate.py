"""Fix 433 — 운영팀 게이트 기록 전용 단계 (규칙 가족, 진입을 막지 않는다)."""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from app.services import council_gate as CG

APP = pathlib.Path(CG.__file__).resolve().parents[1]
NOW = datetime(2026, 10, 10, 1, 0, tzinfo=timezone.utc)


def _report(at=NOW, cells=None, lo=0.4, hi=0.6):
    cells = cells if cells is not None else [{"rule": "bottom_331", "side": "LONG", "b": "low", "n": 50, "roi": 1.0, "edge": 0.5}]
    return json.dumps({"at": at.isoformat(), "params": {"lo": lo, "hi": hi}, "E_today": {"d": "2026-10-10", "current_b": "low", "cells": cells}})


class _R:
    def __init__(self, raw=None, boom=False):
        self.raw, self.boom, self.kv, self.ttl, self.gets = raw, boom, {}, {}, 0

    def get(self, k):
        self.gets += 1
        if self.boom:
            raise RuntimeError("redis down")
        return self.raw

    def setex(self, k, ttl, v):
        if self.boom:
            raise RuntimeError("redis down")
        self.kv[k], self.ttl[k] = v, ttl


@pytest.fixture(autouse=True)
def _clear_cache():
    CG._cache.update(t=None, v=None)
    yield
    CG._cache.update(t=None, v=None)


def test_in_and_out_of_cells_and_bucket_edges():
    c = CG.parse(_report())
    assert CG.judge(c, "bottom_331", "LONG", 0.39, now=NOW)["in_cells"] is True
    assert CG.judge(c, "bottom_331", "LONG", 0.4, now=NOW)["b"] == "mid"          # lo 포함 = mid
    assert CG.judge(c, "bottom_331", "LONG", 0.6, now=NOW)["b"] == "mid"          # hi 포함 = mid
    assert CG.judge(c, "bottom_331", "LONG", 0.61, now=NOW)["b"] == "high"
    assert CG.judge(c, "bottom_331", "LONG", 0.7, now=NOW)["in_cells"] is False
    assert CG.judge(c, "bottom_331", "SHORT", 0.3, now=NOW)["in_cells"] is False
    assert CG.judge(c, "bottom_331", "LONG", 0.3, now=NOW)["edge"] == 0.5


def test_unknown_cases():
    c = CG.parse(_report())
    assert CG.judge(None, "x", "LONG", 0.3, now=NOW)["in_cells"] is None                       # 성적표 없음
    assert CG.judge(c, "bottom_331", "LONG", None, now=NOW)["in_cells"] is None               # 시장폭 모름
    assert CG.judge(c, "bottom_331", "LONG", 1.5, now=NOW)["in_cells"] is None                # 범위 밖
    old = CG.parse(_report(at=NOW - timedelta(hours=49)))
    j = CG.judge(old, "bottom_331", "LONG", 0.3, now=NOW)
    assert j["in_cells"] is None and j["stale"] is True                                        # 48시간+ = 모름
    assert CG.parse("{not json") is None and CG.parse(json.dumps({"x": 1})) is None


def test_bad_params_fall_back():
    c = CG.parse(_report(lo=0.7, hi=0.5))
    assert (c.lo, c.hi) == (0.4, 0.6)


def test_load_cache_and_redis_failure():
    r = _R(_report())
    assert CG.load(r, now_mono=0.0) is not None and CG.load(r, now_mono=100.0) is not None
    assert r.gets == 1                                                                          # 5분 캐시
    CG.load(r, now_mono=400.0)
    assert r.gets == 2
    CG._cache.update(t=None, v=None)
    assert CG.load(_R(boom=True), now_mono=0.0) is None


def test_mode_on_is_shadow():
    assert CG.mode_of(lambda k: "on") == "shadow"
    assert CG.mode_of(lambda k: "off") == "off"
    assert CG.mode_of(lambda k: None) == "shadow" and CG.mode_of(lambda k: "zzz") == "shadow"
    assert CG.mode_of(lambda k: 1 / 0) == "shadow"


def test_record_and_tally():
    r = _R()
    assert CG.record(r, "rf_bottom_long", 7, {"a": 1}) is True
    assert r.ttl["council:gate:rf_bottom_long:7"] == 60 * 86400
    assert CG.record(_R(boom=True), "f", 1, {}) is False
    stat: dict = {}
    for v in (True, False, None, True):
        CG.tally(stat, {"in_cells": v})
    assert stat["council"] == {"in": 2, "out": 1, "unknown": 1}


def test_worker_never_blocks_on_council():
    src = (APP / "workers" / "rule_family_worker.py").read_text(encoding="utf-8")
    assert "CG.judge(" in src and 'blocks.append("council' not in src
    blk = src[src.index("Fix 433: 운영팀"):src.index("if is_shadow:")]
    assert "blocks.append" not in blk                                     # 기록만
    assert src.count("CG.record(") == 3                                   # 그림자 · 분할 · 단일
    assert "si = _enter_split(" in src and "return si" in src


# ── 실제 워커 사이클 (tests/test_queue3_rule_families 의 틀 재사용) ──
def test_worker_records_without_blocking(monkeypatch):
    import tests.test_queue3_rule_families as Q
    snap_in = {**Q._PASS_SNAP, "market_breadth": 0.3}       # bottom_331 LONG low = 칸 안
    snap_out = {**Q._PASS_SNAP, "market_breadth": 0.8}      # high = 칸 밖
    now = datetime.now(timezone.utc)
    red = Q._Redis()
    red.store["council:latest"] = _report(at=now)
    calls = []

    def _create(db, **k):
        calls.append(k)
        return type("SI", (), {"id": 900 + len(calls)})()
    monkeypatch.setattr("app.services.surge_ladder_entry.create_surge_position", _create)
    rows = [Q._row(41, "bottom_331", "LONG", ["LIVE_OK"], sym="INUSDT", snapshot=snap_in),
            Q._row(42, "bottom_331", "LONG", ["LIVE_OK"], sym="OUTUSDT", snapshot=snap_out)]
    red, st = Q._run(monkeypatch, Q._DB(rf_bottom_long_mode="on", rf_bottom_long_entry="single"), rows, red=red)
    assert st["entered"] == 2 and len(calls) == 2                       # 칸 밖도 진입한다 (기록 전용)
    assert st["council"] == {"in": 1, "out": 1, "unknown": 0}
    a = json.loads(red.store["council:gate:rf_bottom_long:41"])
    b = json.loads(red.store["council:gate:rf_bottom_long:42"])
    assert (a["in_cells"], a["mode"], a["strategy_id"]) == (True, "on", 901)
    assert (b["in_cells"], b["b"], b["strategy_id"]) == (False, "high", 902)


def test_worker_shadow_payload_and_off(monkeypatch):
    import tests.test_queue3_rule_families as Q
    Q._no_orders(monkeypatch)
    red = Q._Redis()
    red.store["council:latest"] = _report(at=datetime.now(timezone.utc))
    rows = [Q._row(51, "surge_start_346", "LONG", ["DOWN"], snapshot={**Q._PASS_SNAP, "market_breadth": 0.3})]
    red, st = Q._run(monkeypatch, Q._DB(), rows, red=red)
    p = json.loads(red.store["rf:shadow:rf_surge_long:AAAUSDT:51"])
    assert p["would_enter"] is True and p["council_gate"]["in_cells"] is False and "council:gate:rf_surge_long:51" in red.store
    CG._cache.update(t=None, v=None)
    red2 = Q._Redis()
    red2.store["council:latest"] = _report(at=datetime.now(timezone.utc))
    rows2 = [Q._row(52, "surge_start_346", "LONG", ["DOWN"], snapshot={**Q._PASS_SNAP, "market_breadth": 0.3})]
    red2, st2 = Q._run(monkeypatch, Q._DB(council_gate_mode="off"), rows2, red=red2)
    assert json.loads(red2.store["rf:shadow:rf_surge_long:AAAUSDT:52"])["council_gate"] is None
    assert not [k for k in red2.store if k.startswith("council:gate:")] and "council" not in st2
