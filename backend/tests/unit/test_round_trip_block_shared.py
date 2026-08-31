"""🛡️ Fix 251 — LONG 「원점 회귀」 차단을 **모든 자동 진입**에 적용.

## BTRUSDT #1488 분석에서 나왔다 (단일 최대 손실 -6,552.45)

    08/26~27   0.0138 -> 0.22400   (+1,523%, 16배)
    08/28~31   0.14~0.17 횡보       4~5일
    08/31 15시 0.14 붕괴 -> 0.0823  (-44%)

## 🚨 붕괴를 LONG 으로 사고 있었다

`unified_15m_entry._detect_15m_surge` 는 방향을 **부호만으로** 정한다:

    side = "SHORT" if c1h > 0 else "LONG"

=> -44% 붕괴가 「급락」으로 분류되어 **LONG 진입**이 된다.

사장님 사상 ③ "급락한것은 이전급등에 대한 급락이라 **확실한 숏**" 과
사상 ② "급등후 큰조정에 **롱**" 을 가르는 것은 부호가 아니라 **되돌림 비율**이다:

    되돌림 = (고점 - 현재) / (고점 - 상승 시작)
    0.30~0.60  추세 중 조정   -> LONG 자리   (실측 4건 승률 75%, +684.76)
    0.70 이상  원점 회귀      -> LONG 금지
    1.00 초과  원점 아래      -> 실측 6건 -1,845.38

그 게이트가 `auto_long_at_bottom` 에만 있고 `unified_15m` 에는 없었다.
-> 모든 자동 진입이 지나는 `_create_auto_bb_strategy` 로 올린다 (헌법 6).
"""
from __future__ import annotations

from pathlib import Path

from app.services.retracement import RETRACE_BLOCK_MIN, retracement_ratio

FUNNEL = (
    Path(__file__).resolve().parents[2]
    / "app" / "workers" / "auto_bb_breakdown_worker.py"
)


def _code() -> str:
    return chr(10).join(
        ln for ln in FUNNEL.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def _btr_shape(final: float) -> list[float]:
    """BTR 실제 모양 — 0.0138 -> 0.224 급등 후 하락."""
    up = [0.0138 + (0.224 - 0.0138) * i / 40 for i in range(41)]
    return up + [0.17, 0.15, 0.14, final]


# ───────────────────────────────── 판정

def test_btr_at_collapse_is_deep_but_not_round_trip():
    """실측 — 붕괴 직후 BTR 은 되돌림 0.63 = 「깊은 조정」 구간이다.

    아직 원점 회귀는 아니므로 이 게이트만으로는 안 막힌다
    (합의 게이트 Fix 247 등 다른 관문이 별도로 본다).
    이 사실을 명시해 두어야 「왜 안 막았나」를 나중에 오해하지 않는다.
    """
    r, _d = retracement_ratio(_btr_shape(0.0908), 60)
    assert r is not None
    assert 0.60 < r < 0.70, r
    assert r < RETRACE_BLOCK_MIN


def test_round_trip_is_blocked():
    """원점까지 되돌아온 종목은 LONG 금지 (사장님 사상 ⑤)."""
    r, _d = retracement_ratio(_btr_shape(0.014), 60)
    assert r is not None and r >= RETRACE_BLOCK_MIN


def test_shallow_pullback_passes():
    """사장님이 원하는 자리 — 얕은 조정은 통과해야 한다."""
    r, _d = retracement_ratio(_btr_shape(0.20), 60)
    assert r is not None and r < RETRACE_BLOCK_MIN


# ───────────────────────────────── 연결

def test_block_is_in_the_shared_entry_funnel():
    """🚨 auto_long_at_bottom 에만 있으면 unified_15m 진입은 무방비다."""
    code = _code()
    assert "def _create_auto_bb_strategy" in code
    i_fn = code.index("def _create_auto_bb_strategy")
    assert "Fix251" in code or "retracement_ratio" in code
    i_gate = code.index("_rr251")
    assert i_gate > i_fn, "되돌림 차단이 공용 진입 함수 밖에 있다"


def test_applies_to_long_only():
    """🚨 SHORT 에 적용하면 사장님 사상 ③(급락은 확실한 숏)을 막아버린다."""
    code = _code()
    assert 'if (side or "").upper() == "LONG":' in code, (
        "되돌림 차단이 LONG 전용이 아니다"
    )


def test_blocked_entry_returns_none():
    code = _code()
    i = code.index("_r251 >= _RB251")
    window = code[i: i + 500]
    assert "return None" in window, "차단인데 전략이 만들어진다"


def test_failure_is_fail_open():
    """판정 실패로 자동매매가 멈추면 안 된다."""
    code = _code()
    i = code.index("_rr251")
    window = code[i - 200: i + 1400]
    assert "통과" in window and "except" in window


def test_threshold_comes_from_the_shared_constant():
    """임계가 파일마다 갈리면 또 단일 진실이 깨진다 (헌법 6)."""
    code = _code()
    assert "RETRACE_BLOCK_MIN" in code, "하드코딩 대신 공용 상수를 써야 한다"
    assert RETRACE_BLOCK_MIN == 0.70   # 사장님 사상 ⑤ 「70~80% 이상 금지」
