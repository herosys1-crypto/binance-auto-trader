"""🛡️ Fix 248 — 「너무 빨리 들어간 SHORT」 차단 가드.

## 사장님 verbatim (2026-08-31, SKRUSDT 차트)

    "이렇게 큰하락에 포지션진입을 해야 하는데 **너무 빨리 진입하여 큰손실**을 본거야"

방향은 맞았고 타이밍만 일렀다.

## 실패 사례 (실측)

    SKRUSDT #1873   진입 평단 0.019818 (상승 중 SHORT)
                    이후 정점 0.034856 (+75.9%)
                    강제청산 0.023333  ROI -35.48% / -724.80
                    그 뒤 실제 하락 -> 0.023 (-33.8%)   <- 방향은 맞았다

## 사장님이 보여주신 「진짜 자리」 (1시간봉)

    볼밴 위치 0.471 (중단선 아래)  /  MACD 히스트 -0.000633 (음수 전환)
    고점 대비 -33.8%

## 실측 데이터도 같은 말

    진 SHORT   볼밴 4H **1.005** (상단 밖)
    이긴 SHORT 볼밴 4H 0.923
"""
from __future__ import annotations

from app.services.peak_drop_short import THRESHOLDS, evaluate_peak_drop_short


def _rally_then_drop() -> list[float]:
    """0.010 -> 0.0348 급등 후 0.023 까지 하락 (SKR 실제 모양)."""
    up = [0.010 + i * 0.0005 for i in range(50)]        # -> 0.0345
    return up + [0.0348, 0.030, 0.027, 0.0245, 0.0232]


def _still_rallying() -> list[float]:
    return [0.010 + i * 0.0005 for i in range(55)]      # 마지막이 최고가


# ───────────────────────────────── 차단 (= 너무 빠름)

def test_blocks_when_above_upper_band():
    """🚨 실측 진 SHORT 중앙값이 볼밴 1.005 = 상단 밖에서 들어갔다."""
    v = evaluate_peak_drop_short(
        closes=_rally_then_drop(), bb_pos=1.005, macd_hist=-0.0001,
    )
    assert not v.allow and "급등 중" in v.reason


def test_blocks_when_macd_still_positive():
    """MACD 히스토그램이 양수 = 아직 상승 모멘텀 = 사장님의 「너무 빨리」."""
    v = evaluate_peak_drop_short(
        closes=_rally_then_drop(), bb_pos=0.8, macd_hist=+0.0005,
    )
    assert not v.allow and "상승 모멘텀" in v.reason


def test_blocks_at_the_very_peak():
    """🚨 #1873 재현 — 신고가 갱신 중에는 SHORT 를 넣지 않는다."""
    v = evaluate_peak_drop_short(
        closes=_still_rallying(), bb_pos=0.95, macd_hist=-0.00001,
    )
    assert not v.allow and "정점 미확인" in v.reason
    assert v.detail["drop_from_peak_pct"] < 1.0


# ───────────────────────────────── 허용 (= 사장님이 말한 자리)

def test_allows_the_real_entry_point():
    """사장님이 보여주신 1시간봉 상태 — 볼밴 0.471 / MACD -0.000633 / -33.8%."""
    v = evaluate_peak_drop_short(
        closes=_rally_then_drop(), bb_pos=0.471, macd_hist=-0.000633,
    )
    assert v.allow, v.reason
    assert v.detail["drop_from_peak_pct"] > 30


def test_allows_modest_but_confirmed_turn():
    """-33% 까지 기다리면 늦다. 3% 만 되돌아도 「확인」으로 본다."""
    closes = [0.010 + i * 0.0005 for i in range(50)] + [0.0331]  # 0.0345 -> -4.1%
    v = evaluate_peak_drop_short(closes=closes, bb_pos=0.9, macd_hist=-0.00001)
    assert v.allow, v.reason
    assert 3.0 < v.detail["drop_from_peak_pct"] < 6.0


# ───────────────────────────────── 결측 (fail-open)

def test_missing_values_do_not_block():
    """🚨 차단 전용 게이트라 「모름」으로 기회를 없애지 않는다."""
    assert evaluate_peak_drop_short(closes=None).allow
    assert evaluate_peak_drop_short(closes=[], bb_pos=None, macd_hist=None).allow


def test_broken_values_do_not_raise():
    v = evaluate_peak_drop_short(
        closes=["없음", None, 0], bb_pos="많이", macd_hist=float("nan"),
    )
    assert v.allow


def test_short_series_skips_the_peak_check():
    v = evaluate_peak_drop_short(closes=[1.0, 2.0], bb_pos=0.5, macd_hist=-1.0)
    assert v.allow and v.detail.get("peak_why") == "봉 부족"


# ───────────────────────────────── 임계값 고정

def test_thresholds_match_the_evidence():
    """숫자가 소리 없이 바뀌면 근거와 끊긴다."""
    assert THRESHOLDS["bb_pos_max"] == 1.00        # 진 SHORT 중앙값 1.005
    assert THRESHOLDS["min_drop_from_peak_pct"] == 3.0
    assert THRESHOLDS["peak_lookback"] == 60.0


