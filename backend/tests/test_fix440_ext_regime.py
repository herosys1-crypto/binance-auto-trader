"""Fix 440 — 🧭 외부 전략 장세 필터 (Fix 439 두 줄 법칙을 EMA 눌림·후지모토·마하세븐·볼린저 3종·3중 이평에도)."""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest

from app.services import ext_regime as RG

NOW = datetime(2026, 10, 11, 4, 0, tzinfo=timezone.utc)
APP = pathlib.Path(RG.__file__).resolve().parents[1]


class _DB:
    def __init__(self, **kv):
        self.kv = kv

    def get(self, _m, key):
        v = self.kv.get(key)
        return None if v is None else NS(value=v)


def test_breadth_now_freshness_and_bad_values():
    ok = json.dumps({"at": (NOW - timedelta(minutes=20)).isoformat(), "breadth": 0.31})
    assert RG.breadth_now(ok, now=NOW) == pytest.approx(0.31)
    old = json.dumps({"at": (NOW - timedelta(minutes=61)).isoformat(), "breadth": 0.31})
    assert RG.breadth_now(old, now=NOW) is None                                   # 60분 넘음 = 모름
    fut = json.dumps({"at": (NOW + timedelta(minutes=10)).isoformat(), "breadth": 0.31})
    assert RG.breadth_now(fut, now=NOW) is None                                   # 미래 시각 = 모름
    for bad in (None, "x", json.dumps({"at": NOW.isoformat(), "breadth": True}), json.dumps({"at": NOW.isoformat(), "breadth": 1.5})):
        assert RG.breadth_now(bad, now=NOW) is None


def _bars(closes):
    return [[i, c, c, c, c, 1.0] for i, c in enumerate(closes)]


def test_chg24_from_bars():
    assert RG.chg24_from_bars(_bars([100, 110]), 86_400_000) == pytest.approx(10.0)    # 일봉: 직전 대비
    closes = [100.0] * 97
    closes[-1] = 120.0
    assert RG.chg24_from_bars(_bars(closes), 900_000) == pytest.approx(20.0)        # 15분봉: 96봉 전 대비
    assert RG.chg24_from_bars(_bars([100.0] * 96), 900_000) is None                 # 봉 부족
    assert RG.chg24_from_bars(_bars([0.0, 10.0]), 86_400_000) is None
    assert RG.chg24_from_bars([], 900_000) is None


def test_judge_uses_rule_family_numbers():
    db = _DB()
    assert RG.judge(db, "LONG", 0.3, None, "on")["blocks"] is False
    assert RG.judge(db, "LONG", 0.5, None, "on")["blocks"] is True
    assert RG.judge(db, "LONG", 0.5, None, "shadow")["blocks"] is False            # shadow = 기록만
    assert RG.judge(db, "SHORT", None, 12.0, "on")["blocks"] is False
    assert RG.judge(db, "SHORT", None, None, "on")["blocks"] is True                # 모름 = 막음
    assert RG.judge(_DB(rf_short_chg24_min="20"), "SHORT", None, 12.0, "on")["blocks"] is True   # 규칙 가족과 같은 설정


def test_mode_of():
    assert RG.mode_of(lambda k: None) == "on" and RG.mode_of(lambda k: "SHADOW") == "shadow"
    assert RG.mode_of(lambda k: "zz") == "on" and RG.mode_of(lambda k: 1 / 0) == "on"


def test_enter_blocks_only_when_regime_blocks(monkeypatch):
    from app.workers import external_strategies_worker as W
    calls = []
    monkeypatch.setattr("app.services.surge_ladder_entry.create_surge_position", lambda db, **k: calls.append(k) or None)
    stat = {"miss": {}, "entered": 0}
    kw = dict(fam="emapb", sym="AUSDT", side="LONG", margin=10.0, sp=3.0, lev=2, prefix="EMAPB", stype="ema_pullback",
              cap_key="emapb_max_concurrent", stop_price=1.0, cooldown_h=1.0, stage=None)
    assert W._enter(None, None, stat, **kw, regime={"blocks": True, "why": "시장폭 0.55 ≥ 0.4"}) is False
    assert calls == [] and stat["miss"]["장세 필터"] == 1
    W._enter(None, None, stat, **kw, regime={"blocks": False})
    W._enter(None, None, stat, **kw)                                                # 필터 없음(off) = 예전 그대로
    assert len(calls) == 2


def test_wiring_pins():
    src = (APP / "workers" / "external_strategies_worker.py").read_text(encoding="utf-8")
    for fam, iv in (("fujimoto", "interval"), ("mach7", "interval"), ("emapb", "ep_iv"), ("bbema", "bb_iv")):
        assert f'payload = {{"regime": _regime(side, bars, {iv}), "at": now.isoformat(), "family": "{fam}"' in src, fam
    assert src.count('regime=payload["regime"]') == 4                               # 신규 진입 4곳 (후지모토 2·3차 추가는 거르지 않는다)
    assert '"stage": nxt' in src and src.index('"stage": nxt') < src.index('"family": "fujimoto", "symbol": sym, "side": side, "stage": 1')
    assert 'stat.pop("_regime_fn", None)' in src
    fl = (APP / "workers" / "ext_family_loop.py").read_text(encoding="utf-8")
    assert '"regime": _rgf(side, bars, iv) if callable(_rgf) else None' in fl and 'regime=payload["regime"]' in fl
    from app.services import external_strategies as ES
    assert ES.SETTINGS["ext_regime_filter"][0] == "on"
