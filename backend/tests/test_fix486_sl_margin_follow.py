"""🛡 Fix 486 — 증거금을 넣으면 손절선도 따라 내려가게 (단위 테스트 · 실측 재현).

사장님 (2026-11-11): "증거금을 넣으면 손절선도 따라 내려가게" · "운영중인 인스턴스도 모두 같이 적용되게 해줘"

실측 #4570 PONSUSDT LONG: 증거금 추가 2,100 USDT 로 거래소 청산가는 0.12885 였는데
시스템 손절은 0.14249(ROI −100%)에서 닫았다(−13,355.73). 이 파일은 그 숫자를 그대로 재현해
「이제는 0.1418 에서 닫지 않고, 청산 가드 0.13271 에서 닫는다」를 고정한다.
불변식(I1~I7)은 tests/properties/test_pbt_sl_margin_follow.py (Hypothesis).
"""
from __future__ import annotations

from decimal import Decimal as D

import pytest

from app.services import sl_margin_follow as F

P = F.FollowParams()
# 2026-11-11 01:55:57 KST 스냅샷 (운영 DB 실측)
CASE = dict(
    side="LONG", sl_pct=D("100"), leverage=D("2"), qty=D("93036"), avg_entry=D("0.28497878"),
    added_margin_recorded=D("2100"),
    snap_qty=D("93036"), snap_entry_price=D("0.28497878"),
    snap_isolated_margin=D("1949.23720918"), snap_unrealized_pnl=D("-13150.53905148"),
    snap_liq_price=D("0.12884510"), snap_margin_type="isolated", snapshot_age_sec=15,
)


def roi_long(mark: D, avg: D = CASE["avg_entry"], lev: D = D("2")) -> D:
    return (mark - avg) / avg * 100 * lev


class TestReal4570:
    def test_no_longer_stops_at_old_line(self):
        """옛 손절가 0.1418(ROI −100.48%)에서는 이제 닫지 않는다."""
        mark = D("0.1418")
        r = F.follow(**CASE, mark_price=mark, params=P)
        assert r.applied and not r.guard_hit
        assert r.extra_margin == pytest.approx(D("1843.13"), abs=D("0.5"))      # 지갑 15,099.78 − 초기 13,256.64
        assert r.sl_pct_effective == pytest.approx(D("113.90"), abs=D("0.05"))
        assert roi_long(mark) <= -100                                           # 옛 규칙이면 손절
        assert F.should_stop(roi=roi_long(mark), sl_pct=D("100"), result=r) is False

    def test_stops_at_liquidation_guard(self):
        """거래소 청산가 0.12885 의 3% 위(0.13271)에 닿으면 닫는다 — 거래소 청산보다 먼저."""
        r_above = F.follow(**CASE, mark_price=D("0.1330"), params=P)
        assert not r_above.guard_hit
        assert F.should_stop(roi=roi_long(D("0.1330")), sl_pct=D("100"), result=r_above) is False
        r_hit = F.follow(**CASE, mark_price=D("0.1327"), params=P)
        assert r_hit.guard_hit and r_hit.guard_price == pytest.approx(D("0.132710"), abs=D("0.000001"))
        assert F.should_stop(roi=roi_long(D("0.1327")), sl_pct=D("100"), result=r_hit) is True

    def test_extra_capped_by_recorded_adds(self):
        """DB 기록(A)이 500 뿐이면 거래소 지갑이 더 커 보여도 500 까지만 인정한다."""
        r = F.follow(**{**CASE, "added_margin_recorded": D("500")}, mark_price=D("0.14"), params=P)
        assert r.applied and r.extra_margin == D("500")


