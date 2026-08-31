"""🛡️ Fix 244 — 「급등 중 조정」이 **1순위**로 연결됐는지 (사장님 선택 「B」).

## 사장님 결정 (2026-08-31)

  "B로해줘"  = 두 경로 다 살리되 **급등 중 조정을 먼저** 잡는다.
  "급락한건 ... **포지션 진입을 하지 않는다고 안헀어**"
  ⇒ 급락 경로(패턴 B)를 **없애면 안 된다**.

## 연결이 깨지기 쉬운 이유

새 경로는 반드시 **아래 두 차단보다 앞**에 있어야 한다:

  · `extreme_bull` — 3일 +30%↑ 를 skip 한다. 새 조건은 3일 **+45%↑** 를 요구하므로
    뒤에 놓으면 **수학적으로 한 건도 통과할 수 없다**.
  · 패턴 A skip — 24h +5~15% 상승 종목을 통째로 버린다.

순서가 뒤바뀌면 코드는 멀쩡해 보이는데 **산출이 영원히 0** 이다.
이 프로젝트에서 실제로 겪은 사고 유형이라(볼밴 3차 0건, check_7_signals 도달 불가)
순서를 테스트로 고정한다.
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
    return "\n".join(
        ln for ln in _src().splitlines() if not ln.lstrip().startswith("#")
    )


def test_surge_pullback_runs_before_extreme_bull_skip():
    """🚨 순서가 뒤바뀌면 3일 +45% 조건이 3일 +30% skip 에 먼저 걸려 산출 0 이 된다."""
    code = _code()
    i_sp = code.index("_surge_pullback_probe(bc, symbol")
    i_eb = code.index('if trend == "extreme_bull"')
    assert i_sp < i_eb, "급등중조정 판정이 extreme_bull skip 뒤에 있다 = 영원히 미도달"


def test_surge_pullback_runs_before_pattern_a_skip():
    """패턴 A skip(+5~15% 상승 버림)보다도 앞이어야 한다."""
    code = _code()
    i_sp = code.index("_surge_pullback_probe(bc, symbol")
    i_pa = code.index("PATTERN_A_MIN_CHG <= chg24 <= PATTERN_A_MAX_CHG")
    assert i_sp < i_pa, "급등중조정 판정이 패턴 A skip 뒤에 있다"


def test_crash_entry_path_is_still_alive():
    """🚨 사장님: 급락에 「진입을 하지 않는다고 안했어」 — 패턴 B 를 없애면 안 된다."""
    code = _code()
    assert "PATTERN_B_MAX_CHG" in code, "급락 경로(패턴 B)가 사라졌다"
    assert "if chg24 <= PATTERN_B_MAX_CHG:" in code, (
        "급락 판정 분기가 없다 — 사장님이 진입을 막지 말라고 하셨다"
    )
    assert "_check_pattern_B_after_correction(" in code, (
        "급락 후 조정 진입 함수 호출이 사라졌다"
    )


def test_round_trip_is_hard_blocked_at_worker_level():
    """되돌림 1.00 초과(원점 아래)는 워커에서도 진입을 막아야 한다 (실측 6건 -1,845)."""
    code = _code()
    assert "_sp.blocked" in code
    m = re.search(r"if _sp is not None and _sp\.blocked:(.{0,400})", code, re.S)
    assert m and '"detected": False' in m.group(1), "차단인데 detected=True 로 나간다"


def test_probe_failure_falls_back_to_existing_path():
    """판정이 실패하면 None → 기존 경로가 그대로 돈다 (fail-safe)."""
    code = _code()
    assert "기존 경로 유지" in _src(), "실패 시 fail-safe 라는 근거가 안 보인다"
    assert "if _sp is not None and _sp.ok:" in code, (
        "None 을 ok 처럼 다루면 판정 실패가 진입으로 이어진다"
    )


def test_switch_defaults_to_on_per_sajangnim_choice():
    """사장님이 「B로해줘」라고 선택했으므로 기본 ON. 끄는 수단은 남긴다."""
    code = _code()
    assert '"surge_pullback_long_enabled", True' in code, (
        "기본값이 ON 이 아니거나 설정 키가 없다"
    )
    assert "enabled=surge_pullback_on" in code, "스위치가 판정에 연결되지 않았다"


def test_entry_is_logged_with_the_numbers():
    """무엇을 보고 들어갔는지 로그에 남아야 다음 분석이 가능하다."""
    src = _src()
    assert "[Fix244] 🎯" in src
    for token in ("3일", "CCI15m", "RSI15m", "되돌림"):
        assert token in src, f"진입 로그에 {token} 이 없다"


def test_snapshot_is_recorded_for_learning():
    """entry_snapshot 에 판정 근거가 들어가야 학습 표본이 된다."""
    code = _code()
    assert '"entry_snapshot": _sp.detail' in code


# ── Fix 252: 경로 불일치가 급락 진입을 죽이면 안 된다 ─────────────────

def test_only_hard_block_short_circuits_the_worker():
    """🚨 실측 회귀 — LONG 진입이 100% 막혔다.

        [auto_long_bottom] 완료: scanned=35 entered=0 | 사유: nd:ROUND_TRIP_BLOCKED0=35

    워커의 조기 return 은 `_sp.blocked` 에만 걸려야 한다.
    `not _sp.ok`(= 이 경로가 아님)로 return 하면 급락 경로까지 죽는다.
    """
    code = _code()
    assert "if _sp is not None and _sp.blocked:" in code, (
        "하드 차단 분기가 blocked 를 보지 않는다"
    )
    # `not _sp.ok` 로 조기 종료하는 분기가 있으면 안 된다
    assert "if _sp is not None and not _sp.ok" not in code, (
        "경로 불일치로 조기 종료한다 = 급락 진입이 사라진다"
    )
    # ok 분기는 진입용(detected=True)이어야 한다
    i_ok = code.index("if _sp is not None and _sp.ok:")
    window = code[i_ok: i_ok + 800]
    assert '"detected": True' in window
