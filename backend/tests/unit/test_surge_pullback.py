"""🛡️ Fix 243 — 「급등 중 조정 → 다시 급등」 판정 가드.

## 사장님 verbatim (2026-08-31)

    "급등중에 조정은 다시 급등으로 간다고 했어 바로 수익을 많이 낼수 있고 했고"

## 임계값의 출처 (추측 아님)

수동 LONG 의 진입 시점 지표를 캔들에서 복원한 실측 (Fix 242):

    지표            이긴 진입    진 진입
    ────────────────────────────────────
    CCI 15m          +110.6     +36.9
    3일 변동%          +65.5%    +35.5%
    RSI 15m            67.4      53.9
    볼밴위치 15m        0.877     0.611
    되돌림 4H           0.083     0.580
    OBV방향 4H         +0.168    +0.020

    되돌림 1.00 초과(원점 아래) = 6건 -1,845.38  ← 하드 차단 근거

🚨 이 파일은 **임계값이 소리 없이 바뀌는 것**을 막는다.
   숫자를 바꾸려면 새 실측 근거가 있어야 한다.
"""
from __future__ import annotations

from app.services.surge_pullback import (
    MIN_PASSED,
    THRESHOLDS,
    evaluate_surge_pullback,
)


def _rally(peak_at_end: bool = True) -> list[float]:
    """+50% 상승 파동. 끝에서 살짝 조정(되돌림 약 0.1)."""
    up = [100.0 + i * 1.0 for i in range(50)]      # 100 -> 149
    return up + [147.0, 145.0] if peak_at_end else up


def _round_trip() -> list[float]:
    """급등 후 원점 아래까지 붕괴 (되돌림 > 1.0)."""
    return [100.0 + i * 1.0 for i in range(50)] + [120.0, 105.0, 95.0]


# ───────────────────────────────── 사장님 자리

def test_winning_profile_passes():
    """실측 승자 프로파일이 통과하지 않으면 이 게이트는 쓸모가 없다."""
    s = evaluate_surge_pullback(
        closes_4h=_rally(),
        chg_3d_pct=65.5, cci_15m=110.6, rsi_15m=67.4,
        bb_pos_15m=0.877, obv_dir_4h=0.168,
    )
    assert s.ok, s.detail
    assert s.blocked is None


def test_losing_profile_fails():
    """실측 패자 프로파일이 통과하면 걸러내는 의미가 없다."""
    s = evaluate_surge_pullback(
        closes_4h=_rally(),
        chg_3d_pct=35.5, cci_15m=36.9, rsi_15m=53.9,
        bb_pos_15m=0.611, obv_dir_4h=0.020,
    )
    assert not s.ok, s.detail


def test_current_auto_long_entry_is_rejected():
    """🚨 지금 자동 LONG 이 사는 자리(과매도 바닥)는 반드시 걸러져야 한다.

    실측: CCI 15m 약 -78 / RSI 39.7 / 볼밴 0.284 에서 진입 -> 승률 16.1%.
    이 게이트의 존재 이유가 바로 이 자리를 막는 것이다.
    """
    s = evaluate_surge_pullback(
        closes_4h=_rally(),
        chg_3d_pct=24.6, cci_15m=-78.4, rsi_15m=39.7,
        bb_pos_15m=0.284, obv_dir_4h=0.287,
    )
    assert not s.ok, f"과매도 바닥이 통과됐다: {s.detail}"


# ───────────────────────────────── 하드 차단

def test_round_trip_is_hard_blocked():
    """🚨 원점 아래 = 실측 6건 -1,845. 점수와 무관하게 차단해야 한다."""
    s = evaluate_surge_pullback(
        closes_4h=_round_trip(),
        chg_3d_pct=99.0, cci_15m=200.0, rsi_15m=80.0,
        bb_pos_15m=1.0, obv_dir_4h=0.9,      # 나머지는 전부 만점
    )
    assert not s.ok
    assert s.blocked and "되돌림" in s.blocked


def test_deep_pullback_is_hard_blocked():
    """되돌림 0.58(패자 중앙값)은 **필수 조건 실패** = 차단이다 (Fix 250).

    옛 구조에서는 6개 중 1개일 뿐이라 나머지 4개로 통과할 수 있었다.
    """
    closes = [100.0 + i for i in range(50)] + [120.0]   # 되돌림 약 0.6
    s = evaluate_surge_pullback(
        closes_4h=closes, chg_3d_pct=65.0,
        cci_15m=200.0, rsi_15m=75.0, bb_pos_15m=0.9, obv_dir_4h=0.3,
    )
    assert not s.ok and not s.blocked, "경로 불일치를 하드 차단으로 만들면 안 된다"
    assert "조정이 깊다" in s.detail["reject"]