class TestFallsBackToOldRule:
    @pytest.mark.parametrize("patch,why", [
        ({"added_margin_recorded": D("0")}, "기록 없음"),
        ({"added_margin_recorded": None}, "기록 없음"),
        ({"snapshot_age_sec": 301}, "오래됨"),
        ({"snapshot_age_sec": None}, "스냅샷 없음"),
        ({"snap_liq_price": D("0")}, "청산가 없음"),
        ({"snap_liq_price": None}, "청산가 없음"),
        ({"snap_liq_price": D("0.30")}, "청산가가 평단 위(LONG)"),
        ({"snap_margin_type": "cross"}, "교차"),
        ({"snap_isolated_margin": None}, "값 결손"),
        ({"snap_qty": D("0")}, "수량 0"),
        ({"snap_isolated_margin": D("105")}, "지갑에 추가분 없음"),   # W = 13,255 < M0
        ({"leverage": D("0")}, "레버리지 0"),
        ({"side": "FLAT"}, "방향 불명"),
        ({"avg_entry": D("NaN")}, "NaN"),
    ])
    def test_not_applied(self, patch, why):
        r = F.follow(**{**CASE, **patch}, mark_price=D("0.1418"), params=P)
        assert r.applied is False, why
        assert r.sl_pct_effective == D("100") and r.guard_hit is False and r.extra_margin == 0
        # 옛 판정과 같다
        assert F.should_stop(roi=D("-100.48"), sl_pct=D("100"), result=r) is True
        assert F.should_stop(roi=D("-99.9"), sl_pct=D("100"), result=r) is False

    def test_disabled(self):
        r = F.follow(**CASE, mark_price=D("0.1418"), params=F.FollowParams(enabled=False))
        assert r.applied is False and r.reason == "꺼짐"

    def test_never_raises_on_garbage(self):
        r = F.follow(side=None, sl_pct="x", leverage=object(), qty=[], avg_entry={}, mark_price="",
                     added_margin_recorded="?", snap_qty=None, snap_entry_price=None,
                     snap_isolated_margin=None, snap_unrealized_pnl=None, snap_liq_price=None,
                     snap_margin_type=None, snapshot_age_sec="old", params=P)
        assert r.applied is False
        assert F.should_stop(roi="bad", sl_pct="bad", result=r) is False


class TestPositionChanges:
    def test_position_add_keeps_extra(self):
        """「포지션 추가」 직후 스냅샷이 아직 옛 수량이어도 추가분 E 는 유지된다
        (옛 손절선이 되살아나 추가 주문 하나로 전량 청산되지 않는다)."""
        r = F.follow(**{**CASE, "qty": D("103036"), "avg_entry": D("0.2711")}, mark_price=D("0.1418"), params=P)
        assert r.applied and r.extra_margin == pytest.approx(D("1843.13"), abs=D("0.5"))

    def test_partial_close_scales_extra(self):
        """부분 청산으로 수량이 절반이면 인정 추가분도 절반 (스냅샷이 아직 옛 수량일 때)."""
        r = F.follow(**{**CASE, "qty": D("46518")}, mark_price=D("0.1418"), params=P)
        assert r.applied and r.extra_margin == pytest.approx(D("921.57"), abs=D("0.5"))


class TestShortSide:
    SHORT = dict(
        side="SHORT", sl_pct=D("100"), leverage=D("2"), qty=D("-1000"), avg_entry=D("1.00"),
        added_margin_recorded=D("100"),
        snap_qty=D("-1000"), snap_entry_price=D("1.00"),
        snap_isolated_margin=D("100"), snap_unrealized_pnl=D("-500"),     # 지갑 600 = 초기 500 + 추가 100
        snap_liq_price=D("1.58"), snap_margin_type="isolated", snapshot_age_sec=10,
    )

    def test_short_follow_and_guard(self):
        r = F.follow(**self.SHORT, mark_price=D("1.50"), params=P)        # ROI −100%
        assert r.applied and r.sl_pct_effective == D("120") and not r.guard_hit
        assert F.should_stop(roi=D("-100"), sl_pct=D("100"), result=r) is False
        r2 = F.follow(**self.SHORT, mark_price=D("1.54"), params=P)       # 가드 1.58 × 0.97 = 1.5326
        assert r2.guard_hit
        assert F.should_stop(roi=D("-108"), sl_pct=D("100"), result=r2) is True