def test_gate_is_a_blocker_not_a_requirement():
    """🚨 정점 확인을 **요구**하면 진입이 거의 안 난다 (볼밴 3차 0건 사고와 같은 함정).

    아무 정보도 없을 때 기본이 「허용」이어야 한다.
    """
    assert evaluate_peak_drop_short(closes=None).allow is True


# ── 사장님 사상 ④ — 하단 부근 + OBV 상승 = 반등 위험 ────────────────

def test_blocks_rebound_risk_at_lower_band():
    """🚨 사장님 verbatim ④:

        "볼밴 하단까지 갔다가도 **obv가 강하면 이것도 다시 상승으로 전환**된다고 봐야해"

    사장님이 보여주신 SKR 15분봉 3장 연속 (2026-08-31 18시대):
        가격   0.023120 -> 0.023383 -> 0.023449
        RSI(6)   24.5   ->   28.5   ->   29.4     과매도에서 회복
        OBV     2.201B  ->  2.43B   ->  2.451B    상승
        볼밴 위치  0.120 (하단 부근)

    여기서 SHORT 를 넣으면 반등에 맞는다 — #1873(너무 빠름)과 **정반대 방향**의 실패다.
    """
    v = evaluate_peak_drop_short(
        closes=_rally_then_drop(), bb_pos=0.120, macd_hist=-0.000538, obv_dir=+0.15,
    )
    assert not v.allow
    assert "반등 위험" in v.reason and "obv가 강하면" in v.reason


def test_lower_band_with_falling_obv_still_allowed():
    """하단이어도 OBV 가 같이 죽어 있으면 그건 진짜 하락이다 = 허용."""
    v = evaluate_peak_drop_short(
        closes=_rally_then_drop(), bb_pos=0.120, macd_hist=-0.0005, obv_dir=-0.20,
    )
    assert v.allow, v.reason


def test_mid_band_with_rising_obv_is_not_blocked_by_this_rule():
    """이 규칙은 **하단 부근**에만 적용된다 — 중단에서 OBV 상승은 별개 문제다."""
    v = evaluate_peak_drop_short(
        closes=_rally_then_drop(), bb_pos=0.471, macd_hist=-0.000633, obv_dir=+0.15,
    )
    assert v.allow, v.reason


def test_the_two_failures_are_opposite_ends():
    """🚨 진입 창(window) — 위쪽 끝과 아래쪽 끝을 각각 막고 그 사이만 남긴다."""
    closes = _rally_then_drop()
    too_early = evaluate_peak_drop_short(
        closes=closes, bb_pos=1.005, macd_hist=-0.0001, obv_dir=-0.1,
    )
    too_late = evaluate_peak_drop_short(
        closes=closes, bb_pos=0.10, macd_hist=-0.0005, obv_dir=+0.2,
    )
    just_right = evaluate_peak_drop_short(
        closes=closes, bb_pos=0.471, macd_hist=-0.000633, obv_dir=-0.05,
    )
    assert not too_early.allow and not too_late.allow and just_right.allow


def test_rebound_thresholds_are_pinned():
    assert THRESHOLDS["bb_pos_min"] == 0.20
    assert THRESHOLDS["obv_rebound_min"] == 0.0
    assert THRESHOLDS["bb_pos_min"] < THRESHOLDS["bb_pos_max"], "창이 뒤집혔다"


# ── 연결 확인 ────────────────────────────────────────────────────

from pathlib import Path  # noqa: E402

_SIG = (
    Path(__file__).resolve().parents[2]
    / "app" / "services" / "stage_entry_signal.py"
)


def _sig_code() -> str:
    return chr(10).join(
        ln for ln in _SIG.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_wired_into_short_gate_chain():
    """모든 SHORT 진입이 지나는 게이트 사슬에 있어야 한다."""
    code = _sig_code()
    assert "evaluate_peak_drop_short" in code
    assert 'if _side == "SHORT":' in code


def test_runs_before_confirm_peak():
    """정점 확인보다 앞이어야 「너무 빠른 진입」이 거기 도달하기 전에 걸린다."""
    code = _sig_code()
    i_win = code.index("evaluate_peak_drop_short")
    i_peak = code.index("from app.services.peak_confirmation import confirm_peak")
    assert i_win < i_peak, "진입창이 confirm_peak 뒤에 있다"


def test_defaults_to_off_with_preview_log():
    """🚨 얼마나 막는지 먼저 봐야 한다. OFF 여도 「막았을 것」이 보여야 한다."""
    src = _SIG.read_text(encoding="utf-8")
    assert '"entry_window_short_enabled", False' in src, "기본값이 OFF 가 아니다"
    assert "막았을 것" in src, "예고 로그가 없다"
    assert "entry_window_short_enabled=1" in src, "켜는 방법이 로그에 없다"


def test_failure_is_fail_open():
    """판정 실패로 SHORT 가 통째로 멈추면 안 된다."""
    code = _sig_code()
    i = code.index("evaluate_peak_drop_short")
    window = code[i: i + 2500]
    assert "fail-open" in window


def test_verdict_is_recorded_in_detail():
    """학습 표본이 되도록 판정 근거가 detail 에 남아야 한다."""
    code = _sig_code()
    assert '"entry_window"' in code
