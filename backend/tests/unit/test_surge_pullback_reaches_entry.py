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


def test_surge_pullback_skips_the_bottom_gate():
    """🚨 이 예외가 없으면 급등중 조정 진입은 **수학적으로 0건**이다."""
    code = _code()
    assert '_skip_pk = (pattern == "SURGE_PULLBACK")' in code, (
        "SURGE_PULLBACK 예외가 없다 — 강세 종목은 저점 반등 조건을 못 넘는다"
    )
    assert "if bc is not None and not _skip_pk:" in code, (
        "예외가 confirm_peak 호출을 실제로 건너뛰지 않는다"
    )


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
    """
    src = _src()
    # 호출은 정확히 두 곳 — 알람 경로(pattern=None) 와 스캔 경로(result 사용)
    assert src.count("pattern=None") == 1, "알람 경로가 pattern 을 명시하지 않는다"
    assert src.count('pattern=result.get("pattern")') == 1, (
        "스캔 경로의 pattern 전달이 없거나 중복이다"
    )
    # 알람 루프가 먼저 나오고, result 를 쓰는 스캔 루프가 뒤에 있어야 한다
    i_alert_call = src.index("pattern=None")
    i_scan_call = src.index('pattern=result.get("pattern")')
    i_alert_tag = src.index("[Fix75/alert-long]")
    i_scan_tag = src.index("# 9. 실 진입!")
    assert i_alert_tag < i_alert_call < i_scan_tag < i_scan_call, (
        "알람/스캔 경로가 뒤바뀌었다 — 알람에서 result 를 참조하면 NameError 다"
    )


def test_exemption_is_logged():
    """예외가 걸렸는지 로그로 보여야 다음 분석이 가능하다."""
    src = _src()
    assert "[Fix249]" in src
    assert "저점 게이트 제외" in src


def test_other_patterns_still_pass_the_bottom_gate():
    """🚨 급락 경로(패턴 B)는 저점 게이트를 그대로 받아야 한다.

    예외가 전체로 번지면 「하락 초입 매수」 방지가 사라진다.
    """
    code = _code()
    m = re.search(r"_skip_pk = \(pattern == \"SURGE_PULLBACK\"\)", code)
    assert m, "예외 조건이 없다"
    # 조건이 SURGE_PULLBACK 하나로 한정돼야 한다
    assert "pattern in (" not in code.split("_skip_pk")[1][:200], (
        "예외 대상이 여러 패턴으로 번졌다"
    )


def test_round_trip_block_still_active():
    """되돌림 하드 차단은 유지 — 실측에서 9건을 걸러내고 있었다."""
    code = _code()
    assert "ROUND_TRIP_BLOCKED" in code
