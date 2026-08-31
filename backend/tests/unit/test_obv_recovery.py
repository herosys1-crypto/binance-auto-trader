"""🛡️ Fix 259 — 「소소한 반등」에는 LONG 을 넣지 않는다.

## 사장님 verbatim (2026-09-01, AIOUSDT 차트)

    "급등후 급락했을때 obv 같이 급락하면 다시 지지반등 이상을 하려면
     **obv가 강력하게 상승해야해**. 이건 **작은 반등후 하락**하는거야.
     **세력이 모두 떠난후 다시 상승하려면 세력이 다시 들어와야** 하는데
     이차트는 그냥 **소소한 반등**이야"

「지금 OBV 가 오르는가」가 아니라 **「떨어진 만큼 얼마나 돌아왔는가」**다.

## 실측 (진입 시점 캔들 복원)

    전략              결과        1H 회복률    4H 회복률   4H obv_dir
    #1890 SNXXUSDT   **+22.71**   **0.637**     0.187       +0.3811
    #1909 AIOUSDT     실패          0.060       0.266       +0.3088
    #1884 XPLUSDT     실패          0.106       0.069       -0.1274

🚨 **1시간봉이 판별자**다 — 4H 회복률은 오히려 뒤집혀 있다(승 0.187 / 패 0.266).
🚨 그리고 Fix 257(4H obv_dir <= -0.10)은 **AIO(+0.3088)를 못 잡는다**.
   「지금 오르는가」와 「떨어진 만큼 돌아왔는가」는 다른 질문이다.

⚠️ 표본 3건. 승자가 더 쌓이면 임계를 다시 잡을 것.
"""
from __future__ import annotations

from pathlib import Path

from app.services.obv_recovery import (
    MIN_DROP_RATIO,
    RECOVERY_MIN,
    obv_recovery_ratio,
)

WORKER = (
    Path(__file__).resolve().parents[2]
    / "app" / "workers" / "auto_long_at_bottom_worker.py"
)


def _obv_drop_then_recover(frac: float) -> list[float]:
    """OBV 가 0 -> 2500 -> 900 으로 떨어진 뒤 낙폭의 frac 만큼 회복."""
    up = [i * 100.0 for i in range(26)]           # 0 -> 2500
    down = [2500.0 - i * 80.0 for i in range(1, 21)]   # -> 900
    trough = down[-1]
    return up + down + [trough + (2500.0 - trough) * frac]


# ───────────────────────────────── 판정

def test_strong_recovery_passes():
    """승자 프로파일(0.637) — 세력이 다시 들어온 것."""
    r, d = obv_recovery_ratio(_obv_drop_then_recover(0.637))
    assert r is not None and r >= RECOVERY_MIN, (r, d)


def test_weak_rebound_is_blocked():
    """🚨 패자 프로파일(0.060 / 0.106) — 사장님이 말한 「소소한 반등」."""
    for frac in (0.060, 0.106):
        r, _d = obv_recovery_ratio(_obv_drop_then_recover(frac))
        assert r is not None and r < RECOVERY_MIN, f"회복률 {frac} 이 통과했다"


def test_threshold_sits_between_winner_and_losers():
    """임계가 실측 사이에 있어야 승자를 안 자르고 패자를 거른다."""
    assert 0.106 < RECOVERY_MIN < 0.637


def test_no_drop_means_not_applicable():
    """🚨 사장님 조건은 「obv **같이 급락하면**」이다.

    떨어진 적이 없으면 이 규칙의 대상이 아니다 -> None(막지 않음).
    """
    r, d = obv_recovery_ratio([i * 100.0 for i in range(40)])
    assert r is None
    assert "하락 구간 없음" in d["reason"] or "고점이 현재" in d["reason"]


def test_tiny_drop_is_not_a_departure():
    """낙폭이 미미하면 「세력이 떠난」 상황이 아니다."""
    obv = [i * 100.0 for i in range(40)] + [3890.0, 3885.0, 3888.0]  # 아주 살짝 하락
    r, d = obv_recovery_ratio(obv)
    assert r is None and "낙폭 미미" in d["reason"]
    assert MIN_DROP_RATIO == 0.20


def test_insufficient_bars_is_none():
    assert obv_recovery_ratio([1.0, 2.0, 3.0])[0] is None
    assert obv_recovery_ratio(None)[0] is None


def test_broken_values_do_not_raise():
    r, _d = obv_recovery_ratio(["없음", None, float("nan")] + [1.0] * 30)
    assert r is None or isinstance(r, float)


# ───────────────────────────────── 연결

def _code() -> str:
    return chr(10).join(
        ln for ln in WORKER.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_wired_into_the_crash_long_path():
    """급락 LONG 경로에 있어야 한다 — AIO/XPL 이 그 경로로 들어왔다."""
    code = _code()
    assert "obv_recovery_ratio" in code
    i_gate = code.index("obv_recovery_ratio")
    i_entry = code.index("return _check_pattern_B_after_correction(")
    assert i_gate < i_entry, "판정이 급락 LONG 진입 뒤에 있다 = 무의미"


def test_uses_1h_data_not_4h():
    """🚨 4H 회복률은 승/패가 **뒤집혀** 있다 (승 0.187 / 패 0.266).

    1H 데이터(_a256 = 1h 분석)를 써야 한다.
    """
    src = WORKER.read_text(encoding="utf-8")
    assert '_rr259(_a256.get("obv"), 60)' in src, "1H OBV 를 쓰지 않는다"
    assert '"1h"' in src


def test_blocks_with_a_distinct_pattern_name():
    """차단 사유가 구별돼야 사이클 로그에서 원인을 가릴 수 있다."""
    code = _code()
    assert '"pattern": "WEAK_OBV_REBOUND"' in code


def test_failure_keeps_existing_path():
    """판정 실패로 급락 진입이 통째로 멈추면 안 된다 (Fix 252 의 교훈)."""
    src = WORKER.read_text(encoding="utf-8")
    i = src.index("Fix259")
    assert "기존 경로 유지" in src[i: i + 4000]


def test_counters_exist():
    """🚨 Fix 255/258 의 교훈 — 「안 도는 것」과 「조건 미달」이 구별돼야 한다."""
    code = _code()
    assert '"ob_eval"' in code and '"ob_hit"' in code
    src = WORKER.read_text(encoding="utf-8")
    assert "Fix259 평가=%d 차단=%d" in src
