"""📊 Fix 380 (2026-09-19 사장님) — 볼밴 계열 실매매에 「세력 CCI 방향」 게이트.

사장님: "우리 모든자동매매 거래에 적용해주고 특히 볼밴전략도 적극적으로 적용해줘" → 선택 「실매매 볼밴 계열에 바로 적용」

여기서 고정하는 것:
  ① 세력 CCI 계산 = 전략서 수식 (검증 스크립트 bbcci_backtest.indicators 와 같은 값)
  ② 방향 판정 · on 에서만 막음 · 기본 shadow
  ③ 대상 = 볼밴 계열 5 가족만 (사람 전략·다른 계열·중단 중 = 보지 않음)
  ④ 막힘 = 「다음에 다시」(is_limit_error) ⑤ 생성 지점 배선 순서 ⑥ 관제실 칸 ⑦ 판정 캐시(심볼별)
"""
import json
import random
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from app.services import force_cci_gate as FC

APP = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture(autouse=True)
def _real_mode():
    prev = FC.FORCE_MODE
    FC.FORCE_MODE = None
    yield
    FC.FORCE_MODE = prev


class _DB:
    def __init__(self, **kv):
        self.kv = {"auto_trading_halt": "0", **kv}

    def get(self, _m, key):
        v = self.kv.get(key)
        return None if v is None else NS(value=v)


class _Redis:
    def __init__(self):
        self.store = {}

    def get(self, k):
        return self.store.get(k)

    def setex(self, k, ttl, v):
        self.store[k] = v


def _bars(n=60, seed=1):
    rnd = random.Random(seed)
    out, c = [], 100.0
    for i in range(n):
        o = c
        c = max(1.0, c * (1 + rnd.uniform(-0.02, 0.02)))
        out.append([i * 3_600_000, o, max(o, c) * (1 + rnd.uniform(0, 0.01)), min(o, c) * (1 - rnd.uniform(0, 0.01)), c,
                    rnd.uniform(500, 1500)])
    return out


# ── ① 계산 ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_force_cci_matches_strategy_formula(seed):
    import numpy as np
    import pandas as pd
    b = _bars(60, seed)
    a = np.array(b, dtype=float)
    h, l, c, v = a[:, 2], a[:, 3], a[:, 4], a[:, 5]
    tp = pd.Series((h + l + c) / 3)
    mb = tp.rolling(20).mean()
    md = tp.rolling(20).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    cci = (tp - mb) / (0.015 * md)
    vw = np.clip(v / pd.Series(v).rolling(20).mean(), 0.5, 3.0)
    want = float((cci * vw).iloc[-1])
    assert FC.force_cci(b) == pytest.approx(want, rel=1e-9)


def test_force_cci_needs_20_bars_and_moves():
    assert FC.force_cci(_bars(19)) is None
    flat = [[i, 1, 1, 1, 1, 100] for i in range(30)]
    assert FC.force_cci(flat) is None                     # 평균편차 0


def test_volume_weight_is_clamped():
    b = _bars(40)
    big = [x[:5] + [x[5] * (100 if i == len(b) - 1 else 1)] for i, x in enumerate(b)]
    base = FC.force_cci([x[:5] + [1000.0] for x in b])
    assert abs(FC.force_cci(big)) <= abs(base) * 3.0 + 1e-9    # 거래량 폭증도 최대 3배


# ── ② 판정 · 모드 ────────────────────────────────────────────────────────
@pytest.mark.parametrize("side, fc, verdict", [("LONG", 12.0, "pass"), ("LONG", 0.0, "fail"), ("LONG", -5, "fail"),
                                               ("SHORT", -3.0, "pass"), ("SHORT", 0.0, "fail"), ("SHORT", 40, "fail"),
                                               ("LONG", None, "unknown"), ("SHORT", None, "unknown")])
def test_evaluate(side, fc, verdict):
    assert FC.evaluate(side, fc)["verdict"] == verdict


