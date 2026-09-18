"""🗺 Fix 379 (2026-09-19 사장님) — 기회 지도 두 구간을 가상매매 규칙으로 등록 (주문 0건).

사장님: "차트들을 분석해봐 그냥 모든 들어가는 포지션말고 들어가면 이익은 극대화되는 구간을 찾아줘"
        → "가상매매 규칙으로 추가해서 검증해줘"

여기서 고정하는 것:
  ① 사전등록 숫자 (검증 중 바뀌면 표본 무효) ② 1시간 마감에서만 판정 ③ L1 = 4H 하단 이탈 뒤 1~7봉 (chart_state 와 같은 값)
  ④ S4 = 급반등 + 1H ATR + 일봉 하단권 (일봉 없으면 불발) ⑤ 레지스트리·Series·워커 배선 ⑥ 주문 경로 없음 ⑦ 보고서에 규칙으로 잡힘
"""
from datetime import date
from pathlib import Path

import pytest

from app.services import chart_learning as CL
from app.services import chart_state as CS
from app.services import opportunity_zones as OZ
from app.services import paper_trading as PT

APP = Path(__file__).resolve().parents[1] / "app"
H = 3_600_000
M15 = 900_000
H4 = 14_400_000
D1 = 86_400_000
T0 = 1_788_000_000_000 // D1 * D1          # 자정 정렬


def bars(step, closes, *, spread=0.004, t0=T0):
    out = []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        out.append([t0 + i * step, o, max(o, c) * (1 + spread), min(o, c) * (1 - spread), c, 1000.0])
        prev = c
    return out


def flat(n, base=100.0, amp=0.3):
    return [base + (amp if i % 2 else -amp) for i in range(n)]


# ── ① 사전등록 숫자 ────────────────────────────────────────────────────
def test_preregistered_numbers():
    assert (OZ.L1_SINCE_MIN, OZ.L1_SINCE_MAX) == (1, 7)
    assert (OZ.S4_LO4H_PCT, OZ.S4_H1_LO_PCT, OZ.S4_H1_BARS, OZ.S4_ATR_1H_PCT) == (8.0, 12.0, 16, 2.5)
    assert OZ.S4_D1_POS == ("LOWER_HALF", "BELOW_LOWER")
    assert [k for k, *_ in OZ.PAPER_RULES] == ["zone_l1_rebound_long", "zone_s4_spike_top_short"]
    assert [s for _, s, *_ in OZ.PAPER_RULES] == ["LONG", "SHORT"]


# ── ② 1시간 마감에서만 ─────────────────────────────────────────────────
@pytest.mark.parametrize("k, want", [(3, True), (7, True), (4, False), (5, False), (6, False)])
def test_on_hour(k, want):
    kl15 = bars(M15, flat(k + 1))          # 마지막 봉 open = T0 + k·15분 → 마감 = (k+1)·15분
    assert OZ.on_hour(kl15) is want


# ── ③ L1 ────────────────────────────────────────────────────────────────
def _h4_after_drop(k):
    """평평한 40봉 → 하단 밖으로 떨어진 1봉 → 회복 k봉."""
    return bars(H4, flat(40) + [88.0] + [99.5] * k, spread=0.002)


@pytest.mark.parametrize("k", range(0, 10))
def test_l1_counts_bars_since_lower_break(k):
    kl4h = _h4_after_drop(k)
    since = OZ.h4_since_below_lower(kl4h)
    # chart_state._block('4h') 와 같은 값이어야 한다 (분석·운영 기록과 같은 자)
    blk = CS._block("4h", kl4h[-60:], dict(CS.THRESHOLDS))
    assert since == blk["bb"]["bars_since_below_lower"] == k
    assert OZ.l1_rebound(kl4h) is (1 <= k <= 7)


def test_l1_none_when_no_break_or_too_few_bars():
    assert OZ.h4_since_below_lower(bars(H4, flat(45))) is None
    assert OZ.l1_rebound(bars(H4, flat(45))) is False
    assert OZ.l1_rebound(_h4_after_drop(3)[-20:]) is False       # 30봉 미만


# ── ④ S4 ────────────────────────────────────────────────────────────────
def _spike15(last=110.0):
    return bars(M15, [100.0] * 15 + [last], spread=0.001, t0=T0)   # 16봉 = 4시간 → 마지막 봉 마감 = 정시


def _h1(spread):
    return bars(H, flat(60), spread=spread)


def _d1(closes):
    return bars(D1, closes, spread=0.01)


D1_DOWN = [100.0 - i * 0.8 for i in range(45)] + [70.0, 71.0]         # 중단선 아래
D1_UP = [60.0 + i * 0.8 for i in range(45)] + [98.0, 99.0]              # 중단선 위


def test_s4_needs_spike_and_volatility():
    assert OZ.s4_spike(_spike15(110.0), _h1(0.03)) is True               # +10% · ATR 큼
    assert OZ.s4_spike(_spike15(107.0), _h1(0.03)) is False              # +7% = 문턱 미달 (1시간 저점 대비도 미달)
    assert OZ.s4_spike(_spike15(110.0), _h1(0.002)) is False             # 조용한 시간 = ATR 미달


