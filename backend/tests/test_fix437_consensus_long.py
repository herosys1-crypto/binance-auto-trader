"""Fix 437 — 🤝 합의 LONG: 같은 15분봉 LONG 규칙 4개+ · 시장폭 < 0.4 (가상 판정 → 규칙 가족 rf_consensus_long, 기본 shadow)."""
from __future__ import annotations

import pathlib
from types import SimpleNamespace as NS

import pytest

from app.services import consensus_long as CON

APP = pathlib.Path(CON.__file__).resolve().parents[1]
SIDE = {"a": "LONG", "b": "LONG", "c": "LONG", "d": "LONG", "e": "LONG", "s1": "SHORT", "s2": "SHORT",
        "baseline_LONG": "LONG", "consensus_long": "LONG"}


def _fired(longs=4, shorts=0, baseline=True):
    f = {k: False for k in SIDE}
    for k in ("a", "b", "c", "d", "e")[:longs]:
        f[k] = True
    for k in ("s1", "s2")[:shorts]:
        f[k] = True
    f["baseline_LONG"] = baseline
    return f


def test_qualifies_rules_and_breadth():
    p = CON.params_from()
    assert (p["min_rules"], p["breadth_max"], p["enabled"]) == (4, 0.4, True)
    assert CON.qualifies(_fired(4), SIDE, 0.3, p) == (True, 4)
    assert CON.qualifies(_fired(3), SIDE, 0.3, p) == (False, 3)          # 3개는 아님
    assert CON.qualifies(_fired(5, shorts=2), SIDE, 0.39, p) == (True, 5)  # SHORT·기준선은 세지 않는다
    assert CON.qualifies(_fired(4), SIDE, 0.4, p)[0] is False             # 0.4 는 「낮음」 아님 (< 0.4)
    assert CON.qualifies(_fired(4), SIDE, None, p)[0] is False            # 시장폭 모름 = 판정 안 함
    assert CON.qualifies(_fired(4), SIDE, "x", p)[0] is False
    assert CON.qualifies(_fired(4), SIDE, 1.5, p)[0] is False


def test_apply_sets_flag_and_ignores_itself():
    f = _fired(3)
    f["consensus_long"] = True                                          # 이전 값이 남아 있어도 자신은 세지 않는다
    n = CON.apply(f, SIDE, 0.2)
    assert n == 3 and f["consensus_long"] is False
    f2 = _fired(4)
    assert CON.apply(f2, SIDE, 0.2) == 4 and f2["consensus_long"] is True


@pytest.mark.parametrize("key,val", [("consensus_min_rules", "1"), ("consensus_min_rules", "4.5"), ("consensus_breadth_max", "nan"),
                                     ("consensus_breadth_max", "0.99")])
def test_bad_settings_fall_back(key, val):
    assert CON.params_from(lambda k: val if k == key else None) == CON.params_from()


def test_disabled():
    p = CON.params_from(lambda k: "0" if k == "consensus_enabled" else None)
    assert CON.qualifies(_fired(5), SIDE, 0.1, p) == (False, 5)


def test_rule_family_defaults_measured_exit():
    from app.services import rule_families as RF
    from types import SimpleNamespace as N

    class _DB:
        def get(self, _m, _k):
            return None
    f = RF.FAMILY_BY_KEY["rf_consensus_long"]
    assert (f.rule, f.side, f.prefix, f.stype) == ("consensus_long", "LONG", "RF_CONSENSUS", "rf_consensus_long")
    db = _DB()
    assert RF.mode_of(db, f.key) == "shadow"                            # 실주문은 사장님이 켠다
    assert RF.entry_of(db, f.key) == "single"                           # 측정 = 단일 · TP 15/20/25/30 · 손절 −25
    assert RF.chart_gate_of(db, f.key) == "shadow"                      # 측정에 차트 게이트 없음
    assert RF.places_of(db, f.key) == {"ALL"}


def test_registered_everywhere():
    from app.services import chart_learning as CL
    from app.services.auto_control import LINE_ORDER
    from app.services.auto_family_registry import family_for
    from app.services.chg24_entry_gate import EXEMPT_DEFAULT
    assert "consensus_long" in {r.key for r in CL.RULES}
    assert any("rf_consensus_long" in fams for _t, fams in LINE_ORDER)
    assert family_for(strategy_type="rf_consensus_long", template_name="RF_CONSENSUS_XUSDT", entry_origin=None).key == "rf_consensus_long"
    assert "RF_CONSENSUS" in EXEMPT_DEFAULT                              # LONG 반전 겹침 — 순위 게이트 면제 (Fix 401 과 같은 이유)
    assert CON._never(NS()) is False                                     # 규칙 목록에선 스스로 켜지지 않는다


def test_paper_worker_wiring():
    src = (APP / "workers" / "paper_trading_worker.py").read_text(encoding="utf-8")
    i = src.index("fired = PT.evaluate_rules(series, j)")
    blk = src[i:i + 1200]
    assert "_CON.apply(fired, rule_side, breadth)" in blk                # 평가 직후, 진입 루프 전
    assert src.index("_CON.apply(fired, rule_side, breadth)") < src.index("for key, hit in fired.items():")
    assert 't["snapshot"]["consensus"] = {"n_long": _con_n, "breadth": breadth}' in src
    assert "CON.set_paper_params(lambda k: _setting(db, k))" in src


def test_council_overlap_excludes_consensus():
    from app.services import strategy_council as SC
    from datetime import date
    rows = [SC.Row("a", "LONG", date(2026, 10, 1), 1.0, 0.3, ("a", "b", "consensus_long")),
            SC.Row("b", "LONG", date(2026, 10, 1), 1.0, 0.3, None),
            SC.Row("consensus_long", "LONG", date(2026, 10, 1), 1.0, 0.3, None)]
    B = {(x["side"], x["k"]): x["n"] for x in SC.build_report(rows)["B_overlap"]}
    assert B[("LONG", 2)] == 1                                           # a 행: a,b = 2 (합의는 세지 않음)


def test_huge_number_setting_only_resets_that_key():
    p = CON.params_from(lambda k: {"consensus_enabled": "0", "consensus_min_rules": "6", "consensus_breadth_max": 10 ** 400}.get(k))
    assert (p["enabled"], p["min_rules"], p["breadth_max"]) == (False, 6, 0.4)
