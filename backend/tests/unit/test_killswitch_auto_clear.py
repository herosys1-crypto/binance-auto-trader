"""🚨 Fix 221 — orphan 이 사라지면 Kill-Switch 를 **자동 해제**한다.

## 왜 필요했나 (실측 2026-08-29)

    reason_code    = ZOMBIE:ORPHAN_EXCHANGE_POSITION
    reason_message = 거래소 INJUSDT SHORT 포지션 (amt=-3.9) 에 매칭 strategy 없음
    triggered_at   = 17:02:59      cleared_at = None

명목 20~40 USDT 짜리 먼지 포지션 하나로 17:02 에 계정 전체 신규 거래가 차단됐다.
그 포지션은 곧 사라졌는데 Kill-Switch 는 **44분간 그대로** 걸려 있었고, 그동안
UNIUSDT SHORT 는 정점확인(반복상승 4회, 꺾임 3/2)까지 통과해놓고 30초마다 튕겼다.
사장님이 "자동 전략이 하나도 없어" 라고 하신 원인이 이것이다.

**같은 사고가 세 번째다** — 07-21 ACEUSDT / 08-26 CLUSDT / 08-29 INJUSDT.
발동은 자동인데 **해제만 수동**이라 구조적으로 반복될 수밖에 없었다.
"""
from __future__ import annotations

import ast
from pathlib import Path

GUARD = Path(__file__).resolve().parents[2] / "app" / "services" / "zombie_guardian.py"
ORPHAN_CODE = "ZOMBIE:ORPHAN_EXCHANGE_POSITION"


def _code_without_comments() -> str:
    """주석을 걷어낸 소스 — 내 주석이 테스트를 통과시키면 안 된다 (헌법 122)."""
    return "\n".join(
        ln for ln in GUARD.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_module_still_imports():
    """가드 자체가 못 올라오면 orphan 감지가 통째로 죽는다 = 최악."""
    import app.services.zombie_guardian as z

    assert callable(z.detect_orphan_exchange_positions)


def test_auto_clear_exists():
    """orphan 0 건일 때 clear() 를 부르는 코드가 있어야 한다."""
    src = _code_without_comments()
    assert "_orphan_here" in src, "계정별 orphan 카운터가 없다"
    assert "AccountKillSwitchService(db).clear(" in src, "자동 해제 호출이 없다"
    assert "KILL_SWITCH_AUTO_CLEARED" in src, "해제 사실을 기록하지 않는다 (헌법 161)"


def test_auto_clear_is_narrowly_scoped():
    """🚨 아무 Kill-Switch 나 풀면 안 된다.

    사장님이 수동으로 켰거나 손실한도 등 **다른 사유**로 켜진 것은 건드리면 안 된다.
    반드시 orphan 사유일 때만 해제해야 한다.
    """
    src = _code_without_comments()
    assert ORPHAN_CODE in src, "해제 조건이 orphan 사유로 좁혀져 있지 않다"
    assert "is_enabled" in src, "켜져 있는지 확인하지 않는다"


def test_counter_is_incremented_where_orphan_is_found():
    """카운터가 **증가하지 않으면** orphan 이 있어도 해제해버린다 = 정반대 사고."""
    src = _code_without_comments()
    assert "_orphan_here += 1" in src, (
        "orphan 발견 지점에서 카운터가 증가하지 않는다 — orphan 이 있는데도 "
        "Kill-Switch 를 풀어버린다"
    )


def test_model_is_imported():
    """AccountKillSwitch 모델 import 누락 시 NameError 로 감지 전체가 죽는다."""
    tree = ast.parse(GUARD.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "AccountKillSwitch" in imported, sorted(imported)


def test_detector_would_notice_if_guard_disappeared():
    """음성 대조군 (헌법 170) — 검사가 실제로 무언가를 보고 있는가."""
    src = _code_without_comments()
    assert src.count("AccountKillSwitchService(db).trigger(") >= 1, (
        "trigger 호출조차 못 찾는다 = 이 파일을 잘못 보고 있다"
    )
