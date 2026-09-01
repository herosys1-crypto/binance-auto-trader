"""Fix 276 — 볼밴 1차 진입 「밴드 밖 → 극값에서 꺾임」 단위 테스트.

사장님 사상 검증 지점:
  ① 극값은 **불리 방향** (SHORT=신고점 / LONG=신저점) — Fix 260 과 같다
  ② 극값을 **갱신 중**이면 진입하지 않는다 (아직 최고점이 아니다)
  ③ 판정은 **완료봉**으로만 (진행 중 봉이 되돌리면 가짜 신호가 된다)
  ④ 봉수·되돌림·심도는 전부 인자 = 사장님 "고정은 아니야"
"""
from decimal import Decimal

import pytest

from app.services import bb_entry_rules as R


def _series(vals):
    """20MA 밴드가 잡히도록 앞을 평탄하게 채운 종가열."""
    return [100.0] * 40 + list(vals)


def test_상수_사장님_범위_안에_있다():
    # 사장님 "하단 3-5번" / "최상단 2-4번" — 실측 최선을 쓰되 범위 근처
    assert 1 <= R.PERSIST_BARS_LONG <= 5
    assert 2 <= R.PERSIST_BARS_SHORT <= 4
    assert R.DEPTH_PCT == 10.0          # 사장님 "-10%/+10% 전후"


def test_outside_run_연속만_센다():
    closes = [1, 2, 3, 4, 5]
    band = [3, 3, 3, 3, 3]
    # SHORT = 종가 > 상단. i=4 -> 5>3, 4>3, 3>3(X) -> 2봉
    assert R.outside_run(closes, band, "SHORT", 4) == 2
    # LONG = 종가 < 하단. i=1 -> 2<3, 1<3 -> 2봉
    assert R.outside_run(closes, band, "LONG", 1) == 2


def test_outside_run_밴드None_에서_멈춘다():
    closes = [5, 5, 5, 5]
    band = [None, 3, 3, 3]
    assert R.outside_run(closes, band, "SHORT", 3) == 3


def test_extreme_불리방향_극값():
    closes = [10, 30, 20]
    assert R.extreme_of(closes, "SHORT", 0, 2) == 30    # 신고점
    assert R.extreme_of(closes, "LONG", 0, 2) == 10     # 신저점


# ─────────────────────────────────────────────────────────────────────
# SHORT: 상단 밖 N봉 + 신고점에서 꺾임
# ─────────────────────────────────────────────────────────────────────

def test_short_상단밖_지속후_꺾이면_진입():
    # 급등해서 상단 밖으로 나가 4봉 머물고, 마지막 완료봉이 꺾인다
    closes = _series([106, 112, 118, 124, 121, 121])
    #                 ^--- 밖 구간 ---^  ^꺾임  ^진행중봉(무시)
    base, path, why, d = R.evaluate_first_entry(
        closes, "SHORT", persist_bars=4, retrace_pct=0.0, depth_pct=0)
    assert base is not None, why
    assert path == "persist"
    assert "최고점 확인" in why
    assert d["extreme"] == 124.0          # 신고점
    assert d["retrace_pct"] > 0


def test_short_극값_갱신중이면_진입하지_않는다():
    """아직 오르고 있으면 「최고점」이 아니다 — 사장님 사상의 핵심."""
    closes = _series([106, 112, 118, 124, 130, 130])
    base, path, why, d = R.evaluate_first_entry(
        closes, "SHORT", persist_bars=4, retrace_pct=0.0, depth_pct=0)
    assert base is None
    assert "극값 갱신 중" in why


def test_short_지속봉수_모자라면_진입안함():
    closes = _series([106, 104, 104])
    base, _, why, d = R.evaluate_first_entry(
        closes, "SHORT", persist_bars=4, retrace_pct=0.0, depth_pct=0)
    assert base is None
    assert d["persist_run"] < 4


def test_short_되돌림_임계를_지킨다():
    closes = _series([106, 112, 118, 124, 123.9, 123.9])
    # 되돌림 = (124-123.9)/124*100 = 0.081%
    ok, _, _, d = R.evaluate_first_entry(
        closes, "SHORT", persist_bars=4, retrace_pct=0.0, depth_pct=0)
    assert ok is not None
    ng, _, why, _ = R.evaluate_first_entry(
        closes, "SHORT", persist_bars=4, retrace_pct=1.0, depth_pct=0)
    assert ng is None and "되돌림" in why


# ─────────────────────────────────────────────────────────────────────
# LONG: 하단 밖 N봉 + 신저점에서 반등
# ─────────────────────────────────────────────────────────────────────

