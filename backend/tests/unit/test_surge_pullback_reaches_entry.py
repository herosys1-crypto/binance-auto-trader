"""🛡️ Fix 249 — 「급등 중 조정」이 **진입까지 실제로 도달**하는가.

## 배포 첫날 실측 로그

    [auto_long_bottom] 완료: scanned=36 entered=0
      사유: nd:B1=16 nd:ROUND_TRIP_BLOCKED0=9 nd:B2=8 nd:B3=2

    [auto_long_bottom+Fix111b] LIGHTUSDT SKIP: 지표 꺾임 0/2 (아직 진행 중 = 정점 아님!)
      rsi 67.99  macd +0.00052  cci 248.4

되돌림 하드 차단(ROUND_TRIP_BLOCKED)은 9건 걸러내며 작동했다.
그런데 **SURGE_PULLBACK 진입은 0건**이었다.

## 원인 — 진입 직전에 게이트가 하나 더 있었다

`_create_long_strategy` 가 `confirm_peak(bc, symbol, "LONG")` 를 무조건 부른다(Fix 111b).
그 함수는 **「지표가 저점에서 반등」**을 요구한다:

    _turns_for_long:  rsi <= 35 이고 상승  /  cci <= -80 이고 상승  /  macd hist < 0 이고 상승

그런데 급등 중 조정 종목은 **RSI 68 / CCI 248** 처럼 강세다
(실측 승자 중앙값 CCI +110.6 / RSI 67.4).
=> **수학적으로 0/2** 가 나온다. Fix 244 가 1순위로 골라도 여기서 전부 죽는다.

🚨 볼밴 3차 0건과 **같은 함정**이다. 그때도 「하락이 멈춰야 산다」는 게이트가
물타기와 충돌해 3차 체결이 0건이었다(Fix 203/218/223 이 예외를 줬다).
순서만 테스트로 고정하고 **뒤에 또 있는 게이트를 놓쳤다.**

## 고침

SURGE_PULLBACK 경로는 Fix 111b 를 건너뛴다.
보호가 없어지는 것이 아니라 **다른 보호로 바뀐다** —
그 경로는 되돌림 <= 0.35 + 강세 4개 조건 + 원점 아래 하드 차단을 이미 통과했다.
"""
from __future__ import annotations

import re
from pathlib import Path

WORKER = (
    Path(__file__).resolve().parents[2]
    / "app" / "workers" / "auto_long_at_bottom_worker.py"
)


def _src() -> str:
    return WORKER.read_text(encoding="utf-8")


def _code() -> str:
    return chr(10).join(
        ln for ln in _src().splitlines() if not ln.lstrip().startswith("#")
    )


#: 🚨 테스트 stale fix (Fix 346/352, commits c7417a8 / 60c471e): 저점 게이트
#: 예외가 SURGE_PULLBACK 하나에서 SURGE_START(정점 SHORT 워커가 넘긴 알람,
#: Fix 346) · MULTIDAY_PULLBACK(다일 조정 반등, Fix 352)까지 3개로 늘었다.
SURGE_SKIP = {"SURGE_PULLBACK", "SURGE_START", "MULTIDAY_PULLBACK"}


def _skip_set(code: str) -> set[str]:
    m = re.search(r"_skip_pk = \(pattern in \(([^)]*)\)\)", code)
    assert m, "저점 게이트 예외 조건이 없다"
    return set(re.findall(r'"([A-Z_]+)"', m.group(1)))


def test_surge_pullback_skips_the_bottom_gate():
    """🚨 이 예외가 없으면 급등중 조정 진입은 **수학적으로 0건**이다.

    🚨 테스트 stale fix (Fix 346/352): 옛 조건 `pattern == "SURGE_PULLBACK"`
    (단일 값 비교)이 `pattern in (...)` (집합 소속 판정)으로 바뀌었다 —
    SURGE_START/MULTIDAY_PULLBACK 도 같은 이유로 강세 종목이라 저점 반등
    조건을 못 넘는다.
    """
    code = _code()
    assert "SURGE_PULLBACK" in _skip_set(code)
    assert code.count("_skip_pk = (") == 1
    i_skip = code.index("_skip_pk = (")
    i_gate = code.index("if bc is not None and not _skip_pk:")
    i_cp = code.index('confirm_peak(bc, symbol, "LONG")')
    assert i_skip < i_gate < i_cp