# ───────────────────────────────── 결측 처리

def test_missing_values_do_not_count_as_pass():
    """🚨 「모르는데 통과」는 이 프로젝트에서 반복된 사고 유형이다 (fail-closed)."""
    s = evaluate_surge_pullback(closes_4h=None)
    assert s.passed == 0
    assert not s.ok
    assert len(s.detail["missing"]) >= 3


def test_partial_data_still_decidable():
    """일부만 있어도 4개를 넘으면 판정된다 (전부 요구하면 진입이 안 난다)."""
    s = evaluate_surge_pullback(
        closes_4h=_rally(),
        chg_3d_pct=65.0, cci_15m=120.0, rsi_15m=70.0, bb_pos_15m=0.9,
        obv_dir_4h=None,
    )
    assert s.ok and "OBV 안 꺾임" in s.detail["missing"]


def test_broken_values_do_not_raise():
    s = evaluate_surge_pullback(
        closes_4h=["없음", None, 3], chg_3d_pct="많이", cci_15m=None,
        rsi_15m=float("nan"), bb_pos_15m="", obv_dir_4h=[],
    )
    assert not s.ok


# ───────────────────────────────── 임계값 고정

def test_thresholds_match_the_measurement():
    """🚨 숫자가 소리 없이 바뀌면 실측 근거와 끊긴다.

    바꾸려면 새 실측(analyze_entry_patterns) 결과를 근거로 대야 한다.
    """
    assert THRESHOLDS["chg_3d_min"] == 45.0        # 패 35.5 < 45 < 승 65.5
    assert THRESHOLDS["cci_15m_min"] == 60.0       # 패 36.9 < 60 < 승 110.6
    assert THRESHOLDS["rsi_15m_min"] == 58.0       # 패 53.9 < 58 < 승 67.4
    assert THRESHOLDS["bb_pos_15m_min"] == 0.70    # 패 0.611 < 0.70 < 승 0.877
    assert THRESHOLDS["retrace_max"] == 0.35       # 승 0.083 / 패 0.580
    assert THRESHOLDS["retrace_hard_block"] == 1.00  # 실측 6건 -1,845
    assert THRESHOLDS["obv_4h_min"] == 0.08        # 패 0.020 < 0.08 < 승 0.168
    assert MIN_PASSED == 3                          # Fix 250: 선택 4개 중 3개


def test_thresholds_sit_between_win_and_loss_medians():
    """과적합 방지 — 임계가 승자 중앙값에 붙으면 표본 12건에 맞춘 것이 된다."""
    pairs = [
        ("chg_3d_min", 35.5, 65.5),
        ("cci_15m_min", 36.9, 110.6),
        ("rsi_15m_min", 53.9, 67.4),
        ("bb_pos_15m_min", 0.611, 0.877),
        ("obv_4h_min", 0.020, 0.168),
    ]
    for key, loser, winner in pairs:
        t = THRESHOLDS[key]
        assert loser <= t < winner, f"{key}={t} 가 승/패 중앙값 사이에 없다"


# ── Fix 250: 정의 조건은 **필수**다 ────────────────────────────────

def test_the_real_false_positive_is_blocked():
    """🚨 배포 첫날 실측 — 이 종목이 1순위로 뽑혔다.

        [Fix244] LIGHTUSDT 급등중 조정 = LONG 1순위 (4/6 통과)
                 3일 -18.0%  되돌림 0.568  볼밴 1.18  CCI 240  RSI 69

    3일 -18% 는 급등이 아니라 **하락 중**이고 되돌림 0.568 은 얕은 조정이 아니다.
    「급등 중 조정」을 **정의하는 두 조건을 둘 다 실패**했는데
    타이밍 지표 4개만으로 4/6 을 채워 통과했다 = 「6중 4」 규칙의 설계 결함.
    """
    closes = [100.0 + i for i in range(50)] + [147.0, 145.0]
    s = evaluate_surge_pullback(
        closes_4h=closes, chg_3d_pct=-18.0,
        cci_15m=240.9, rsi_15m=68.8, bb_pos_15m=1.07, obv_dir_4h=0.2,
    )
    assert not s.ok, s.detail
    assert not s.blocked, "🚨 급락 경로까지 막으면 안 된다 (Fix 252)"
    assert "급등 중이 아니다" in s.detail["reject"]


