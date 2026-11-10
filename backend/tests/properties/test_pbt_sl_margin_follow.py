"""Fix 486 — 「증거금을 넣으면 손절선도 따라 내려가게」 불변식 (Hypothesis).

I1 옛 규칙보다 일찍 닫지 않는다        새 손절 ⇒ roi ≤ −sl_pct
I2 기록된 증거금 추가가 없으면 옛 판정과 완전히 같다
I3 상한                              sl_eff ≤ sl_pct × (M0 + A) / M0
I4 스냅샷이 이상하면(오래됨·청산가 없음·교차·결손) 옛 판정과 같다
I5 적용 중 가드선에 닿고 옛 손절선도 넘었으면 반드시 손절
I6 A 가 커질수록 sl_eff 는 줄지 않는다 (단조)
I7 LONG/SHORT 대칭 (거울 입력 → 같은 판정)

대상 구현을 고치거나 반례를 xfail 로 숨기지 않는다. 네트워크·DB 없음.
"""
from decimal import Decimal

import pytest

hypothesis = pytest.importorskip("hypothesis")

from hypothesis import assume, given, strategies as st

from app.services import sl_margin_follow as F

D = Decimal
P = F.FollowParams()


def dec(lo: str, hi: str, places: int = 6):
    return st.decimals(min_value=D(lo), max_value=D(hi), places=places, allow_nan=False, allow_infinity=False)


@st.composite
def long_case(draw):
    """일관된 LONG 포지션 + 격리 스냅샷. 추가 증거금 A_true 가 실제로 지갑에 들어 있다."""
    lev = draw(st.sampled_from([D("1"), D("2"), D("3"), D("5"), D("10")]))
    avg = draw(dec("0.0001", "50000", 6))
    qty = draw(dec("1", "1000000", 2))
    m0 = qty * avg / lev
    assume(m0 > D("1"))
    add_true = draw(dec("0", "3", 4)) * m0                 # 실제 추가 0~3배
    recorded = draw(st.one_of(st.just(D("0")), st.just(add_true), dec("0", "3", 4).map(lambda k: k * m0)))
    drop = draw(dec("0", "0.999", 5))                      # 평단 대비 하락률
    mark = avg * (D("1") - drop)
    assume(mark > 0)
    upnl = (mark - avg) * qty
    liq_ratio = draw(dec("0.01", "0.999", 5))              # 청산가 = 평단 × 비율 (평단 아래)
    return dict(
        side="LONG", sl_pct=draw(st.sampled_from([D("10"), D("25"), D("50"), D("80"), D("100")])),
        leverage=lev, qty=qty, avg_entry=avg, mark_price=mark,
        added_margin_recorded=recorded,
        snap_qty=qty, snap_entry_price=avg,
        snap_isolated_margin=m0 + add_true + upnl, snap_unrealized_pnl=upnl,
        snap_liq_price=avg * liq_ratio, snap_margin_type="isolated",
        snapshot_age_sec=draw(st.integers(min_value=0, max_value=300)),
    )


def roi_of(c) -> Decimal:
    return (c["mark_price"] - c["avg_entry"]) / c["avg_entry"] * 100 * c["leverage"]


def old_stop(c) -> bool:
    return roi_of(c) <= -c["sl_pct"]


@given(long_case())
def test_i1_never_earlier_than_old_rule(c):
    r = F.follow(**c, params=P)
    if F.should_stop(roi=roi_of(c), sl_pct=c["sl_pct"], result=r):
        assert old_stop(c)
    assert r.sl_pct_effective >= c["sl_pct"]


@given(long_case())
def test_i2_no_recorded_add_means_old_rule(c):
    c = {**c, "added_margin_recorded": D("0")}
    r = F.follow(**c, params=P)
    assert r.applied is False and r.sl_pct_effective == c["sl_pct"] and r.guard_hit is False
    assert F.should_stop(roi=roi_of(c), sl_pct=c["sl_pct"], result=r) == old_stop(c)


@given(long_case())
def test_i3_cap_by_recorded_adds(c):
    r = F.follow(**c, params=P)
    m0 = c["qty"] * c["avg_entry"] / c["leverage"]
    cap = c["sl_pct"] * (m0 + max(c["added_margin_recorded"], D("0"))) / m0
    assert r.sl_pct_effective <= cap + D("1e-18")
    assert r.extra_margin <= max(c["added_margin_recorded"], D("0"))


