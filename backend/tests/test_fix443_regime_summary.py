"""Fix 443 — 운영팀 성적표 텔레그램에 「장세 필터 24시간 요약」 (읽기 전용)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

from app.workers import strategy_council_worker as W

NOW = datetime(2026, 10, 12, 0, 40, tzinfo=timezone.utc)


class _DB:
    def __init__(self, rows, breadth=0.35, live=2, kv=None):
        self.rows, self.breadth, self.live, self.kv = rows, breadth, live, kv or {}

    def get(self, _m, key):
        if key == "market_breadth_last":
            return NS(value=json.dumps({"at": (NOW - timedelta(minutes=10)).isoformat(), "breadth": self.breadth}))
        v = self.kv.get(key)
        return None if v is None else NS(value=v)

    def execute(self, stmt, params=None):
        if params and "rules" in params:
            return iter(self.rows)
        return NS(scalar=lambda: self.live)

    def rollback(self):
        pass


def _r(side, mb=None, chg=None):
    return NS(rule="bottom_331", side=side, mb=mb, chg_24h=chg)


def test_regime_24h_counts():
    rows = [_r("LONG", "0.3"), _r("LONG", "0.5"), _r("LONG", None), _r("SHORT", chg=15), _r("SHORT", chg=2), _r("SHORT")]
    g = W.regime_24h(_DB(rows, kv={"rf_bottom_long_mode": "on"}), NOW)
    assert g["LONG"] == [1, 1, 1] and g["SHORT"] == [1, 1, 1]
    assert g["breadth"] == 0.35 and g["mode"] == "on" and g["live_entries"] == 2


def test_regime_line_text():
    lines = W.regime_line({"breadth": 0.35, "LONG": [3, 5, 0], "SHORT": [1, 9, 2], "live_entries": 1, "mode": "on"})
    txt = "\n".join(lines)
    assert "시장폭 0.35 (낮음 → LONG 쓰는 날)" in txt and "LONG 신호 통과 3 · 막힘 5" in txt and "모름 2" in txt and "실주문 진입 1건" in txt
    assert W.regime_line(None) == []
    assert "모름" in W.regime_line({"breadth": None, "LONG": [0, 0, 0], "SHORT": [0, 0, 0], "mode": "on"})[1]


def test_summary_includes_regime():
    from app.services import strategy_council as SC
    rep = SC.build_report([])
    rep["regime_24h"] = {"breadth": 0.7, "LONG": [0, 4, 0], "SHORT": [2, 1, 0], "live_entries": 0, "mode": "on"}
    _t, body = W.summary_text(rep)
    assert "🧭 장세 필터(on) 24시간" in body and "시장폭 0.70 (높음)" in body