def test_blocks_only_when_on():
    for v in ("fail", "unknown"):
        assert FC.blocks("on", {"verdict": v}) is True
        assert FC.blocks("shadow", {"verdict": v}) is False
    assert FC.blocks("on", {"verdict": "pass"}) is False


def test_mode_default_is_shadow_and_overrides():
    assert FC.DEFAULT_MODE == "shadow"
    assert FC.mode_for(_DB(), "pump_split") == "shadow"
    assert FC.mode_for(_DB(force_cci_gate_default="on"), "pump_split") == "on"
    assert FC.mode_for(_DB(force_cci_gate_default="on", pump_split_force_cci_gate="off"), "pump_split") == "off"
    assert FC.mode_for(_DB(pump_split_force_cci_gate="garbage"), "pump_split") == "shadow"


# ── ③ 대상 ──────────────────────────────────────────────────────────────
def _check(db, stype, *, side="LONG", origin=None, name="auto"):
    return FC.check(db, strategy_type=stype, template_name=name, entry_origin=origin, symbol="AAAUSDT", side=side,
                    exchange_account_id=1)


def test_families():
    assert FC.BB_FAMILIES == ("pump_split", "bb_swing", "bb_mid_line", "bb_break", "bb_reentry")


def test_only_bb_families(monkeypatch):
    monkeypatch.setattr(FC, "judge", lambda *a, **k: {"verdict": "fail", "why": ["x"], "source": "t"})
    db = _DB(force_cci_gate_default="on")
    assert _check(db, "auto_bb_break_SAJANGNIM_TOP", side="SHORT") is None      # 정점 SHORT = 볼밴 계열 아님
    assert _check(db, "rf_surge_long") is None                                  # 규칙 가족
    assert _check(db, "pump_split", origin="manual_modal") is None              # 사람 전략
    with pytest.raises(ValueError):
        _check(db, "pump_split")
    with pytest.raises(ValueError):
        _check(db, "auto_bb_break")                                             # BB 이탈 자동 (꼬리 없음)
    with pytest.raises(ValueError):
        _check(db, "auto_bb_break_reentry")                                     # BB 손절 뒤 재진입


def test_halt_skips_fetch(monkeypatch):
    from app.services import auto_trading_halt as H
    monkeypatch.setattr(H, "FORCE_HALT", None)                                 # conftest 는 중단을 끈다 → 실제 설정을 읽게
    called = []
    monkeypatch.setattr(FC, "judge", lambda *a, **k: called.append(1) or {"verdict": "fail"})
    assert _check(_DB(auto_trading_halt="1", force_cci_gate_default="on"), "pump_split") is None
    assert called == []


def test_shadow_records_and_never_blocks(monkeypatch):
    red = _Redis()
    monkeypatch.setattr("app.core.redis_client.get_redis_client", lambda: red)
    monkeypatch.setattr(FC, "judge", lambda *a, **k: {"verdict": "fail", "why": ["세력 CCI -30"], "source": "t"})
    res = _check(_DB(), "bb_swing")
    assert res["mode"] == "shadow" and res["verdict"] == "fail"
    rec = [json.loads(v) for k, v in red.store.items() if k.startswith("force_cci:shadow:bb_swing:AAAUSDT:")]
    assert rec and rec[0]["side"] == "LONG" and rec[0]["verdict"] == "fail"


# ── ④ 막힘 = 다음에 다시 ────────────────────────────────────────────────
def test_block_is_retry_later(monkeypatch):
    from app.services import auto_family_registry as AF
    monkeypatch.setattr(FC, "judge", lambda *a, **k: {"verdict": "fail", "why": ["세력 CCI -30"], "source": "t"})
    with pytest.raises(ValueError) as ei:
        _check(_DB(bb_mid_line_force_cci_gate="on"), "bb_mid_line")
    assert FC.is_gate_error(ei.value) and AF.is_limit_error(ei.value)
    assert "bb_mid_line_force_cci_gate" in str(ei.value)