def test_s4_daily_low_half():
    assert CS.bb_state(_d1(D1_DOWN), tol_pct=CS.THRESHOLDS["tol_pct_1d"], lookback=CS.THRESHOLDS["lookback_1d"],
                       slope_pct=CS.THRESHOLDS["trend_slope_1d"], th=dict(CS.THRESHOLDS))["pos"] in OZ.S4_D1_POS
    assert OZ.d1_low_half(_d1(D1_DOWN)) is True
    assert OZ.d1_low_half(_d1(D1_UP)) is False
    assert OZ.d1_low_half(None) is False                                  # 일봉 없음 = 불발 (fail-closed)


class _Ctx:
    def __init__(self, kl15, kl1h, kl4h=(), kl1d=None):
        self.kl15, self.kl1h, self.kl4h, self.kl1d = kl15, kl1h, list(kl4h), kl1d


def test_rule_functions():
    assert OZ.on_hour(_spike15()) is True
    fn = dict((k, f) for k, _s, _l, f in OZ.PAPER_RULES)
    s4 = fn["zone_s4_spike_top_short"]
    assert s4(_Ctx(_spike15(), _h1(0.03), kl1d=_d1(D1_DOWN))) is True
    assert s4(_Ctx(_spike15(), _h1(0.03), kl1d=_d1(D1_UP))) is False
    assert s4(_Ctx(_spike15(), _h1(0.03), kl1d=None)) is False
    off_hour = bars(M15, [100.0] * 15 + [110.0], spread=0.001, t0=T0 + M15)
    assert s4(_Ctx(off_hour, _h1(0.03), kl1d=_d1(D1_DOWN))) is False     # 정시 아님
    assert OZ.needs_daily(_spike15(), _h1(0.03)) is True
    assert OZ.needs_daily(_spike15(), _h1(0.002)) is False
    l1 = fn["zone_l1_rebound_long"]
    assert l1(_Ctx(_spike15(), [], kl4h=_h4_after_drop(3))) is True
    assert l1(_Ctx(off_hour, [], kl4h=_h4_after_drop(3))) is False


# ── ⑤ 배선 ──────────────────────────────────────────────────────────────
def test_registered_in_paper_rules_and_series_carries_daily():
    keys = {r.key: r.side for r in CL.RULES}
    assert keys["zone_l1_rebound_long"] == "LONG" and keys["zone_s4_spike_top_short"] == "SHORT"
    series = PT.Series.build(bars(M15, flat(80)), [])
    assert series.k1d is None and series.ctx(70).kl1d is None
    series.k1d = _d1(D1_DOWN)
    assert series.ctx(70).kl1d is series.k1d
    fired = PT.evaluate_rules(series, 70)
    assert "zone_l1_rebound_long" in fired and "zone_s4_spike_top_short" in fired


def test_worker_fetches_daily_only_when_needed():
    w = (APP / "workers" / "paper_trading_worker.py").read_text(encoding="utf-8")
    i_need, i_eval = w.index("OZ.needs_daily("), w.index("fired = PT.evaluate_rules(series, j)")
    assert i_need < i_eval, "일봉은 규칙 평가 전에 채워야 한다"
    assert 'interval="1d", limit=61' in w and "series.k1d = " in w


# ── ⑥ 주문 경로 없음 ────────────────────────────────────────────────────
def test_no_order_path():
    src = (APP / "services" / "opportunity_zones.py").read_text(encoding="utf-8")
    for bad in ("execution_service", "strategy_service", "place_order", "create_order", "new_order", "StrategyInstance"):
        assert bad not in src, bad
    import ast
    mods = {n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)}
    assert mods <= {"__future__", "typing", "app.services"}


# ── ⑦ 보고서에 규칙으로 잡힌다 ──────────────────────────────────────────
def test_report_counts_new_rules():
    from tests.test_fix370_paper_report_v3 import _mk, _report, dt
    day = date(2026, 9, 25)
    rows = [_mk(f"A{i}USDT", "LONG", "zone_l1_rebound_long", 4.0, dt(day, 1, 0)) for i in range(5)]
    rows += [_mk(f"B{i}USDT", "SHORT", "zone_s4_spike_top_short", 6.0, dt(day, 2, 0)) for i in range(3)]
    rep = _report(rows, now=dt(day, 12, 0))
    assert "zone_l1_rebound_long" in rep["blocks"]["all"]["rules"]["LONG"]
    assert "zone_s4_spike_top_short" in rep["blocks"]["all"]["rules"]["SHORT"]


def test_not_wired_to_any_live_family():
    """가상만 — 규칙 가족(rf_*, 실주문 후보)에 연결되지 않는다. 연결은 7일 판정 뒤 사장님 결정."""
    from app.services import rule_families as RF
    fam_rules = {f.rule for f in RF.FAMILIES}
    assert not fam_rules & {"zone_l1_rebound_long", "zone_s4_spike_top_short"}
