"""🔼 Fix 382 (2026-09-19 사장님) — 조건 붙인 피라미딩을 가상매매 보고서에 사전등록.

사장님: "조건 붙인 피라미딩 가상매매로 검증해줘"
재측정(가상 추가 lot 22,965건): LONG 추가는 진입 시점 시장폭 ≥0.55 일 때 두 장세 모두 나았다(6일 중 4일) ·
SHORT 추가 ≤0.45 는 나빴다(대조군). 9/20 이후 진입분으로만 판정한다.
"""
from datetime import date

from app.services import paper_report_v3 as PR3
from tests.test_fix370_paper_report_v3 import _mk, _report, dt

D = date(2026, 9, 22)


def lot(side, pnl, breadth, *, day=D, variant="live_both"):
    return (side, "r", dt(day, 3, 0), variant, pnl / 3.0, pnl, breadth)


def test_numbers():
    assert PR3.ADD_COND_SINCE.startswith("2026-09-20")
    assert PR3.ADD_COND == (("A1_long_add_breadth_up", "LONG", 0.55, ">="),
                            ("A2_short_add_breadth_down", "SHORT", 0.45, "<="))


def test_split_by_breadth_and_cutoff():
    lots = [lot("LONG", 30, 0.7) for _ in range(3)]                        # 통과
    lots += [lot("LONG", -12, 0.4) for _ in range(2)]                      # 제외
    lots += [lot("LONG", 99, 0.9, day=date(2026, 9, 19))]                  # 사전등록 전 = 안 셈
    lots += [lot("LONG", 50, None)]                                        # 시장폭 없음 = 안 셈
    lots += [lot("LONG", 50, 0.9, variant="noind")]                        # 다른 변형 = 안 셈
    lots += [lot("SHORT", -20, 0.3), lot("SHORT", 5, 0.8)]
    c = PR3._adds_conditional(lots)
    a1 = c["A1_long_add_breadth_up"]
    assert (a1["kept"]["n"], a1["kept"]["pnl_sum"], a1["excluded"]["n"], a1["excluded"]["pnl_sum"]) == (3, 90.0, 2, -24.0)
    a2 = c["A2_short_add_breadth_down"]
    assert (a2["kept"]["n"], a2["excluded"]["n"]) == (1, 1)


def test_days_better_needs_20_each_side():
    lots = [lot("LONG", 10, 0.7) for _ in range(20)] + [lot("LONG", -5, 0.3) for _ in range(20)]
    c = PR3._adds_conditional(lots)["A1_long_add_breadth_up"]
    assert (c["days_better"], c["days_both"]) == (1, 1)


def test_old_six_field_lots_still_work():
    six = [("LONG", "r", dt(D, 3, 0), "live_both", 2.0, 6.0)]
    rep = _report([_mk("AUSDT", "LONG", "myrule", 3.0, dt(D, 1, 0))], six, now=dt(D, 12, 0))
    assert rep["blocks"]["all"]["adds"]["live_both"]["LONG"]["n"] == 1
    assert rep["blocks"]["all"]["adds_cond"]["A1_long_add_breadth_up"]["kept"]["n"] == 0


def test_render_has_section():
    rep = _report([_mk("AUSDT", "LONG", "myrule", 3.0, dt(D, 1, 0))], [lot("LONG", 30, 0.7)], now=dt(D, 12, 0))
    md = PR3.render_markdown_v3(rep)
    assert "4-1. 조건부 피라미딩" in md and "A1_long_add_breadth_up" in md


def test_loader_reads_breadth():
    src = (PR3.__file__ and open(PR3.__file__, encoding="utf-8").read())
    assert 'PaperTrade.snapshot["market_breadth"].astext' in src


# ── 🧭 Fix 385 (2026-09-19 사장님 「최소한 90%이상은 성공할수있는 단순한 흐름 … 성공하는 모든 로직으로 만들어줘」) ──
#   장세 전환 = 오르는 장엔 L1 반등 LONG 만 · 내리는 장엔 S4 급반등 꼭대기 SHORT 만 (사전등록 9/20~)
def _rule_row(sym, side, rule, roi, breadth, day=D):
    r = _mk(sym, side, rule, roi, dt(day, 2, 0))
    r["gate"] = {"breadth": breadth}
    return r


def test_fix385_regime_switch_filters():
    assert (PR3.REGIME_UP, PR3.REGIME_DOWN) == (0.55, 0.45)
    assert PR3.FILTER_PREREG["R1_l1_rising_market"].startswith("2026-09-20")
    rows = [_rule_row(f"U{i}USDT", "LONG", "zone_l1_rebound_long", 8.0, 0.7) for i in range(4)]
    rows += [_rule_row(f"D{i}USDT", "LONG", "zone_l1_rebound_long", -6.0, 0.3) for i in range(3)]
    rows += [_rule_row(f"X{i}USDT", "LONG", "surge_start_346", 5.0, 0.7) for i in range(2)]          # 다른 규칙 = 밖
    rows += [_rule_row(f"S{i}USDT", "SHORT", "zone_s4_spike_top_short", 6.0, 0.35) for i in range(3)]
    rows += [_rule_row(f"T{i}USDT", "SHORT", "zone_s4_spike_top_short", -9.0, 0.8) for i in range(2)]
    rows += [_rule_row("BUSDT", "LONG", "zone_l1_rebound_long", 1.0, 0.6, day=date(2026, 9, 19))]  # 등록 전
    f = _report(rows, now=dt(D, 12, 0))["blocks"]["all"]["filters"]
    r1, r2 = f["LONG"]["R1_l1_rising_market"], f["SHORT"]["R2_s4_falling_market"]
    assert (r1["universe"]["n"], r1["kept"]["n"], r1["excluded"]["n"]) == (7, 4, 3)
    assert (r2["universe"]["n"], r2["kept"]["n"], r2["excluded"]["n"]) == (5, 3, 2)
    assert 'PaperTrade.snapshot["market_breadth"].astext, Float).label("g_breadth")' in open(PR3.__file__, encoding="utf-8").read()
