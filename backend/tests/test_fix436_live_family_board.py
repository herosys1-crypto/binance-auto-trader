"""Fix 436 — 운영팀 카드의 가족별 실거래 (시스템 몫 · 사람 💉 추가 몫 · 손실 차단기). 읽기 전용."""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

from app.services import live_family_board as LB

NOW = datetime(2026, 10, 10, 6, 0, tzinfo=timezone.utc)
APP = pathlib.Path(LB.__file__).resolve().parents[1]


class _DB:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, stmt):
        return NS(all=lambda: self.rows)

    def get(self, _m, key):
        return None


def _row(sid, side, status, pnl, stype, name="auto", origin=None, days=1):
    return (sid, side, status, pnl, NOW - timedelta(days=days), origin, stype, name)


def test_build_splits_and_orders(monkeypatch):
    from app.services import family_loss_breaker as FB
    from app.services import human_share as HS
    rows = [_row(1, "LONG", "STOPPED", -27.83, "rf_bottom_331"),
            _row(2, "LONG", "STAGE1_OPEN", 0.0, "rf_bottom_331"),
            _row(3, "SHORT", "STOPPED", 1.5, "rf_zone_s4"),
            _row(4, "LONG", "STOPPED", 500.0, "manual", name="수동", origin="manual_modal")]       # 사람 전략 = 제외
    monkeypatch.setattr(HS, "split_for", lambda db, items: {
        1: {"system": -3.6, "human": -24.23, "unknown": 0.0, "human_n": 1},
        3: {"system": 1.5, "human": 0.0, "unknown": 0.0, "human_n": 0}})
    monkeypatch.setattr(FB, "all_states", lambda db, keys, now=None: {k: {"pnl": -3.0, "limit": 30.0, "days": 7, "tripped": False} for k in keys})
    d = LB.build(_DB(rows), now=NOW)
    by = {f["key"]: f for f in d["families"]}
    b = by["rf_bottom_long"]
    assert (b["n"], b["closed"], b["open"]) == (2, 1, 1)
    assert (b["system"], b["human"], b["human_n"], b["realized"]) == (-3.6, -24.23, 1, -27.83)
    assert b["breaker"]["limit"] == 30.0 and by["rf_zone_s4"]["system"] == 1.5
    assert all(f["key"] for f in d["families"]) and "manual" not in json.dumps(d, default=str).lower().replace("human", "")
    assert d["total"]["human"] == -24.23
    json.dumps(d, default=str)


def test_on_family_without_trades_is_listed_and_breaker_failure_safe(monkeypatch):
    from app.services import family_loss_breaker as FB
    from app.services import rule_families as RF
    monkeypatch.setattr(RF, "mode_of", lambda db, k: "on" if k == "rf_wick_long" else "shadow")
    monkeypatch.setattr(FB, "all_states", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db")))
    d = LB.build(_DB([]), now=NOW)
    assert [f["key"] for f in d["families"]] == ["rf_wick_long"]
    assert d["families"][0]["mode"] == "on" and d["families"][0]["breaker"] is None and d["breaker_ok"] is False


def test_api_and_card_wiring():
    api = (APP / "api" / "v1" / "strategy_council.py").read_text(encoding="utf-8")
    assert '@router.get("/live-families")' in api and "LIVE_TTL = 300" in api and "LB.build(db)" in api
    assert 'data.get("breaker_ok", True)' in api                       # 차단기 실패 결과는 캐시 안 함
    js = (APP / "static" / "js" / "strategy-council.js").read_text(encoding="utf-8")
    assert "/strategy-council/live-families" in js and "시스템 몫" in js
    html = (APP / "static" / "index.html").read_text(encoding="utf-8")
    assert "strategy-council.js?v=fix436" in html
    src = (APP / "services" / "live_family_board.py").read_text(encoding="utf-8")
    assert "commit" not in src and "setex" not in src


def test_split_failure_goes_to_unknown(monkeypatch):
    from app.services import family_loss_breaker as FB
    from app.services import human_share as HS
    monkeypatch.setattr(HS, "split_for", lambda db, items: (_ for _ in ()).throw(RuntimeError("db")))
    monkeypatch.setattr(FB, "all_states", lambda db, keys, now=None: {})
    d = LB.build(_DB([_row(1, "LONG", "STOPPED", -5.0, "rf_bottom_331")]), now=NOW)
    f = {x["key"]: x for x in d["families"]}["rf_bottom_long"]
    assert (f["system"], f["unknown"], f["realized"]) == (0.0, -5.0, -5.0)
