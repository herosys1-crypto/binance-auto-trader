"""🚨 Fix 218 — 볼밴 2·3차를 「조정 신호」로 바꾸고, 손절 -15%, 재시작 1회.

사장님 verbatim (2026-08-30):
  "볼밴 하단 -3%에 100 진입하고 2단계부터는 차트와 보조지표가 조정으로 바뀌면
   2단계 진입하고 그리고 다시 하락하면 다시 차트와 보조지표가 조정을 보이면
   3단계 진입해서 -15%되면 청산 하고 다시 모니터링대기해서 다시 조정받으면
   1단계 부터 다시 한번더 해줘"

⚠️ 이 변경은 **Fix 203 을 뒤집는다.** 같은 계열 게이트(Fix114 정점확인)가
   2026-08-29 실측에서 볼밴 3차를 100% 차단했었다(체결 0건). 사장님 지시로
   되돌리는 것이며, 차단 사유를 남기게 해서 하루 안에 판단할 수 있게 했다.
"""
from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

from app.workers.pump_split_entry_worker import (
    FORCE_SL_ROI,
    SPLIT_MAX_CYCLES_PER_DAY,
    SPLIT_STEP_PCT,
    check_no_dead_stage,
    mid_steps,
)

WORKERS = Path(__file__).resolve().parents[2] / "app" / "workers"
STAGE_TRIGGER = WORKERS / "stage_trigger_worker.py"
CAPS = [Decimal("100"), Decimal("200"), Decimal("500")]
LEV = 2


def _code_without_comments(path: Path) -> str:
    """주석을 걷어낸 소스 — 내 주석이 테스트를 통과시키면 안 된다 (헌법 122)."""
    return "\n".join(
        ln for ln in path.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_stop_loss_default_is_15():
    """사장님 "-15%되면 청산". 이건 **fallback** 이고 운영은 DB 설정이 이긴다."""
    assert FORCE_SL_ROI == Decimal("15")


def test_restart_limit_is_one_more_time():
    """"다시 한번더" = 최초 1 + 재시작 1 = 24h 내 2건."""
    assert SPLIT_MAX_CYCLES_PER_DAY == 2


def test_restart_limit_is_actually_applied():
    """상수만 있고 안 쓰이면 「올렸다고 보고하고 아무 일 없음」이 된다 (헌법 169)."""
    src = _code_without_comments(WORKERS / "pump_split_entry_worker.py")
    assert src.count("SPLIT_MAX_CYCLES_PER_DAY") >= 2, (
        "재시작 상한 상수가 정의만 되고 실제로 쓰이지 않는다"
    )


def test_no_dead_stage_at_sl_15_both_tables():
    """손절을 -10 → -15 로 **넓히면** 트리거가 더 확실히 먼저 온다 (죽은 단계 없음)."""
    for label, steps in (("하단", SPLIT_STEP_PCT), ("중단", mid_steps(SPLIT_STEP_PCT))):
        ok, why = check_no_dead_stage(CAPS, steps, Decimal("15"), LEV)
        assert ok, f"{label} 단계표가 SL -15% 에서 죽는다: {why}"


def test_split_stages_now_go_through_the_correction_signal():
    """2·3차가 `check_stage_entry_signal`(조정 신호)을 실제로 통과해야 한다.

    Fix 203 은 볼밴을 지표 게이트에서 **빼는** 코드였다. 사장님 지시로 되돌렸으므로,
    이제 split 경로가 그 함수를 부르지 않으면 지시가 구현되지 않은 것이다.
    """
    src = _code_without_comments(STAGE_TRIGGER)
    assert "check_stage_entry_signal" in src, (
        "stage_trigger_worker 가 조정 신호 판정을 부르지 않는다"
    )
    assert "_is_split" in src, "split 분기가 사라졌다"


def test_block_reason_is_recorded_when_signal_is_missing():
    """차단하면 **사유를 남겨야** 한다 (헌법 161).

    이 게이트는 과거에 볼밴 3차를 100% 막았다. 사유가 안 남으면 그때처럼
    「왜 안 들어가는지 모르는」 상태가 그대로 재현된다.
    """
    tree = ast.parse(STAGE_TRIGGER.read_text(encoding="utf-8"))
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_record_block_reason"
    ]
    assert len(calls) >= 5, (
        f"차단 사유 기록 호출이 너무 적다({len(calls)}) — 조정 신호 경로가 조용히 막힌다"
    )
