"""🎚 Fix 378 (2026-09-18 사장님) — 가상매매로 나온 문제의 미세조정 후보를 **사전등록**만 한다.

사장님: "문제점을 일부 수정해서 다시 검증을 하는게 좋을듯 한데 가상매매로 나온 문제를 수정해서
        전략을 미세조정해서 가상매매를 계속해 보는건 어떤가?"

원칙: 실주문 판정(entry_conditions·chart_gate_live)은 **건드리지 않는다.** 후보는 보고서 필터로만 등록하고,
7일 표본(클러스터 300 · 긍정일 70%)을 채우면 그때 사장님이 켤지 정한다.

후보 (가상 9일 · 발견 9/9~9/13 · 검증 9/14~9/18 · 두 기간 모두 통과 쪽이 나은 것만):
  P8  SHORT 게이트 + 1시간 ATR ≤ 1.5%            발견 ex +1.67(막힘 −0.71) · 검증 +0.75(−1.41)
  P9  SHORT 게이트 + 4시간 하단이탈 뒤 14봉+       발견 +2.35(+0.12) · 검증 +2.24(−2.25) · 검증 5/5일
      값이 None = 「최근 60봉 안에 이탈 없음」(38%) 은 universe 에서 뺀다 — 발견 +2.79/검증 −0.62 로 뒤집히는 집단
  P10 LONG 게이트 or (고점추격 아님 & 일봉 %B ≤0.5) 발견 +0.34(−0.86) · 검증 +1.25(−0.21)
"""
from datetime import date
from pathlib import Path

import pytest

from app.services import paper_report_v3 as PR3
from tests.test_fix370_paper_report_v3 import _mk, _report, dt

APP = Path(__file__).resolve().parents[1] / "app"
DAY = date(2026, 9, 26)


def mk(sym, side, **gate):
    r = _mk(sym, side, "myrule", 3.0, dt(DAY, 1, 0))
    r["gate"] = gate
    return r


def filters(rows, side):
    return _report(rows, now=dt(DAY, 12, 0))["blocks"]["all"]["filters"][side]


# ── 숫자는 한곳에 ───────────────────────────────────────────────────────
def test_tuning_numbers():
    assert PR3.TUNE == {"short_max_atr_1h_pct": 1.5, "short_min_bars_since_h4_lower": 14.0, "long_max_d1_pctb": 0.5}


# ── P8: SHORT 게이트 + 저변동 ──────────────────────────────────────────
def _short(sym, *, hi=-1.0, trend="FLAT", atr=1.0, since=20.0):
    return mk(sym, "SHORT", h1_from_hi=hi, d1_trend=trend, h1_atr=atr, h4_since_lower=since)


def test_p8_needs_gate_pass_and_calm_hour():
    rows = [_short(f"OK{i}USDT", atr=1.2) for i in range(4)]             # 게이트 통과 + 조용함 → 통과
    rows += [_short(f"WILD{i}USDT", atr=2.0) for i in range(3)]          # 변동 큼 → 제외
    rows += [_short(f"CHASE{i}USDT", hi=-9.0, atr=1.0) for i in range(2)]  # 게이트 불통과(이미 내려옴) → 제외
    rows += [_short(f"UP{i}USDT", trend="UP", atr=1.0) for i in range(2)]  # 일봉 상승 → 제외
    rows += [mk(f"OLD{i}USDT", "SHORT", h1_from_hi=-1.0, d1_trend="FLAT") for i in range(3)]   # ATR 없음 = universe 밖
    f = filters(rows, "SHORT")["P8_short_calm_hour"]
    assert (f["universe"]["n"], f["kept"]["n"], f["excluded"]["n"]) == (11, 4, 7)


def test_p8_boundary_is_inclusive():
    rows = [_short(f"B{i}USDT", atr=1.5) for i in range(3)] + [_short(f"O{i}USDT", atr=1.51) for i in range(3)]
    f = filters(rows, "SHORT")["P8_short_calm_hour"]
    assert f["kept"]["n"] == 3 and f["excluded"]["n"] == 3


# ── P9: SHORT 게이트 + 급락 직후 아님 ─────────────────────────────────
def test_p9_blocks_right_after_h4_breakdown():
    rows = [_short(f"OK{i}USDT", since=14.0) for i in range(4)]          # 14봉 = 통과(경계 포함)
    rows += [_short(f"FRESH{i}USDT", since=3.0) for i in range(3)]       # 이탈 직후 → 제외
    rows += [_short(f"UP{i}USDT", trend="UP", since=30.0) for i in range(2)]   # 게이트 불통과 → 제외
    rows += [mk(f"OLD{i}USDT", "SHORT", h1_from_hi=-1.0, d1_trend="FLAT", h1_atr=1.0) for i in range(2)]  # 값 없음
    f = filters(rows, "SHORT")["P9_short_not_after_breakdown"]
    assert (f["universe"]["n"], f["kept"]["n"], f["excluded"]["n"]) == (9, 4, 5)