def test_chasing_above_the_band_is_blocked():
    """볼밴 상단 밖(>1.05)에서 사는 것은 추격매수. 실측 승자 중앙값은 0.877."""
    closes = [100.0 + i for i in range(50)] + [147.0, 145.0]
    s = evaluate_surge_pullback(
        closes_4h=closes, chg_3d_pct=65.0,
        cci_15m=200.0, rsi_15m=70.0, bb_pos_15m=1.18, obv_dir_4h=0.2,
    )
    assert not s.ok and not s.blocked
    assert "추격매수" in s.detail["reject"]


def test_defining_conditions_cannot_be_outvoted():
    """🚨 나머지가 만점이어도 정의 조건 하나만 실패하면 차단이어야 한다."""
    closes = [100.0 + i for i in range(50)] + [147.0, 145.0]
    perfect_timing = dict(cci_15m=300.0, rsi_15m=80.0, bb_pos_15m=0.9, obv_dir_4h=0.9)
    assert not evaluate_surge_pullback(
        closes_4h=closes, chg_3d_pct=10.0, **perfect_timing
    ).ok, "급등 실패인데 통과됐다"
    deep = [100.0 + i for i in range(50)] + [120.0]
    assert not evaluate_surge_pullback(
        closes_4h=deep, chg_3d_pct=65.0, **perfect_timing
    ).ok, "깊은 조정인데 통과됐다"


# ── Fix 252: blocked 는 「LONG 자체 금지」에만 쓴다 ────────────────────

def test_blocked_is_reserved_for_doctrine_violation():
    """🚨 실측 사고 — 이 구분이 없어 LONG 진입이 **100% 막혔다**.

        [auto_long_bottom] 완료: scanned=35 entered=0 | 사유: nd:ROUND_TRIP_BLOCKED0=35

    워커는 `blocked` 를 보면 **급락 경로(패턴 B)까지 통째로 건너뛴다**.
    그래서 「3일 +45% 미만」같은 **경로 불일치**를 blocked 로 만들면
    사장님이 금지하지 않은 급락 진입까지 사라진다.

        사장님: "급락한건 ... **포지션 진입을 하지 않는다고 안헀어**"

    blocked = 원점 아래(되돌림 >= 1.00) = 사장님 사상 ⑤ 위반, **그것만**.
    """
    closes = [100.0 + i for i in range(50)] + [147.0, 145.0]
    # 경로 불일치 3종 — 전부 blocked 가 아니어야 한다
    for kw in (
        dict(chg_3d_pct=-18.0, cci_15m=240.0, rsi_15m=68.0, bb_pos_15m=1.02),
        dict(chg_3d_pct=65.0, cci_15m=240.0, rsi_15m=68.0, bb_pos_15m=1.18),
    ):
        s = evaluate_surge_pullback(closes_4h=closes, obv_dir_4h=0.2, **kw)
        assert not s.ok
        assert not s.blocked, f"경로 불일치가 하드 차단이 됐다: {s.detail}"
        assert s.detail.get("reject"), "왜 아닌지 사유가 없다"
    # 깊은 조정도 마찬가지
    deep = [100.0 + i for i in range(50)] + [120.0]
    s = evaluate_surge_pullback(
        closes_4h=deep, chg_3d_pct=65.0, cci_15m=200.0, rsi_15m=75.0,
        bb_pos_15m=0.9, obv_dir_4h=0.3,
    )
    assert not s.ok and not s.blocked

    # 진짜 차단은 원점 아래 하나뿐
    rt = [100.0 + i for i in range(50)] + [120.0, 105.0, 95.0]
    s = evaluate_surge_pullback(
        closes_4h=rt, chg_3d_pct=99.0, cci_15m=200.0, rsi_15m=80.0,
        bb_pos_15m=1.0, obv_dir_4h=0.9,
    )
    assert s.blocked and "되돌림" in s.blocked


def test_reason_explains_path_mismatch():
    """로그에 「왜 이 경로가 아닌지」가 보여야 한다."""
    closes = [100.0 + i for i in range(50)] + [147.0, 145.0]
    s = evaluate_surge_pullback(closes_4h=closes, chg_3d_pct=-18.0)
    assert "해당 없음" in s.reason