def test_guard_never_fires_before_old_line():
    """가드에 닿아도 옛 손절선(−sl_pct)을 넘기 전에는 닫지 않는다 (I1)."""
    r = F.FollowResult(True, D("120"), True, D("10"), "x", D("1"))
    assert F.should_stop(roi=D("-50"), sl_pct=D("100"), result=r) is False
    assert F.should_stop(roi=D("-100"), sl_pct=D("100"), result=r) is True


class TestPositionAddBeforeSnapshot:
    """「포지션 추가」가 아직 스냅샷에 없는 ≤2분 — 청산가를 새 수량으로 다시 추정해 보수적인 쪽을 쓴다."""

    def test_low_leverage_add_keeps_snapshot_guard(self):
        """레버 2: 추가 뒤 실제 청산가는 내려간다(추정 0.1236 < 스냅샷 0.1288) → 스냅샷 가드 유지."""
        r = F.follow(**{**CASE, "qty": D("103036"), "avg_entry": D("0.27108282")}, mark_price=D("0.1418"), params=P)
        assert r.applied and "보수 추정" in r.reason
        assert r.guard_price == pytest.approx(D("0.132710"), abs=D("0.000001"))

    def test_high_leverage_add_raises_guard(self):
        """레버 10: 청산가(0.8889) 근처보다 높은 0.99 에 같은 수량을 더하면 실제 청산가가 올라간다(≈0.8944).
        스냅샷 청산가만 보면 가드(0.9156)가 실제보다 낮다 → 추정값으로 올려 세운다(≈0.9213)."""
        c = dict(side="LONG", sl_pct=D("100"), leverage=D("10"), qty=D("200"), avg_entry=D("0.995"),
                 added_margin_recorded=D("2"), snap_qty=D("100"), snap_entry_price=D("1"),
                 snap_isolated_margin=D("1"), snap_unrealized_pnl=D("-11"),      # 지갑 12 = 초기 10 + 추가 2
                 snap_liq_price=D("0.8889"), snap_margin_type="isolated", snapshot_age_sec=20)
        r = F.follow(**c, mark_price=D("0.95"), params=P)
        assert r.applied and r.extra_margin == D("2")
        assert r.guard_price > D("0.8889") * D("1.03")
        assert r.guard_price == pytest.approx(D("0.92127"), abs=D("0.0005"))

    def test_estimate_impossible_falls_back(self):
        """수량은 늘었는데 원가가 늘지 않았다(스냅샷·전략 값이 서로 안 맞음) → 옛 판정."""
        r = F.follow(**{**CASE, "qty": D("103036"), "avg_entry": D("0.2")}, mark_price=D("0.1418"), params=P)
        assert r.applied is False

    def test_short_add_lowers_guard(self):
        """SHORT 레버 10: 1.01 에 같은 수량을 더하면 실제 청산가가 내려온다(1.1089 → ≈1.1045) → 가드도 내려 세운다."""
        c = dict(side="SHORT", sl_pct=D("100"), leverage=D("10"), qty=D("-200"), avg_entry=D("1.005"),
                 added_margin_recorded=D("2"), snap_qty=D("-100"), snap_entry_price=D("1"),
                 snap_isolated_margin=D("1"), snap_unrealized_pnl=D("-11"),      # 지갑 12 = 초기 10 + 추가 2
                 snap_liq_price=D("1.10891"), snap_margin_type="isolated", snapshot_age_sec=20)
        r = F.follow(**c, mark_price=D("1.05"), params=P)
        assert r.applied and r.extra_margin == D("2")
        assert r.guard_price < D("1.10891") * D("0.97")
        assert r.guard_price == pytest.approx(D("1.07132"), abs=D("0.0005"))
