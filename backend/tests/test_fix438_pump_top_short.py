"""Fix 438 — 🔺 급등 정점 SHORT: SHORT 규칙이 켜진 24h 급등 종목 (+30% / +10% · 시장폭 중간). 가상 판정 → 규칙 가족 2종, 기본 shadow."""
from __future__ import annotations

import pathlib

import pytest

from app.services import pump_top_short as PTS

APP = pathlib.Path(PTS.__file__).resolve().parents[1]
SIDE = {"s1": "SHORT", "s2": "SHORT", "l1": "LONG", "baseline_SHORT": "SHORT",
        "pumptop_short_30": "SHORT", "pumptop_short_mid": "SHORT", "consensus_long": "LONG"}


def _f(shorts=1, longs=0, baseline=True, meta=False):
    f = {k: False for k in SIDE}
    for k in ("s1", "s2")[:shorts]:
        f[k] = True
    if longs:
        f["l1"] = True
    f["baseline_SHORT"] = baseline
    if meta:
        f["pumptop_short_30"] = f["pumptop_short_mid"] = True
    return f


def test_judge_thresholds():
    p = PTS.params_from()
    assert (p["chg_hi"], p["chg_lo"], p["b_lo"], p["b_hi"]) == (30.0, 10.0, 0.4, 0.6)
    assert PTS.judge(_f(), SIDE, 30.0, 0.8, p) == (True, False, 1)          # +30 이상 = 30 (시장폭 무관)
    assert PTS.judge(_f(), SIDE, 29.9, 0.5, p) == (False, True, 1)          # +10 이상 · 중간 = mid
    assert PTS.judge(_f(), SIDE, 35.0, 0.5, p) == (True, True, 1)           # 둘 다
    assert PTS.judge(_f(), SIDE, 15.0, 0.39, p) == (False, False, 1)        # 시장폭 낮음 = mid 아님
    assert PTS.judge(_f(), SIDE, 15.0, 0.61, p) == (False, False, 1)
    assert PTS.judge(_f(), SIDE, 9.9, 0.5, p) == (False, False, 1)
    assert PTS.judge(_f(), SIDE, 15.0, None, p) == (False, False, 1)        # 시장폭 모름 = mid 판정 안 함
    assert PTS.judge(_f(), SIDE, None, 0.5, p) == (False, False, 1)         # 24h 모름 = 둘 다 안 함


def test_needs_a_short_rule_and_ignores_meta_baseline_long():
    assert PTS.judge(_f(shorts=0, longs=1, meta=True), SIDE, 50.0, 0.5) == (False, False, 0)   # LONG·기준선·규칙의 규칙만 = 0
    assert PTS.judge(_f(shorts=2), SIDE, 50.0, 0.5)[2] == 2


def test_apply_overwrites_previous_flags():
    f = _f(shorts=0, meta=True)
    assert PTS.apply(f, SIDE, 50.0, 0.5) == 0 and f["pumptop_short_30"] is False and f["pumptop_short_mid"] is False
    f2 = _f()
    PTS.apply(f2, SIDE, 31.0, 0.45)
    assert f2["pumptop_short_30"] is True and f2["pumptop_short_mid"] is True


@pytest.mark.parametrize("key,val", [("pumptop_chg_hi", "1"), ("pumptop_chg_lo", "x"), ("pumptop_breadth_lo", "0.7"),
                                     ("pumptop_chg_hi", 10 ** 400)])
def test_bad_settings_fall_back(key, val):
    assert PTS.params_from(lambda k: val if k == key else None) == PTS.params_from()


def test_disabled():
    p = PTS.params_from(lambda k: "0" if k == "pumptop_enabled" else None)
    assert PTS.judge(_f(), SIDE, 50.0, 0.5, p) == (False, False, 1)


def test_rule_families_shadow_single():
    from app.services import rule_families as RF

    class _DB:
        def get(self, _m, _k):
            return None
    for key, rule in (("rf_pumptop30", "pumptop_short_30"), ("rf_pumptop_mid", "pumptop_short_mid")):
        f = RF.FAMILY_BY_KEY[key]
        assert (f.rule, f.side) == (rule, "SHORT")
        assert RF.mode_of(_DB(), key) == "shadow"                         # 🚨 헌법 64 — 실주문은 사장님이 켤 때만
        assert RF.entry_of(_DB(), key) == "single" and RF.chart_gate_of(_DB(), key) == "shadow"


def test_registered_and_wired():
    from app.services import chart_learning as CL
    from app.services.auto_control import LINE_ORDER
    from app.services.chg24_entry_gate import EXEMPT_DEFAULT
    from app.services.strategy_council import META_RULES
    keys = {r.key for r in CL.RULES}
    assert {"pumptop_short_30", "pumptop_short_mid"} <= keys and {"pumptop_short_30", "pumptop_short_mid"} <= META_RULES
    assert any("rf_pumptop30" in fams and "rf_pumptop_mid" in fams for _t, fams in LINE_ORDER)
    assert "RF_PUMPTOP" not in EXEMPT_DEFAULT                            # SHORT 은 순위 게이트 그대로 (막혀서 이득이었다)
    src = (APP / "workers" / "paper_trading_worker.py").read_text(encoding="utf-8")
    assert "_PTS.apply(fired, rule_side, chg.get(sym), breadth)" in src
    assert src.index("_PTS.apply(") < src.index("for key, hit in fired.items():")
    assert 't["snapshot"]["pumptop"]' in src and "PTS.set_paper_params(lambda k: _setting(db, k))" in src


def test_bool_is_not_a_number():
    assert PTS.judge(_f(), SIDE, 15.0, True) == (False, False, 1)
    assert PTS.judge(_f(), SIDE, True, 0.5) == (False, False, 1)
    from app.services import consensus_long as CON
    assert CON.qualifies({"a": True, "b": True, "c": True, "d": True}, {k: "LONG" for k in "abcd"}, False)[0] is False