@given(long_case(), st.sampled_from(["stale", "no_liq", "cross", "missing", "liq_above", "no_age"]))
def test_i4_bad_snapshot_means_old_rule(c, how):
    patch = {
        "stale": {"snapshot_age_sec": 301},
        "no_liq": {"snap_liq_price": D("0")},
        "cross": {"snap_margin_type": "cross"},
        "missing": {"snap_isolated_margin": None},
        "liq_above": {"snap_liq_price": c["avg_entry"] * 2},
        "no_age": {"snapshot_age_sec": None},
    }[how]
    c = {**c, **patch}
    r = F.follow(**c, params=P)
    assert r.applied is False
    assert F.should_stop(roi=roi_of(c), sl_pct=c["sl_pct"], result=r) == old_stop(c)


@given(long_case())
def test_i5_guard_always_stops_once_old_line_crossed(c):
    r = F.follow(**c, params=P)
    if r.applied and r.guard_hit and old_stop(c):
        assert F.should_stop(roi=roi_of(c), sl_pct=c["sl_pct"], result=r) is True
    if r.applied:
        assert r.guard_hit == (c["mark_price"] <= c["snap_liq_price"] * (1 + P.liq_buffer_pct / 100))


@given(long_case(), dec("0", "5", 4))
def test_i6_monotone_in_recorded_adds(c, k):
    m0 = c["qty"] * c["avg_entry"] / c["leverage"]
    lo = F.follow(**c, params=P)
    hi = F.follow(**{**c, "added_margin_recorded": c["added_margin_recorded"] + k * m0}, params=P)
    assert hi.sl_pct_effective >= lo.sl_pct_effective


@given(long_case())
def test_i7_long_short_symmetry(c):
    """LONG 을 평단 기준으로 거울에 비춘 SHORT 는 같은 손절% · 같은 판정을 낸다."""
    avg = c["avg_entry"]
    mirror = lambda px: avg + (avg - px)          # noqa: E731
    s = {**c, "side": "SHORT", "qty": -c["qty"], "snap_qty": -c["snap_qty"],
         "mark_price": mirror(c["mark_price"]), "snap_liq_price": mirror(c["snap_liq_price"])}
    rl, rs = F.follow(**c, params=P), F.follow(**s, params=P)
    assert rl.applied == rs.applied
    assert rl.sl_pct_effective == rs.sl_pct_effective and rl.extra_margin == rs.extra_margin
    roi_s = (avg - s["mark_price"]) / avg * 100 * c["leverage"]
    assert roi_s == roi_of(c)
    # 가드선은 곱셈 버퍼라 거울에서 살짝 다르다 → 가드가 안 닿은 경우의 판정만 비교한다
    if not rl.guard_hit and not rs.guard_hit:
        assert (F.should_stop(roi=roi_of(c), sl_pct=c["sl_pct"], result=rl)
                == F.should_stop(roi=roi_s, sl_pct=c["sl_pct"], result=rs))


@given(st.one_of(st.none(), st.text(max_size=5), st.floats(allow_nan=True, allow_infinity=True),
                 st.decimals(allow_nan=True, allow_infinity=True)),
       st.one_of(st.none(), st.floats(allow_nan=True, allow_infinity=True)))
def test_garbage_never_raises(x, y):
    r = F.follow(side=x, sl_pct=x, leverage=y, qty=x, avg_entry=y, mark_price=x,
                 added_margin_recorded=y, snap_qty=x, snap_entry_price=y, snap_isolated_margin=x,
                 snap_unrealized_pnl=y, snap_liq_price=x, snap_margin_type=x, snapshot_age_sec=y, params=P)
    assert isinstance(r, F.FollowResult)
    assert isinstance(F.should_stop(roi=x, sl_pct=y, result=r), bool)


# ══════════════════════════════════════════════════════════════════════════════
# duel 감사(2026-11-11) 반영 — 비공허성·정확값 오라클·구간 의미·경계
#   「applied=True 인데 sl_eff 가 늘 기준과 같다」 같은 과보수 구현은 I1·I3·I6 을 모두 통과한다.
#   그래서 ① 실제로 적용되는 입력을 만들고 ② 분수(Fraction) 오라클과 값을 맞추고
#   ③ 새로 생긴 구간 (−sl_eff, −sl_pct] 안에서의 판정을 전수로 본다.
# ══════════════════════════════════════════════════════════════════════════════
from fractions import Fraction


