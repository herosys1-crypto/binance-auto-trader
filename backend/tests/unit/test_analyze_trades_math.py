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


def _mod():
    spec = importlib.util.spec_from_file_location("_analyze_trades", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stat_cls():
    return _mod().Stat


def test_worker_grouping_strips_symbol_names():
    """🚨 심볼이 그룹 이름에 섞이면 워커별 성적을 볼 수 없다.

    실측 사고: 볼밴 분할 22건이 `PUMPSPLIT_BTRUSDT` / `PUMPSPLIT_TACUSDT` ... 처럼
    **심볼 수만큼 쪼개져** 「건수 2건」짜리 그룹이 줄줄이 나왔다.
    그 상태로는 「이 워커가 버는가」를 판단할 수 없다.
    """
    f = _mod()._normalize_source
    assert f("PUMPSPLIT_BTRUSDT_20260830") == "PUMPSPLIT"
    assert f("PUMPSPLIT_TACUSDT_20260829") == "PUMPSPLIT"
    assert f("PUMPSPLIT_BTRUSDT_1") == f("PUMPSPLIT_ZKPUSDT_2"), "같은 워커로 합쳐야 한다"


def test_manual_is_identified_by_quick_prefix():
    """수동/자동을 가르는 기준 — 이게 틀리면 「자동만 분석」이 무의미해진다."""
    f = _mod()._normalize_source
    assert f("_quick_20260831120000") == "수동(직접입력)"
    assert f("auto_bb_break_SAJANGNIM_BO") != "수동(직접입력)"


def test_grouping_never_crashes_on_odd_names():
    f = _mod()._normalize_source
    for name in ("", "BTCUSDT", "___", "X" * 60, "auto"):
        assert isinstance(f(name), str) and f(name)


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


# ── Fix 246: 중첩 entry_context 를 자동으로 펼친다 ──────────────────

def test_nested_entry_context_is_flattened():
    """🚨 실측 사고 — entry_context 가 71.2% 차 있는데 「비어 있습니다」가 나왔다.

    옛 코드는 `rsi_15m` 같은 **평탄 키를 가정**했는데 실제 저장 구조는
    ema_vcp / sar_ichimoku / confluence / bb_top / pump_dump /
    pump_continuation / bb_4h 7개 하위 dict 로 **중첩**돼 있다.
    키 이름을 추측하면 스키마가 바뀔 때마다 조용히 눈이 먼다.
    """
    f = _mod()._flatten
    out = f({"ema_vcp": {"grade": 3, "score": 0.7}, "bb_top": {"rsi": 68.2}})
    assert out == {"ema_vcp.grade": 3.0, "ema_vcp.score": 0.7, "bb_top.rsi": 68.2}


def test_flatten_keeps_only_usable_numbers():
    """문자열·None·무계값은 버린다 — obv_slope_pct 2,249,160 사고의 재발 방지."""
    f = _mod()._flatten
    out = f({"a": "문자열", "b": None, "c": 1.5, "d": True, "e": 1e15,
             "f": float("nan")})
    assert out == {"c": 1.5, "d": 1.0}


def test_flatten_survives_odd_shapes():
    f = _mod()._flatten
    assert f(None) == {}
    assert f({}) == {}
    assert f({"a": [1, 2, 3]}) == {}
    deep = {"a": {"b": {"c": {"d": {"e": {"f": 1.0}}}}}}
    assert isinstance(f(deep), dict)          # 깊이 제한에 걸려도 죽지 않는다


def test_effect_size_is_scale_free():
    """🚨 척도가 다른 지표를 raw 차이로 줄세우면 RSI(0~100)가 항상 이긴다.

    효과크기(차이/표준편차)로 재야 비율값(0~1)과 공정하게 비교된다.
    """
    m = _mod()
    small = [0.10, 0.12, 0.11, 0.13, 0.12]
    small_hi = [0.50, 0.52, 0.51, 0.53, 0.52]
    big = [50.0, 52.0, 51.0, 53.0, 52.0]
    big_hi = [54.0, 56.0, 55.0, 57.0, 56.0]
    eff_small = (m._median(small_hi) - m._median(small)) / m._stdev(small + small_hi)
    eff_big = (m._median(big_hi) - m._median(big)) / m._stdev(big + big_hi)
    assert eff_small > eff_big, "작은 척도의 뚜렷한 차이가 과소평가된다"
