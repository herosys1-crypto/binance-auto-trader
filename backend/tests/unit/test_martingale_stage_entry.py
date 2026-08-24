"""Fix 59 (2026-08-24): 마틴게일 단계별 진입 조건 단위 테스트.

3개 진입 워커의 방어선 통합 검증:
  1. stage_trigger_worker       — 다음 stage 자동 진입 (매 10초!)
  2. realtime_reentry_worker    — 실시간 재진입 (매 15분!)
  3. peak_break_reversal_worker — 전고점 돌파 후 반전 (매 30초!)

사장님 사상 (Fix 55, 2026-08-24 verbatim):
  "충분히 상승/하락 반복 → 조정 시점 진입 → 3단계까지 실패는 말이 안돼!"

= 2단계 = 지표 반전 2/3 통과 (MEDIUM)
= 3단계+ = 지표 반전 3/3 통과 (STRICT!)
= 헌법 64: 급등 SHORT / 급락 LONG = 물타기 폭발 방지!
= 사장님 v219 마틴게일: 300 → 600 → 1800 (3단계까지만!)
= Fix 53 라스트 챈스: 3단계 SL 후 = 1회만 동일 자본 재진입 허용!
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 공통 helper — 실 DB/API 없이 mock 데이터 생성.
# ---------------------------------------------------------------------------


def _mk_analyzer_result(rsi_now, rsi_prev, macd_hist_now, macd_hist_prev, obv_now, obv_5ago):
    """ChartAnalyzer.analyze_timeframe 이 반환하는 dict 모형.

    obv 는 5봉 이상 필요 (worker 가 obv[-1] - obv[-5] 로 slope 계산).
    """
    return {
        "rsi_now": rsi_now,
        "rsi_prev": rsi_prev,
        "macd_hist": [macd_hist_prev, macd_hist_now],
        "obv": [obv_5ago, 0.0, 0.0, 0.0, obv_now],
    }


def _mk_klines(closes: list[float], vols: list[float] | None = None) -> list[list]:
    """Binance kline row = [openTime, open, high, low, close, volume, ...]."""
    if vols is None:
        vols = [1000.0] * len(closes)
    rows: list[list] = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c
        rows.append([
            1_700_000_000_000 + i * 60_000,
            o, max(o, c), min(o, c), c, vols[i],
        ])
    return rows


# ===========================================================================
# stage_trigger_worker (Fix 55 = 마틴게일 2단계+ 방어선!)
# ===========================================================================


class TestStageTriggerIndicatorReversal:
    """`_check_stage_indicator_reversal` = 사장님 Fix 55 핵심 gate.

    given: RSI/MACD/OBV 3중 반전 지표 mock
    when : 2단계 vs 3단계 호출
    then : 2단계=2/3, 3단계+=3/3 통과 요건 정확히 적용
    """

    def test_stage2_all_three_signals_reversal_passes(self):
        """given SHORT + 3/3 반전 지표 / when stage=2 / then PASS + required=2."""
        from app.workers.stage_trigger_worker import _check_stage_indicator_reversal
        result = _mk_analyzer_result(
            rsi_now=50.0, rsi_prev=55.0,            # RSI -5 하락 (≥ -1 필요)
            macd_hist_now=-0.1, macd_hist_prev=0.2, # MACD hist 감소
            obv_now=90.0, obv_5ago=100.0,           # OBV slope = -10 < 0
        )
        with patch(
            "app.services.chart_analyzer.ChartAnalyzer.analyze_timeframe",
            return_value=result,
        ):
            passed, detail = _check_stage_indicator_reversal(
                bc=MagicMock(), symbol="BTCUSDT", side="SHORT", next_stage=2,
            )
        assert passed is True
        assert detail["passed"] == 3
        assert detail["required"] == 2  # 2단계 = MEDIUM

    def test_stage3_stricter_requires_all_three(self):
        """given 2/3만 반전 (RSI 변화 없음) / when stage=2 vs stage=3 /
        then stage2=PASS (loose) but stage3=FAIL (strict)!
        = 자본 폭발 방지 계단식 gate 증명.
        """
        from app.workers.stage_trigger_worker import _check_stage_indicator_reversal
        result = _mk_analyzer_result(
            rsi_now=55.0, rsi_prev=55.0,            # RSI 변화 없음 → reversal X
            macd_hist_now=-0.1, macd_hist_prev=0.2, # MACD 감소 ✓
            obv_now=90.0, obv_5ago=100.0,           # OBV 감소 ✓
        )
        with patch(
            "app.services.chart_analyzer.ChartAnalyzer.analyze_timeframe",
            return_value=result,
        ):
            passed_s2, detail_s2 = _check_stage_indicator_reversal(
                bc=MagicMock(), symbol="BTCUSDT", side="SHORT", next_stage=2,
            )
            passed_s3, detail_s3 = _check_stage_indicator_reversal(
                bc=MagicMock(), symbol="BTCUSDT", side="SHORT", next_stage=3,
            )
        # 2단계 = 2/3 통과 = PASS
        assert passed_s2 is True
        assert detail_s2["required"] == 2
        assert detail_s2["passed"] == 2
        # 3단계 = 3/3 필수 = FAIL
        assert passed_s3 is False
        assert detail_s3["required"] == 3
        assert detail_s3["passed"] == 2

    def test_stage4_also_stricter(self):
        """given 2/3 지표 / when stage=4 / then FAIL (3단계 이상 = 모두 STRICT!)."""
        from app.workers.stage_trigger_worker import _check_stage_indicator_reversal
        result = _mk_analyzer_result(
            rsi_now=55.0, rsi_prev=55.0,            # X
            macd_hist_now=-0.1, macd_hist_prev=0.2, # ✓
            obv_now=90.0, obv_5ago=100.0,           # ✓
        )
        with patch(
            "app.services.chart_analyzer.ChartAnalyzer.analyze_timeframe",
            return_value=result,
        ):
            passed, detail = _check_stage_indicator_reversal(
                bc=MagicMock(), symbol="BTCUSDT", side="SHORT", next_stage=4,
            )
        assert passed is False
        assert detail["required"] == 3

    def test_long_side_requires_upward_reversal(self):
        """given LONG + RSI/MACD/OBV 상승 반전 / when 호출 / then PASS.
        = LONG = 하락세 꺾임 확인 (반대 방향 검사!).
        """
        from app.workers.stage_trigger_worker import _check_stage_indicator_reversal
        result = _mk_analyzer_result(
            rsi_now=45.0, rsi_prev=40.0,             # +5 상승 (> +1 필요)
            macd_hist_now=0.2, macd_hist_prev=-0.1,  # MACD hist 상승
            obv_now=110.0, obv_5ago=100.0,           # OBV slope = +10 > 0
        )
        with patch(
            "app.services.chart_analyzer.ChartAnalyzer.analyze_timeframe",
            return_value=result,
        ):
            passed, detail = _check_stage_indicator_reversal(
                bc=MagicMock(), symbol="ETHUSDT", side="LONG", next_stage=2,
            )
        assert passed is True
        assert detail["passed"] == 3
        assert detail["rsi"] is True
        assert detail["macd"] is True
        assert detail["obv"] is True

    def test_analyze_exception_fail_safe_returns_false(self):
        """given analyze_timeframe 예외 / when 호출 / then False (skip = 자본 보호!)."""
        from app.workers.stage_trigger_worker import _check_stage_indicator_reversal
        with patch(
            "app.services.chart_analyzer.ChartAnalyzer.analyze_timeframe",
            side_effect=RuntimeError("Binance down"),
        ):
            passed, detail = _check_stage_indicator_reversal(
                bc=MagicMock(), symbol="BTCUSDT", side="SHORT", next_stage=2,
            )
        assert passed is False
        assert "error" in detail

    def test_empty_analyze_result_returns_false(self):
        """given analyze_timeframe 빈 결과 / when 호출 / then False."""
        from app.workers.stage_trigger_worker import _check_stage_indicator_reversal
        with patch(
            "app.services.chart_analyzer.ChartAnalyzer.analyze_timeframe",
            return_value=None,
        ):
            passed, _ = _check_stage_indicator_reversal(
                bc=MagicMock(), symbol="BTCUSDT", side="SHORT", next_stage=2,
            )
        assert passed is False


class TestStageTrigger24hFilter:
    """`_check_stage_24h_filter` = 헌법 64 (급등 반대매매 금지!).

    사장님 사고: SHORT + 급등에 진입 = 물타기 폭발 → 자본 폭발!
    → 24h ±15% 초과 = 자동 skip + fail-open (ticker 실패 시 진입 허용).
    """

    def test_short_pump_above_15pct_blocked(self):
        """given SHORT + 24h +20.5% / when 필터 / then skip (False, 20.5)."""
        from app.workers.stage_trigger_worker import _check_stage_24h_filter
        bc = MagicMock()
        bc.get_24hr_ticker.return_value = {"priceChangePercent": "20.5"}
        ok, chg = _check_stage_24h_filter(bc, "SHIBUSDT", "SHORT")
        assert ok is False
        assert chg == 20.5

    def test_short_pump_below_threshold_ok(self):
        """given SHORT + 24h +10% / when 필터 / then pass."""
        from app.workers.stage_trigger_worker import _check_stage_24h_filter
        bc = MagicMock()
        bc.get_24hr_ticker.return_value = {"priceChangePercent": "10.0"}
        ok, chg = _check_stage_24h_filter(bc, "SHIBUSDT", "SHORT")
        assert ok is True
        assert chg == 10.0

    def test_long_dump_below_minus_15pct_blocked(self):
        """given LONG + 24h -18% / when 필터 / then skip (급락에 LONG = 물타기!)."""
        from app.workers.stage_trigger_worker import _check_stage_24h_filter
        bc = MagicMock()
        bc.get_24hr_ticker.return_value = {"priceChangePercent": "-18.0"}
        ok, chg = _check_stage_24h_filter(bc, "PEPEUSDT", "LONG")
        assert ok is False
        assert chg == -18.0

    def test_long_mild_dump_ok(self):
        """given LONG + 24h -8% / when 필터 / then pass (한도 이내!)."""
        from app.workers.stage_trigger_worker import _check_stage_24h_filter
        bc = MagicMock()
        bc.get_24hr_ticker.return_value = {"priceChangePercent": "-8.0"}
        ok, chg = _check_stage_24h_filter(bc, "PEPEUSDT", "LONG")
        assert ok is True
        assert chg == -8.0

    def test_short_exactly_15pct_boundary(self):
        """given SHORT + 24h +15.0% / when 필터 / then skip (≥ 15% 경계 포함!)."""
        from app.workers.stage_trigger_worker import _check_stage_24h_filter
        bc = MagicMock()
        bc.get_24hr_ticker.return_value = {"priceChangePercent": "15.0"}
        ok, chg = _check_stage_24h_filter(bc, "BTCUSDT", "SHORT")
        assert ok is False  # ≥ 15% = skip 경계값 확인

    def test_ticker_exception_fail_open(self):
        """given ticker 예외 / when 필터 / then True + chg=None (진입 허용 = 기존 로직 유지!)."""
        from app.workers.stage_trigger_worker import _check_stage_24h_filter
        bc = MagicMock()
        bc.get_24hr_ticker.side_effect = ConnectionError("api down")
        ok, chg = _check_stage_24h_filter(bc, "BTCUSDT", "SHORT")
        assert ok is True
        assert chg is None


# ===========================================================================
# realtime_reentry_worker (Fix 55 P3 = 단계별 계단식 강화!)
# ===========================================================================


class TestRealtimeReentryConstants:
    """단계별 min_passed 상수 = 계단식 강화 헌법 (Fix 55 P3, 2026-08-24)."""

    def test_min_passed_stage2_is_loose_2(self):
        """MIN_PASSED_STAGE2 = 2 (기존 유지, loose)."""
        from app.workers.realtime_reentry_worker import MIN_PASSED_STAGE2
        assert MIN_PASSED_STAGE2 == 2

    def test_min_passed_stage3_is_strict_3(self):
        """MIN_PASSED_STAGE3 = 3 (엄격 = 자본 폭발 방지!)."""
        from app.workers.realtime_reentry_worker import MIN_PASSED_STAGE3
        assert MIN_PASSED_STAGE3 == 3

    def test_min_passed_stage_last_is_strict_3(self):
        """MIN_PASSED_STAGE_LAST = 3 (라스트 챈스 = 매우 엄격!)."""
        from app.workers.realtime_reentry_worker import MIN_PASSED_STAGE_LAST
        assert MIN_PASSED_STAGE_LAST == 3

    def test_stage_gate_progression_is_monotonic_strict(self):
        """계단식: stage2(loose) < stage3(strict) ≤ stage_last(strict)."""
        from app.workers.realtime_reentry_worker import (
            MIN_PASSED_STAGE2,
            MIN_PASSED_STAGE3,
            MIN_PASSED_STAGE_LAST,
        )
        assert MIN_PASSED_STAGE2 < MIN_PASSED_STAGE3  # 2단계 → 3단계 엄격!
        assert MIN_PASSED_STAGE3 <= MIN_PASSED_STAGE_LAST

    def test_stage3_24h_abs_limit_is_15pct(self):
        """헌법 64 = 3단계+ 24h ±15% 한도!"""
        from app.workers.realtime_reentry_worker import STAGE3_24H_ABS_LIMIT_PCT
        assert STAGE3_24H_ABS_LIMIT_PCT == 15.0

    def test_last_chance_enabled_and_max_stage_4(self):
        """Fix 53 라스트 챈스 = ENABLE_LAST_CHANCE=True + MAX=4 (3단계 + 1회!)."""
        from app.workers.realtime_reentry_worker import (
            ENABLE_LAST_CHANCE,
            MAX_REENTRY_STAGE_WITH_LAST,
        )
        assert ENABLE_LAST_CHANCE is True
        assert MAX_REENTRY_STAGE_WITH_LAST == 4  # 3단계 + 라스트 챈스 1회


class TestRealtimeReentryIndicatorGate:
    """`_check_indicator_reversal_for_reentry` = 3중 반전 gate + 단계별 min_passed 반영."""

    def test_insufficient_klines_returns_false(self):
        """given kline < 35봉 / when 호출 / then False + '부족' 메시지."""
        from app.workers.realtime_reentry_worker import _check_indicator_reversal_for_reentry
        bc = MagicMock()
        bc.get_klines.return_value = _mk_klines([100.0] * 20)  # 20봉만
        ok, msg, _snap = _check_indicator_reversal_for_reentry(
            bc, "BTCUSDT", "SHORT", use_4h=False, min_passed=2,
        )
        assert ok is False
        assert "kline 부족" in msg

    def test_min_passed_argument_recorded_in_snapshot(self):
        """given min_passed 인자 / when 호출 / then snapshot 에 min_passed_required 기록.

        = 단계별 gate 가 실제로 함수 호출 시 전달되는지 검증.
        """
        from app.workers.realtime_reentry_worker import _check_indicator_reversal_for_reentry
        bc = MagicMock()
        # 60봉 (충분!) — 결과는 지표 데이터 의존이라 snapshot 필드만 확인.
        closes = [100.0 + i * 0.1 for i in range(60)]
        bc.get_klines.return_value = _mk_klines(closes)
        _ok, _msg, snap_loose = _check_indicator_reversal_for_reentry(
            bc, "BTCUSDT", "SHORT", use_4h=False, min_passed=2,
        )
        _ok, _msg, snap_strict = _check_indicator_reversal_for_reentry(
            bc, "BTCUSDT", "SHORT", use_4h=False, min_passed=3,
        )
        assert snap_loose["min_passed_required"] == 2
        assert snap_strict["min_passed_required"] == 3

    def test_stricter_gate_never_more_permissive_than_loose(self):
        """same-data invariant: min_passed=3 통과 → min_passed=2 반드시 통과.
        = 계단식 gate 성립 증명 (strict 는 loose 보다 관대할 수 없음!).
        """
        from app.workers.realtime_reentry_worker import _check_indicator_reversal_for_reentry
        bc = MagicMock()
        closes = [100.0 + i * 0.1 for i in range(55)] + [106.5, 107.0, 107.5, 107.8, 108.0]
        bc.get_klines.return_value = _mk_klines(closes)
        ok_strict, _, _ = _check_indicator_reversal_for_reentry(
            bc, "BTCUSDT", "LONG", use_4h=False, min_passed=3,
        )
        ok_loose, _, _ = _check_indicator_reversal_for_reentry(
            bc, "BTCUSDT", "LONG", use_4h=False, min_passed=2,
        )
        # 계단식 gate = strict 통과 시 loose 도 반드시 통과!
        if ok_strict:
            assert ok_loose, "strict 3/3 통과인데 loose 2/3 실패는 논리 위반!"


# ===========================================================================
# peak_break_reversal_worker (Fix 41 = 사장님 사상 6지표 AND!)
# ===========================================================================


class TestPeakBreakStageCapital:
    """`_get_stage_capital` = 사장님 마틴게일 (300 → 600 → 1800!)."""

    def test_stage_capital_progression_300_600_1800(self):
        """given base=300 + max_stage=3 / when stage 1,2,3 / then 300, 600, 1800."""
        from app.workers.peak_break_reversal_worker import _get_stage_capital

        db = MagicMock()

        # db.get(SystemSetting, key) = 2-args → side_effect 도 2-args 시그니처!
        def _get_side(_model, key):
            if key == "sajangnim_default_capital":
                return MagicMock(value="300")
            if key == "sajangnim_max_stage":
                return MagicMock(value="3")
            return None
        db.get.side_effect = _get_side

        assert _get_stage_capital(db, 1) == Decimal("300")
        assert _get_stage_capital(db, 2) == Decimal("600")
        assert _get_stage_capital(db, 3) == Decimal("1800")

    def test_stage_capital_max_stage_2_blocks_stage_3(self):
        """given max_stage=2 (사장님 신 default!) / when stage=3 / then None."""
        from app.workers.peak_break_reversal_worker import _get_stage_capital

        db = MagicMock()

        def _get_side(_model, key):
            if key == "sajangnim_default_capital":
                return MagicMock(value="300")
            if key == "sajangnim_max_stage":
                return MagicMock(value="2")
            return None
        db.get.side_effect = _get_side

        assert _get_stage_capital(db, 1) == Decimal("300")
        assert _get_stage_capital(db, 2) == Decimal("600")
        assert _get_stage_capital(db, 3) is None  # max_stage=2 → 3단계 차단!

    def test_stage_capital_invalid_stage_zero_returns_none(self):
        """stage < 1 = None (방어!)."""
        from app.workers.peak_break_reversal_worker import _get_stage_capital
        db = MagicMock()
        db.get.return_value = None
        assert _get_stage_capital(db, 0) is None
        assert _get_stage_capital(db, -1) is None


class TestPeakBreakReversalSignals:
    """`_check_reversal_signals` = 6지표 AND (사장님 "확실한 하락!")."""

    def test_insufficient_klines_returns_false(self):
        """given kline < 30 / when 호출 / then False + insufficient 사유."""
        from app.workers.peak_break_reversal_worker import _check_reversal_signals
        bc = MagicMock()
        bc.get_klines.return_value = _mk_klines([100.0] * 20)
        ok, snap = _check_reversal_signals(bc, "BTCUSDT")
        assert ok is False
        assert snap.get("reason") == "insufficient"

    def test_exception_returns_false_with_err(self):
        """given get_klines 예외 / when 호출 / then False + err 필드."""
        from app.workers.peak_break_reversal_worker import _check_reversal_signals
        bc = MagicMock()
        bc.get_klines.side_effect = ConnectionError("api down")
        ok, snap = _check_reversal_signals(bc, "BTCUSDT")
        assert ok is False
        assert "err" in snap


class TestPeakBreak24hFilter:
    """`_get_24h_change` = fail-open 0.0 (진입 허용 = 기존 로직 유지!)."""

    def test_returns_pct_from_dict_ticker(self):
        """given dict ticker / when 호출 / then float 반환."""
        from app.workers.peak_break_reversal_worker import _get_24h_change
        bc = MagicMock(spec=["get_24hr_ticker"])
        bc.get_24hr_ticker.return_value = {"priceChangePercent": "12.5"}
        assert _get_24h_change(bc, "BTCUSDT") == 12.5

    def test_returns_zero_when_all_methods_missing(self):
        """given 3 메서드 없음 (get_24hr_ticker, get_ticker_24hr, get_ticker) /
        when 호출 / then 0.0 fail-open!
        """
        from app.workers.peak_break_reversal_worker import _get_24h_change
        bc = MagicMock(spec=[])  # 무 속성 spec
        assert _get_24h_change(bc, "BTCUSDT") == 0.0


# ===========================================================================
# 사장님 v219 마틴게일 자본 계산 (헌법 = 300 → 600 → 1800, 3단계 상한!)
# ===========================================================================


class TestMartingaleCapitalV219:
    """`compute_reentry_capital` = 사장님 v219 (2026-08-22 최종 확정!).

    verbatim: "3단계까지 갈수 있다야 가능하면 가지않는 관리가 필요하다는거야"
    """

    def test_stage2_prev_x2(self):
        """given stage=2 + [300] / when 호출 / then 600 (이전 × 2!)."""
        from app.services.sajangnim_capital import compute_reentry_capital
        result = compute_reentry_capital(2, [Decimal("300")])
        assert result == Decimal("600.00")

    def test_stage3_total_x2(self):
        """given stage=3 + [300, 600] / when 호출 / then 1800 (전체 × 2!) ⚠️매우 신중!"""
        from app.services.sajangnim_capital import compute_reentry_capital
        result = compute_reentry_capital(3, [Decimal("300"), Decimal("600")])
        assert result == Decimal("1800.00")

    def test_stage4_forbidden_returns_none(self):
        """given stage=4 or 5 / when 호출 / then None (사장님 상한 = 3단계까지!)."""
        from app.services.sajangnim_capital import compute_reentry_capital
        assert compute_reentry_capital(
            4, [Decimal("300"), Decimal("600"), Decimal("1800")]
        ) is None
        assert compute_reentry_capital(
            5, [Decimal("300"), Decimal("600"), Decimal("1800")]
        ) is None

    def test_stage1_or_zero_raises(self):
        """given stage <= 1 / when 호출 / then ValueError (compute_stage1_capital 사용!)."""
        from app.services.sajangnim_capital import compute_reentry_capital
        with pytest.raises(ValueError):
            compute_reentry_capital(1, [Decimal("300")])
        with pytest.raises(ValueError):
            compute_reentry_capital(0, [Decimal("300")])

    def test_empty_previous_capitals_raises(self):
        """given previous_capitals 빈 리스트 / when 호출 / then ValueError."""
        from app.services.sajangnim_capital import compute_reentry_capital
        with pytest.raises(ValueError):
            compute_reentry_capital(2, [])

    def test_max_reentry_stage_constant_is_3(self):
        """MAX_REENTRY_STAGE = 3 (사장님 v219 최종 상한!)."""
        from app.services.sajangnim_capital import MAX_REENTRY_STAGE
        assert MAX_REENTRY_STAGE == 3

    def test_stage2_custom_base_capital(self):
        """given base=500 / when stage=2 / then 1000 (사장님 설정 커스텀 확장!)."""
        from app.services.sajangnim_capital import compute_reentry_capital
        result = compute_reentry_capital(2, [Decimal("500")])
        assert result == Decimal("1000.00")

    def test_stage3_custom_base_full_progression(self):
        """given base=500 / when stage=3 with [500, 1000] / then (500+1000)*2 = 3000."""
        from app.services.sajangnim_capital import compute_reentry_capital
        result = compute_reentry_capital(3, [Decimal("500"), Decimal("1000")])
        assert result == Decimal("3000.00")