# ── P10: LONG 게이트 또는 (고점추격 아님 & 일봉 하단권) ───────────────
def _long(sym, *, chg=2.0, m5=-1.0, hi=-3.0, pctb=0.3):
    return mk(sym, "LONG", chg24=chg, m5_from_hi=m5, h1_from_hi=hi, d1_pctb=pctb)


def test_p10_two_branches():
    rows = [_long(f"DROP{i}USDT", chg=-8.0, hi=-0.2, pctb=0.9) for i in range(3)]   # 게이트 가지(24h 급락)
    rows += [_long(f"PULL{i}USDT", chg=2.0, m5=-6.0, hi=-0.2, pctb=0.9) for i in range(2)]  # 게이트 가지(5분 조정)
    rows += [_long(f"LOW{i}USDT", chg=8.0, hi=-4.0, pctb=0.3) for i in range(3)]    # P7 가지 + 하단권
    rows += [_long(f"HIGH{i}USDT", chg=8.0, hi=-4.0, pctb=0.8) for i in range(2)]   # 하단권 아님 → 제외
    rows += [_long(f"CHASE{i}USDT", chg=8.0, hi=-0.5, pctb=0.2) for i in range(2)]  # 고점 추격 → 제외
    rows += [mk(f"OLD{i}USDT", "LONG", chg24=-8.0, h1_from_hi=-3.0) for i in range(3)]      # %B 없음 = universe 밖
    f = filters(rows, "LONG")["P10_long_gate_or_low_band"]
    assert (f["universe"]["n"], f["kept"]["n"], f["excluded"]["n"]) == (12, 8, 4)


# ── 고를 때 본 행은 판정에서 뺀다 ──────────────────────────────────────
def test_filter_prereg_cutoff_excludes_rows_used_for_picking():
    """P8~P10 은 9/18 에 골랐다 — 9/19 자정 이전에 열린 행은 universe 에서 빠져야 한다."""
    assert PR3.FILTER_PREREG["P8_short_calm_hour"].startswith("2026-09-19")
    assert PR3.FILTER_PREREG["P7_long_no_high_chase"].startswith("2026-09-19")

    def at(day, sym, **gate):
        r = _mk(sym, "SHORT", "myrule", 3.0, dt(day, 1, 0))
        r["gate"] = dict(h1_from_hi=-1.0, d1_trend="FLAT", h1_atr=1.0, h4_since_lower=20.0, **gate)
        return r
    rows = [at(date(2026, 9, 18), f"OLD{i}USDT") for i in range(5)]          # 고를 때 본 날 = 제외
    rows += [at(date(2026, 9, 20), f"NEW{i}USDT") for i in range(4)]         # 등록 뒤 = 센다
    f = _report(rows, now=dt(date(2026, 9, 26), 12, 0))["blocks"]["all"]["filters"]["SHORT"]
    assert f["P8_short_calm_hour"]["universe"]["n"] == 4
    assert f["P8_short_calm_hour"]["since"].startswith("2026-09-19")
    assert f["P1_drop_weak_rules"]["universe"]["n"] == 9, "P1 은 필터별 차단을 쓰지 않는다"


# ── 실주문 판정은 건드리지 않았다 ──────────────────────────────────────
def test_live_judgement_untouched():
    from app.services import entry_conditions as EC
    assert set(EC.DEFAULT_PARAMS) == {
        "short_max_below_high_pct", "short_block_d1_trend", "long_min_drop_24h_pct", "long_min_pullback_5m_pct",
        "short_allow_no_daily_trend", "surge_min_pullback_1h_pct", "surge_max_chg24_pct", "surge_dead_zone_chg24",
    }, "미세조정 후보는 보고서에만 등록한다 — 실주문 판정 파라미터를 늘리지 않는다"
    src = (APP / "services" / "chart_gate_live.py").read_text(encoding="utf-8")
    assert "TUNE" not in src and "atr" not in src.lower()


def test_all_filters_render():
    rows = ([_short(f"S{i}USDT") for i in range(12)] + [_long(f"L{i}USDT", chg=-8.0) for i in range(12)])
    rep = _report(rows, now=dt(DAY, 12, 0))
    names = {n for side in ("LONG", "SHORT") for n in rep["blocks"]["all"]["filters"][side]}
    for want in ("P5_short_near_high_not_d1_up", "P6_long_after_drop_or_pullback", "P7_long_no_high_chase",
                 "P8_short_calm_hour", "P9_short_not_after_breakdown", "P10_long_gate_or_low_band"):
        assert want in names, want
    assert PR3.render_markdown_v3(rep)