def test_long_하단밖_지속후_반등하면_진입():
    closes = _series([94, 88, 82, 76, 78, 78])
    base, path, why, d = R.evaluate_first_entry(
        closes, "LONG", persist_bars=2, retrace_pct=0.6, depth_pct=0)
    assert base is not None, why
    assert "최저점 확인" in why
    assert d["extreme"] == 76.0            # 신저점 (LONG 은 min)


def test_long_아직_내려가는중이면_진입안함():
    closes = _series([94, 88, 82, 76, 70, 70])
    base, _, why, _ = R.evaluate_first_entry(
        closes, "LONG", persist_bars=2, retrace_pct=0.0, depth_pct=0)
    assert base is None
    assert "극값 갱신 중" in why


def test_long_24h급등조건은_설정하면_막는다():
    closes = _series([94, 88, 82, 76, 78, 78])
    ok, _, _, _ = R.evaluate_first_entry(
        closes, "LONG", persist_bars=2, retrace_pct=0.6, depth_pct=0,
        chg_24h=20.0, long_min_chg24=10.0)
    assert ok is not None
    ng, _, why, d = R.evaluate_first_entry(
        closes, "LONG", persist_bars=2, retrace_pct=0.6, depth_pct=0,
        chg_24h=2.0, long_min_chg24=10.0)
    assert ng is None
    assert d["blocked_by"] == "chg24"


def test_long_24h_없으면_fail_open():
    """티커를 못 받았다고 사장님 지시를 통째로 막지 않는다."""
    closes = _series([94, 88, 82, 76, 78, 78])
    base, _, _, _ = R.evaluate_first_entry(
        closes, "LONG", persist_bars=2, retrace_pct=0.6, depth_pct=0,
        chg_24h=None, long_min_chg24=10.0)
    assert base is not None


def test_short_은_24h조건의_대상이_아니다():
    """실측: SHORT 에 24h 급등 조건을 더하면 나빠진다 (+276 -> -44)."""
    closes = _series([106, 112, 118, 124, 121, 121])
    base, _, _, _ = R.evaluate_first_entry(
        closes, "SHORT", persist_bars=4, retrace_pct=0.0, depth_pct=0,
        chg_24h=0.0, long_min_chg24=99.0)
    assert base is not None


# ─────────────────────────────────────────────────────────────────────
# 심도 경로 + 완료봉 + 방어
# ─────────────────────────────────────────────────────────────────────

def test_심도경로는_지속봉수가_모자라도_열린다():
    """사장님 "-10% 전후로 큰하락에 무조건진입" — 지속 미달이어도 심도로 들어간다."""
    closes = _series([70, 74, 74])          # 하단보다 한참 아래로 급락 후 반등
    base, path, why, d = R.evaluate_first_entry(
        closes, "LONG", persist_bars=99, retrace_pct=0.0, depth_pct=10.0)
    assert base is not None, why
    assert path == "depth"


def test_판정은_완료봉이다_진행중봉은_무시():
    """closes[-1] 은 진행 중 봉 — 그것 때문에 신호가 생기거나 사라지면 안 된다."""
    done = _series([106, 112, 118, 124, 121])
    a = R.evaluate_first_entry(done + [999], "SHORT", persist_bars=4,
                               retrace_pct=0.0, depth_pct=0)
    b = R.evaluate_first_entry(done + [1], "SHORT", persist_bars=4,
                               retrace_pct=0.0, depth_pct=0)
    assert a[0] == b[0] and a[0] is not None      # 진행 중 봉이 결과를 못 바꾼다


def test_밖_1봉이면_극값판단_불가():
    # 직전 봉은 평탄(=밴드 안, 표준편차 0 이라 상단==100), 완료봉만 밖 -> run=1
    closes = _series([100, 108, 108])
    base, _, why, _ = R.evaluate_first_entry(
        closes, "SHORT", persist_bars=1, retrace_pct=0.0, depth_pct=0)
    assert base is None
    assert "극값 판단 불가" in why


def test_봉이_모자라면_보류():
    base, _, why, _ = R.evaluate_first_entry([1, 2, 3], "SHORT")
    assert base is None and "봉 부족" in why


def test_반환_기준선은_Decimal_이고_밴드값이다():
    closes = _series([106, 112, 118, 124, 121, 121])
    base, _, _, d = R.evaluate_first_entry(
        closes, "SHORT", persist_bars=4, retrace_pct=0.0, depth_pct=0)
    assert isinstance(base, Decimal)
    assert float(base) == pytest.approx(d["base"])


def test_기본상수로도_동작한다():
    """인자를 안 주면 모듈 기본값(실측 최선)을 쓴다."""
    closes = _series([106, 112, 118, 124, 121, 121])
    base, _, why, _ = R.evaluate_first_entry(closes, "SHORT")
    assert base is not None, why
