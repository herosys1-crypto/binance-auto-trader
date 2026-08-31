"""🛡️ Fix 239 — 매매 분석 도구의 **산수**를 고정한다.

사장님 지시 (2026-08-31):
  "익절과 손절에서 우리 로직이 효율적으로 잘 작동하는지 **검증**하고
   실패보다는 익절을 많이 할수 있는 로직을 만들수 있게 **데이터를 수집**해줘"

분석이 틀리면 그 위에서 내리는 모든 결정이 틀린다.
특히 **기대값(expectancy)** 은 「이 전략을 계속하면 벌 것인가」를 결정하는 숫자라
부호 하나만 틀려도 정반대의 결론을 낸다.

옛 사고 선례: 「LONG 승률 15.2%」 로 오보한 적이 있다 —
COMPLETED 가 stopped_at 을 안 남겨 성공 234건이 집계에서 통째로 빠졌었다.
그래서 집계 로직은 반드시 검증한다.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "analyze_trades.py"


def _stat_cls():
    spec = importlib.util.spec_from_file_location("_analyze_trades", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Stat


def test_basic_aggregation():
    Stat = _stat_cls()
    s = Stat()
    for p in (10.0, 20.0, -5.0, -5.0, -5.0):
        s.add(p)
    assert s.n == 5
    assert s.win_rate == 40.0
    assert s.avg_win == 15.0
    assert s.avg_loss == -5.0
    assert s.rr == 3.0
    assert s.total == 15.0


def test_expectancy_sign_decides_go_or_stop():
    """🚨 기대값 부호 = 「계속할 것인가」의 답. 여기가 틀리면 결론이 뒤집힌다."""
    Stat = _stat_cls()
    good = Stat()
    for p in (10.0, 10.0, -5.0):        # 승률 67%, 손익비 2.0
        good.add(p)
    assert good.expectancy > 0

    bad = Stat()
    for p in (10.0, -20.0, -20.0):      # 승률 33%, 손익비 0.5
        bad.add(p)
    assert bad.expectancy < 0, "잃는 전략을 벌고 있다고 보고하면 안 된다"


def test_zero_pnl_counts_but_does_not_skew_win_rate():
    """본전(0) 은 건수엔 들어가되 승률 분모에선 빠진다 — 승률을 희석하지 않는다."""
    Stat = _stat_cls()
    s = Stat()
    s.add(10.0)
    s.add(-10.0)
    s.add(0.0)
    assert s.n == 3
    assert s.win_rate == 50.0


def test_no_division_by_zero_on_empty_or_one_sided():
    Stat = _stat_cls()
    empty = Stat()
    assert empty.n == 0 and empty.win_rate == 0.0 and empty.rr == 0.0
    assert empty.expectancy == 0.0 and empty.total == 0.0

    only_wins = Stat()
    only_wins.add(5.0)
    assert only_wins.win_rate == 100.0
    assert only_wins.rr == 0.0, "패가 없으면 손익비는 정의되지 않는다 (0 으로 표시)"
    assert only_wins.expectancy == 5.0

    only_losses = Stat()
    only_losses.add(-5.0)
    assert only_losses.win_rate == 0.0
    assert only_losses.expectancy == -5.0


def test_totals_match_sum_of_inputs():
    """합계가 입력의 합과 다르면 어떤 결론도 못 믿는다."""
    Stat = _stat_cls()
    vals = [3.5, -1.25, 0.0, 100.0, -99.75]
    s = Stat()
    for v in vals:
        s.add(v)
    assert abs(s.total - sum(vals)) < 1e-9
    assert s.n == len(vals)
