"""🛡️ Fix 254 — 볼밴 지지 붕괴 = SHORT (사장님 사상 ③).

## 사장님 verbatim

    "급락한것은 **이전급등에 대한 급락**이라 확실한 숏"
    "볼밴 **지지선 붕괴**와 지속하락을 찾아서 분할 포지션 진입"

## 왜 필요했나 — 시스템이 붕괴를 LONG 으로 사고 있었다

`unified_15m_entry._detect_15m_surge` 는 방향을 **부호만으로** 정한다:

    side = "SHORT" if c1h > 0 else "LONG"

BTRUSDT 가 -44% 붕괴하면 「급락」으로 분류돼 **LONG 진입**이 된다.

## BTRUSDT #1488 (단일 최대 손실 -6,552.45)

    0.0138 -> 0.22400 (+1,523%) -> 4~5일 횡보 -> 0.0823 (-44%)

정점과 붕괴 사이가 4~5일. **기다렸어야 할 자리가 「붕괴」다.**
"""
from __future__ import annotations

from pathlib import Path

from app.services.support_breakdown import (
    THRESHOLDS,
    evaluate_support_breakdown,
)

WORKER = (
    Path(__file__).resolve().parents[2]
    / "app" / "workers" / "unified_15m_entry_worker.py"
)

# BTR 실제 모양
_RALLY = [0.0138 + (0.224 - 0.0138) * i / 25 for i in range(26)]
_FLAT = [0.160, 0.165, 0.158, 0.162, 0.155, 0.168, 0.160, 0.157,
         0.163, 0.159, 0.161, 0.156, 0.164, 0.158, 0.160, 0.162]
_BREAK = [0.140, 0.120, 0.098]


def _vols(n: int, spike: float = 4.0) -> list[float]:
    return [100.0] * (n - 1) + [100.0 * spike]


# ───────────────────────────────── 판정

def test_btr_breakdown_is_detected():
    """🚨 BTR 실측 모양 — 이게 안 잡히면 이 파일은 존재 이유가 없다."""
    c = _RALLY + _FLAT + _BREAK
    v = evaluate_support_breakdown(closes=c, volumes=_vols(len(c)), obv_dir=-0.25)
    assert v.ok, v.detail["checks"]
    assert v.detail["prior_rally_pct"] > 1000
    assert v.detail["now"] < v.detail["support"]


def test_strong_obv_makes_it_a_fake_break():
    """🚨 사장님 사상 ④ — OBV 가 안 꺾인 이탈은 **가짜 이탈**이다.

        "볼밴 하단까지 갔다가도 obv가 강하면 이것도 다시 상승으로 전환된다"
    """
    c = _RALLY + _FLAT + _BREAK
    v = evaluate_support_breakdown(closes=c, volumes=_vols(len(c)), obv_dir=+0.30)
    assert not v.ok
    assert v.detail["checks"]["OBV 하락"] is False


def test_still_consolidating_is_not_a_breakdown():
    """횡보 중에는 아직 아니다 — 지지선을 깨야 한다."""
    c = _RALLY + _FLAT
    v = evaluate_support_breakdown(closes=c, volumes=_vols(len(c), 1.0), obv_dir=-0.2)
    assert not v.ok


def test_no_prior_rally_is_not_a_breakdown():
    """🚨 사상 ③ 은 「**이전 급등**에 대한 급락」이다. 그냥 하락은 대상이 아니다."""
    c = [100.0 + i * 0.1 for i in range(45)]
    v = evaluate_support_breakdown(closes=c, volumes=_vols(45), obv_dir=-0.2)
    assert not v.ok
    assert v.detail["checks"]["선행 급등"] is False


def test_no_volume_spike_is_not_a_breakdown():
    """붕괴에 물량이 안 실렸으면 진짜 붕괴가 아니다."""
    c = _RALLY + _FLAT + _BREAK
    v = evaluate_support_breakdown(closes=c, volumes=_vols(len(c), 1.0), obv_dir=-0.25)
    assert not v.ok
    assert v.detail["checks"]["거래량 급증"] is False


# ───────────────────────────────── 결측 / 안전