@st.composite
def applied_case(draw):
    """반드시 적용되는 LONG: 기록 A>0 · 지갑에 추가분 ≥ 5% · 신선 · 격리 · 청산가가 평단 아래."""
    lev = draw(st.sampled_from([D("1"), D("2"), D("3"), D("5")]))
    avg = draw(dec("0.01", "5000", 4))
    qty = draw(dec("1", "100000", 2))
    m0 = qty * avg / lev
    assume(m0 > D("1"))
    add_true = draw(dec("0.05", "2", 4)) * m0
    recorded = draw(st.one_of(st.just(add_true), dec("0.01", "3", 4).map(lambda k: k * m0)))
    mark = avg * (D("1") - draw(dec("0", "0.99", 5)))
    assume(mark > 0)
    upnl = (mark - avg) * qty
    return dict(
        side="LONG", sl_pct=draw(st.sampled_from([D("12.5"), D("25"), D("80"), D("100")])),
        leverage=lev, qty=qty, avg_entry=avg, mark_price=mark, added_margin_recorded=recorded,
        snap_qty=qty, snap_entry_price=avg, snap_isolated_margin=m0 + add_true + upnl,
        snap_unrealized_pnl=upnl, snap_liq_price=avg * draw(dec("0.01", "0.99", 5)),
        snap_margin_type="isolated", snapshot_age_sec=draw(st.integers(0, 300)),
    ), add_true


@given(applied_case())
def test_non_vacuous_and_exact_value(ca):
    """적용되는 입력에서는 실제로 적용되고, 값이 분수 오라클과 맞는다 (내림 1e-12 이내)."""
    c, add_true = ca
    r = F.follow(**c, params=P)
    assert r.applied is True
    m0 = Fraction(c["qty"]) * Fraction(c["avg_entry"]) / Fraction(c["leverage"])
    extra_exact = min(Fraction(add_true), Fraction(c["added_margin_recorded"]))
    assert abs(Fraction(r.extra_margin) - extra_exact) <= extra_exact * Fraction(1, 10**18) + Fraction(1, 10**18)
    eff_exact = Fraction(c["sl_pct"]) * (m0 + extra_exact) / m0
    assert Fraction(r.sl_pct_effective) <= eff_exact + Fraction(1, 10**15)          # 느슨한 쪽으로 새지 않는다
    assert eff_exact - Fraction(r.sl_pct_effective) <= Fraction(1, 10**9)           # 과보수도 아니다
    assert r.sl_pct_effective > c["sl_pct"]                                          # 실제로 넓어졌다


@given(applied_case(), dec("0", "1", 6))
def test_interval_semantics(ca, t):
    """새로 생긴 구간 (−sl_eff, −sl_pct] 안: 가드가 안 닿았으면 버티고, 닿았으면 닫는다."""
    c, _ = ca
    r = F.follow(**c, params=P)
    assume(r.applied and r.sl_pct_effective > c["sl_pct"])
    roi = -(c["sl_pct"] + (r.sl_pct_effective - c["sl_pct"]) * t)       # −sl_pct … −sl_eff
    stopped = F.should_stop(roi=roi, sl_pct=c["sl_pct"], result=r)
    if roi <= -r.sl_pct_effective:
        assert stopped is True
    else:
        assert stopped is bool(r.guard_hit)
    assert F.should_stop(roi=-(c["sl_pct"] * D("0.999")), sl_pct=c["sl_pct"], result=r) is False   # 옛 손절선 전


@given(applied_case(), dec("0", "50", 3))
def test_min_extra_boundary(ca, min_extra):
    """거래소 지갑의 추가분이 문턱(min_extra_pct) 미만이면 미적용, 이상이면 적용."""
    c, add_true = ca
    m0 = c["qty"] * c["avg_entry"] / c["leverage"]
    r = F.follow(**c, params=F.FollowParams(True, D("3"), 300, min_extra))
    threshold = m0 * min_extra / 100
    if add_true < threshold - D("1e-9"):
        assert r.applied is False
    elif add_true > threshold + D("1e-9"):
        assert r.applied is True


