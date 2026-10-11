"""Fix 442 — 📣 시장 전체 동시 반등 감지 (알림·기록 전용)."""
from __future__ import annotations

import json
import pathlib

from app.services import mass_rebound as MR

APP = pathlib.Path(MR.__file__).resolve().parents[1]


class _R:
    def __init__(self):
        self.store = {}

    def set(self, k, v, nx=False, ex=None):
        if nx and k in self.store:
            return None
        self.store[k] = v
        return True

    def setex(self, k, ttl, v):
        self.store[k] = v


def test_params():
    p = MR.params_from(lambda k: None)
    assert (p["min_symbols"], p["min_rules"], p["alert"]) == (16, 4, True)
    assert MR.params_from(lambda k: {"mass_rebound_min_symbols": "1"}.get(k))["min_symbols"] == 16     # 범위 밖
    assert MR.params_from(lambda k: {"mass_rebound_min_symbols": "20", "mass_rebound_alert": "0"}.get(k)) == \
        {"min_symbols": 20, "min_rules": 4, "alert": False}
    assert MR.params_from(lambda k: 1 / 0) == {"min_symbols": 16, "min_rules": 4, "alert": True}


def test_detect_threshold():
    p = MR.params_from(lambda k: None)
    m = {f"S{i}USDT": 4 for i in range(16)}
    assert len(MR.detect(m, p)) == 16
    m2 = {f"S{i}USDT": 4 for i in range(15)} | {"X": 3, "Y": None}
    assert MR.detect(m2, p) == []                                    # 15종목 = 아님 · 3개·None 은 안 셈
    m3 = {"A": 6, **{f"S{i}": 4 for i in range(16)}}
    assert MR.detect(m3, p)[0] == "A"                                # 많은 순


def test_record_once_and_alert(monkeypatch):
    sent = []

    class _NS:
        def __init__(self, db):
            pass

        def send_system_alert(self, title, body):
            sent.append(title)
            return 1
    monkeypatch.setattr("app.services.notification_service.NotificationService", _NS)
    r = _R()
    p = MR.params_from(lambda k: None)
    syms = [f"S{i}USDT" for i in range(17)]
    assert MR.record_and_alert(None, r, bar_ts=1000, symbols=syms, breadth=0.31, p=p) is True
    assert MR.record_and_alert(None, r, bar_ts=1000, symbols=syms, breadth=0.31, p=p) is False   # 같은 봉 두 번 = 알림 한 번
    assert len(sent) == 1 and "17종목" in sent[0]
    assert json.loads(r.store["mass_rebound:last"])["n"] == 17


def test_retro_bars():
    side_of = {f"r{i}": "LONG" for i in range(5)} | {"s": "SHORT"}
    rows = []
    for k in range(16):
        rows.append({"rule": "r0", "side": "LONG", "symbol": f"S{k}", "ts": 7, "rf": ["r0", "r1", "r2", "r3", "s", "consensus_long"]})
    rows.append({"rule": "r0", "side": "LONG", "symbol": "Z", "ts": 8, "rf": ["r0", "r1", "r2", "r3"]})
    assert MR.retro_bars(rows, side_of=side_of) == {7}
    rows2 = [dict(x, rf=["r0", "r1", "r2", "consensus_long"]) for x in rows]    # 합의 자신은 세지 않는다 → 3개
    assert MR.retro_bars(rows2, side_of=side_of) == set()


def test_worker_wiring():
    src = (APP / "workers" / "paper_trading_worker.py").read_text(encoding="utf-8")
    assert "_mass_n[sym] = _con_n" in src and "MR.detect(_mass_n, _mp)" in src
    assert src.index("MR.detect(_mass_n, _mp)") > src.index("for key, hit in fired.items():")      # 사이클 끝
    rep = (APP.parent / "scripts" / "entry_condition_study" / "verdict_2026_10_25.py").read_text(encoding="utf-8")
    assert "MR.retro_bars(" in rep and "## F." in rep