def test_pattern_is_threaded_from_the_decision():
    """판정 결과의 pattern 이 진입 함수까지 전달돼야 예외가 걸린다."""
    code = _code()
    assert "def _create_long_strategy(" in code
    assert "pattern: str | None = None" in code, "시그니처에 pattern 이 없다"
    assert 'pattern=result.get("pattern")' in code, (
        "스캔 경로가 pattern 을 넘기지 않는다"
    )


def test_alert_path_does_not_reference_undefined_result():
    """🚨 알람 루프에는 `result` 가 없다 — 참조하면 NameError 로 진입이 죽는다.

    (이 실수를 실제로 한 번 넣었다가 잡았다.)

    🚨 테스트 stale fix (Fix 346, commit c7417a8, 2026-09-04): 알람 경로가
    무조건 `pattern=None` 이던 것이, 정점 SHORT 워커가 넘긴 SURGE_START 류
    알람은 패턴을 그대로 전달하도록 바뀌었다(`_alert_pattern` 변수 도입,
    Fix 352 가 MOMENTUM_ALERT_PATTERNS 로 판정 범위를 확정). `result` 를
    직접 참조하지 않는다는 불변식은 그대로 지켜야 한다.
    """
    src = _src()
    assert src.count("pattern=_alert_pattern") == 1, "알람 경로가 _alert_pattern 을 전달하지 않는다"
    assert src.count('pattern=result.get("pattern")') == 1, (
        "스캔 경로의 pattern 전달이 없거나 중복이다"
    )
    a0 = src.index("[Fix75/alert-long]")
    a_def = src.index("_alert_pattern = (")
    a_call = src.index("pattern=_alert_pattern")
    a1 = src.rindex("[Fix75/alert-long]")
    s_tag = src.index("# 9. 실 진입!")
    s_call = src.index('pattern=result.get("pattern")')
    assert a0 < a_def < a_call < a1 < s_tag < s_call, (
        "알람/스캔 경로가 뒤바뀌었다 — 알람에서 result 를 참조하면 NameError 다"
    )
    # 알람 루프 전체(a0~a1)에는 (주석을 뺀) 어디에도 bare `result` 참조가 없어야 한다
    seg = chr(10).join(
        ln for ln in src[a0:a1].splitlines() if not ln.lstrip().startswith("#")
    )
    assert not re.search(r"\bresult\b", seg), "알람 루프가 스캔 전용 변수 result 를 참조한다"
    # _alert_pattern 정의 자체도 MOMENTUM_ALERT_PATTERNS 기준으로 안전하게 None 폴백해야 한다
    line = src[a_def: src.index(chr(10), a_def)]
    assert "alert.get(" in line and "MOMENTUM_ALERT_PATTERNS" in line and "else None" in line


def test_exemption_is_logged():
    """예외가 걸렸는지 로그로 보여야 다음 분석이 가능하다."""
    src = _src()
    assert "[Fix249]" in src
    assert "저점 게이트 제외" in src


def test_other_patterns_still_pass_the_bottom_gate():
    """🚨 급락 경로(패턴 B)는 저점 게이트를 그대로 받아야 한다.

    예외가 전체로 번지면 「하락 초입 매수」 방지가 사라진다.

    🚨 테스트 stale fix (Fix 346/352): 예외 대상이 SURGE_PULLBACK 하나에서
    SURGE_START/MULTIDAY_PULLBACK 까지 늘었지만(`SURGE_SKIP`), 여전히
    **그 3개로 한정**돼야 한다 — 패턴 A/B(저점 반등) 나 빈 값은 절대 포함되면
    안 된다. `MOMENTUM_ALERT_PATTERNS` 와도 동일해야 한다(두 상수가 따로
    놀면 한쪽만 고치는 사고가 난다).
    """
    from app.workers.auto_long_at_bottom_worker import MOMENTUM_ALERT_PATTERNS
    s = _skip_set(_code())
    assert s == SURGE_SKIP, f"예외 대상이 바뀌었다: {s}"
    assert s == set(MOMENTUM_ALERT_PATTERNS)
    for dip in ("A", "B", "", "NONE"):
        assert dip not in s


def test_round_trip_block_still_active():
    """되돌림 하드 차단은 유지 — 실측에서 9건을 걸러내고 있었다."""
    code = _code()
    assert "ROUND_TRIP_BLOCKED" in code