# ── ⑤ 배선 ──────────────────────────────────────────────────────────────
def test_wired_after_chart_gate_before_account():
    s = (APP / "services" / "strategy_service.py").read_text(encoding="utf-8")
    i_chart, i_cci, i_acct = s.index("_chart_gate376(self.db"), s.index("_force_cci380(self.db"), s.index(
        "ex_account = self.db.get(_EA, exchange_account_id)")
    assert i_chart < i_cci < i_acct


# ── ⑥ 관제실 ────────────────────────────────────────────────────────────
def test_control_room_has_switches():
    from app.services import auto_control as AC
    wl = AC.whitelist()
    assert wl["force_cci_gate_default"].default == "shadow"
    for fam in FC.BB_FAMILIES:
        assert f"{fam}_force_cci_gate" in wl, fam
        assert wl[f"{fam}_force_cci_gate"].kind == "gate3"
    assert "top_short_force_cci_gate" not in wl                                # 볼밴 계열만


# ── ⑦ 판정 · 캐시 ───────────────────────────────────────────────────────
def test_judge_fetches_once_and_caches_per_symbol(monkeypatch):
    red = _Redis()
    calls = []
    b = _bars(60, 5)
    raw = [[x[0], str(x[1]), str(x[2]), str(x[3]), str(x[4]), str(x[5])] for x in b]

    class _BC:
        def get_klines(self, **kw):
            calls.append(kw)
            return raw
    monkeypatch.setattr("time.time", lambda: (b[-1][0] + 2 * 3_600_000) / 1000)   # 마지막 봉까지 마감
    r1 = FC.judge(_DB(), symbol="AAAUSDT", side="LONG", client=_BC(), redis_client=red)
    r2 = FC.judge(_DB(), symbol="AAAUSDT", side="SHORT", client=_BC(), redis_client=red)
    assert len(calls) == 1 and calls[0]["interval"] == "1h" and calls[0]["limit"] == 60
    assert r1["source"] == "fetch" and r2["source"] == "cache"
    assert r1["force_cci"] == r2["force_cci"] == pytest.approx(FC.force_cci(b), abs=0.01)
    assert {r1["verdict"], r2["verdict"]} == {"pass", "fail"}                  # 같은 값 = 한쪽만 통과


def test_judge_fetch_error_is_unknown():
    class _Bad:
        def get_klines(self, **kw):
            raise RuntimeError("boom")
    r = FC.judge(_DB(), symbol="AAAUSDT", side="LONG", client=_Bad(), redis_client=_Redis())
    assert r["verdict"] == "unknown"


# ── ⑧ 막혔을 때 워커가 조용히 건너뛴다 (자동매매 중단 중이라 운영에서는 아직 한 번도 안 난 경로) ──
def test_realtime_reentry_classifies_force_cci_block():
    from app.workers.realtime_reentry_worker import _classify_entry_error
    msg = "⛔ [세력 CCI 게이트] BB 손절 뒤 재진입 AAAUSDT LONG 세력 CCI 방향 반대 — 세력 CCI -30 (>0 이어야)"
    assert _classify_entry_error(msg) == "force_cci_gate"
    w = (APP / "workers" / "realtime_reentry_worker.py").read_text(encoding="utf-8")
    assert '("chart_gate", "force_cci_gate", "family_daily_max")' in w          # 스택트레이스 대신 info


def test_auto_bb_breakdown_returns_none_on_gate_block():
    w = (APP / "workers" / "auto_bb_breakdown_worker.py").read_text(encoding="utf-8")
    i_gate = w.index("if _is_gate(_bal_e):")
    i_raise = w.index("if not _is_bal(_bal_e):")
    assert i_gate < i_raise, "게이트 막힘은 다시 던지기 전에 None 으로 건너뛴다"
    blk = w[i_gate:i_raise]
    assert "db.rollback()" in blk and "return None" in blk