def test_missing_data_is_not_a_breakdown():
    """🚨 이 판정은 **매매 방향을 뒤집는다** — 모르는데 뒤집으면 안 된다 (fail-closed)."""
    assert not evaluate_support_breakdown(closes=None).ok
    assert not evaluate_support_breakdown(closes=[1.0, 2.0, 3.0]).ok
    c = _RALLY + _FLAT + _BREAK
    assert not evaluate_support_breakdown(closes=c).ok, "거래량/OBV 없이 통과하면 안 된다"


def test_broken_values_do_not_raise():
    v = evaluate_support_breakdown(
        closes=["없음", None, 0] + _RALLY, volumes=["x", None], obv_dir="많이",
    )
    assert not v.ok


def test_all_checks_required_not_majority():
    """🚨 Fix 250 의 교훈 — 방향을 뒤집는 판정은 다수결로 정하지 않는다."""
    c = _RALLY + _FLAT + _BREAK
    v = evaluate_support_breakdown(closes=c, volumes=_vols(len(c)), obv_dir=+0.30)
    assert v.passed == v.total - 1 and not v.ok, "4/5 인데 통과됐다"


# ───────────────────────────────── 연결

def _code() -> str:
    return chr(10).join(
        ln for ln in WORKER.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_flip_is_wired_before_the_surge_gate():
    """방향 전환이 surge 판정 직후, 진입 처리 **앞**에 있어야 한다."""
    code = _code()
    i_detect = code.index("matched, side, surge_meta = _detect_15m_surge")
    i_flip = code.index("evaluate_support_breakdown")
    i_use = code.index("if not matched or side is None:")
    assert i_detect < i_flip < i_use, "전환이 방향이 쓰이기 전에 일어나지 않는다"


def test_flip_only_applies_to_long():
    """🚨 SHORT 에 걸면 무한 반전이 된다."""
    code = _code()
    assert 'if matched and side == "LONG":' in code


def test_defaults_to_off_with_preview_log():
    """방향을 뒤집는 변경이라 얼마나 발생하는지 먼저 봐야 한다."""
    src = WORKER.read_text(encoding="utf-8")
    assert '"support_breakdown_short_enabled", 0' in src, "기본값이 OFF 가 아니다"
    assert "SHORT 였을 것" in src, "예고 로그가 없다"
    assert "support_breakdown_short_enabled=1" in src, "켜는 방법이 로그에 없다"


def test_failure_keeps_original_side():
    """판정 실패로 방향이 엉뚱하게 바뀌면 안 된다."""
    code = _code()
    i = code.index("evaluate_support_breakdown")
    window = code[i: i + 2200]
    assert "원 방향 유지" in WORKER.read_text(encoding="utf-8")
    assert "except Exception" in window


def test_thresholds_are_pinned():
    assert THRESHOLDS["prior_rally_min_pct"] == 50.0   # 사상 ③ 「이전 급등」
    assert THRESHOLDS["bb_pos_break_max"] == 0.45      # BTR 붕괴 시점 1H 0.434
    assert THRESHOLDS["vol_spike_min"] == 1.5
    assert THRESHOLDS["obv_max"] == 0.0                # 사상 ④


# ── Fix 255: 관측 가능성 ──────────────────────────────────────────

def test_evaluation_is_counted_even_when_it_does_not_match():
    """🚨 「평가 안 함」과 「평가했는데 미달」이 구별돼야 한다.

    옛 코드는 **전환에 성공했을 때만** 로그를 남겨서, Fix254 로그가 0건일 때
    그것이 「코드가 안 도는 것」인지 「조건이 안 맞는 것」인지 알 수 없었다.
    = 이 프로젝트가 반복해서 당한 「조용한 실패」 형태 (헌법 93).
    """
    code = _code()
    for name in ("sb_evaluated", "sb_matched", "sb_error"):
        assert f"{name} = 0" in code, f"{name} 카운터가 없다"
        assert f"{name} += 1" in code, f"{name} 를 세지 않는다"


def test_counters_appear_in_the_cycle_summary():
    """사이클 완료 로그에 보여야 매 30초 확인이 가능하다."""
    src = WORKER.read_text(encoding="utf-8")
    assert "Fix254 평가=%d 전환=%d 오류=%d" in src, "완료 로그에 카운터가 없다"


def test_counters_are_in_the_returned_payload():
    """상태 화면/모니터링이 읽을 수 있도록 반환값에도 넣는다."""
    code = _code()
    assert '"sb_evaluated": sb_evaluated' in code
    assert '"sb_matched": sb_matched' in code


def test_evaluated_is_counted_before_the_verdict():
    """🚨 판정 결과와 무관하게 세야 「돌긴 도는가」를 알 수 있다."""
    code = _code()
    i_eval = code.index("sb_evaluated += 1")
    i_ok = code.index("if _v254.ok:")
    assert i_eval < i_ok, "성공했을 때만 세면 옛 문제가 그대로다"


# ── Fix 256: 살아 있는 워커에 연결됐는가 ─────────────────────────────

_LIVE = (
    Path(__file__).resolve().parents[2]
    / "app" / "workers" / "auto_long_at_bottom_worker.py"
)


def _live_code() -> str:
    return chr(10).join(
        ln for ln in _LIVE.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_wired_into_the_live_long_worker():
    """🚨 Fix 254 를 unified_15m_entry 에 넣었는데 그 워커는 **꺼져 있었다**.

    실측: `unified_entry_enabled = 0`, 10분간 **0 사이클**.
    같은 10분에 auto_long_bottom 은 **17 사이클** 돌았다.
    = 살아 있는 급락 LONG 경로는 이쪽이다.

    「기능을 만들었는데 그 코드가 도는지 확인하지 않는 것」이
    이 프로젝트의 반복 사고다 (볼밴 3차 0건 / check_7_signals 도달 불가 / 이번 건).
    """
    code = _live_code()
    assert "evaluate_support_breakdown" in code, (
        "살아 있는 LONG 워커에 지지붕괴 판정이 없다"
    )


def test_runs_before_the_crash_long_path():
    """급락 LONG 진입(_check_pattern_B_after_correction)보다 **앞**이어야 한다."""
    code = _live_code()
    i_gate = code.index("evaluate_support_breakdown")
    i_entry = code.index("return _check_pattern_B_after_correction(")
    assert i_gate < i_entry, "판정이 급락 LONG 진입 뒤에 있다 = 무의미"


def test_blocks_long_when_breakdown():
    """붕괴면 detected=False 로 나가야 한다 (이 워커는 SHORT 를 못 만든다)."""
    code = _live_code()
    i = code.index("if _v256.ok:")
    window = code[i: i + 900]
    assert '"detected": False' in window
    assert '"pattern": "SUPPORT_BREAKDOWN"' in window


def test_failure_keeps_existing_path():
    """판정 실패로 급락 진입이 통째로 멈추면 안 된다 (Fix 252 의 교훈)."""
    src = _LIVE.read_text(encoding="utf-8")
    assert "기존 경로 유지" in src


# ── Fix 258: 같은 실수를 두 번 했다 (관측 카운터) ────────────────────

def test_live_worker_counts_evaluations_too():
    """🚨 Fix 255 에서 배운 것을 auto_long_bottom 에는 적용하지 않았다.

    Fix256 로그가 0 이었는데, 같은 사이클에 급락 후보 14건(B1=8 B2=4 B3=2)이
    패턴 B 로 들어갔다 = **판정은 돌고 있었다**. 로그를 「적중했을 때만」 남겨서
    「안 도는 것」과 「조건 미달」이 또 구별되지 않았다.
    """
    code = _live_code()
    assert '"sb_eval"' in code, "평가 횟수를 세지 않는다"
    assert '"sb_hit"' in code, "적중 횟수를 세지 않는다"
    assert '"sb_err"' in code, "오류 횟수를 세지 않는다"


def test_eval_counted_before_verdict_in_live_worker():
    """판정 결과와 무관하게 먼저 세야 「돌긴 도는가」를 알 수 있다."""
    code = _live_code()
    i_eval = code.index('stats["sb_eval"]')
    i_ok = code.index("if _v256.ok:")
    assert i_eval < i_ok


def test_counters_in_the_cycle_summary():
    src = _LIVE.read_text(encoding="utf-8")
    assert "Fix256 평가=%d 적중=%d 오류=%d" in src, "완료 로그에 카운터가 없다"