@given(applied_case())
def test_opposite_leg_snapshot_rejected(ca):
    """헤지 모드: 반대 다리 스냅샷이면 쓰지 않는다. 단방향("BOTH")·빈 값은 방향 정보가 없으니 통과."""
    c, _ = ca
    assert F.follow(**c, params=P, snap_side="SHORT").applied is False
    assert F.follow(**c, params=P, snap_side="LONG").applied is True
    assert F.follow(**c, params=P, snap_side="BOTH").applied is True
    assert F.follow(**c, params=P, snap_side=None).applied is True


def test_infinite_roi_follows_old_rule():
    """판정 불능이 아니면 옛 규칙과 같다: ROI −∞ 는 손절, +∞ 는 아님, NaN 은 판정 불가(False)."""
    na = F.FollowResult(False, D("100"), False, D("0"), "x")
    assert F.should_stop(roi=D("-Infinity"), sl_pct=D("100"), result=na) is True
    assert F.should_stop(roi=D("Infinity"), sl_pct=D("100"), result=na) is False
    assert F.should_stop(roi=D("NaN"), sl_pct=D("100"), result=na) is False
    ap = F.FollowResult(True, D("120"), False, D("10"), "x", D("1"))
    assert F.should_stop(roi=D("-Infinity"), sl_pct=D("100"), result=ap) is True


# ══════════════════════════════════════════════════════════════════════════════
# Gemini 심판(2026-11-11) 지적 — 수량이 스냅샷과 다를 때 (요구사항 개정: 「옛 판정」 대신 보수 추정)
#   늘었으면(포지션 추가 반영 전) 넓힌 손절%는 유지하되 가드는 스냅샷 가드보다 느슨해지지 않는다.
#   줄었으면(부분 청산) 인정 추가분이 수량 비율만큼 줄어든다. 두 경우 모두 I1·I3 는 그대로다.
# ══════════════════════════════════════════════════════════════════════════════
@given(applied_case(), dec("1.011", "4", 3), dec("0.02", "1.5", 4), dec("0", "1", 6))
def test_qty_increase_guard_never_looser_than_snapshot(ca, grow, fill_ratio, t):
    c, _ = ca
    q_new = c["qty"] * grow
    fill = c["avg_entry"] * fill_ratio                              # 추가 체결가 (평단의 2% ~ 150%)
    avg_new = (c["qty"] * c["avg_entry"] + (q_new - c["qty"]) * fill) / q_new
    c2 = {**c, "qty": q_new, "avg_entry": avg_new}
    r = F.follow(**c2, params=P)
    snap_guard = c["snap_liq_price"] * (1 + P.liq_buffer_pct / 100)
    m0 = q_new * avg_new / c["leverage"]
    if r.applied:
        assert r.guard_price >= snap_guard                          # 스냅샷 가드보다 느슨하지 않다 (LONG = 더 높거나 같다)
        assert r.guard_price < avg_new * (1 + P.liq_buffer_pct / 100)
        assert r.extra_margin <= c["added_margin_recorded"]         # I3
        assert Fraction(r.sl_pct_effective) <= Fraction(c["sl_pct"]) * (Fraction(m0) + Fraction(c["added_margin_recorded"])) / Fraction(m0) + Fraction(1, 10**15)
    else:
        assert r.sl_pct_effective == c["sl_pct"] and r.guard_hit is False
    roi = -(c["sl_pct"] * (D("0.5") + t))                           # 옛 손절선 앞뒤
    if F.should_stop(roi=roi, sl_pct=c["sl_pct"], result=r):
        assert roi <= -c["sl_pct"]                                  # I1


@given(applied_case(), dec("0.01", "0.989", 4))
def test_qty_decrease_scales_extra(ca, keep):
    """부분 청산이 스냅샷에 아직 없을 때: 인정 추가분 ≤ (지갑 추가분 × 남은 비율), 가드는 스냅샷 그대로."""
    c, add_true = ca
    r = F.follow(**{**c, "qty": c["qty"] * keep}, params=P)
    assert r.applied is True
    assert Fraction(r.extra_margin) <= Fraction(add_true) * Fraction(keep) + Fraction(1, 10**15)
    assert r.extra_margin <= c["added_margin_recorded"]
    assert r.guard_price == c["snap_liq_price"] * (1 + P.liq_buffer_pct / 100)
