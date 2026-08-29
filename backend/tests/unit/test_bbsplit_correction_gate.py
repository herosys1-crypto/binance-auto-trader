"""🚨 Fix 223 — 볼밴 2·3차의 「조정 신호」에서 **반복 저점 요구를 뺀다**.

사장님 verbatim (2026-08-30):
  "2단계부터는 차트와 보조지표가 **조정으로 바뀌면** 2단계 진입"

`confirm_peak` 은 두 관문이다:
  [A] 반복 상승/하락 2회 이상  ← 「바닥/정점 확인」. 사장님이 말씀하신 적 **없다**
  [B] 지표 꺾임 RSI/MACD/CCI 2/3 ← 이게 「조정으로 바뀌었다」

볼밴은 **급락 초입에 나눠 사는** 전략이라 [A] 가 구조적으로 안 나온다.

실측 2026-08-29 21:54~21:56 (Fix 218 배포 직후, 30초마다 반복):
    [Fix218/split] ⏳ #1751 OPGUSDT LONG 단계2 대기 — 조정 신호 미충족:
      정점확인 미충족: 반복하락 0회 < 2 (단일 추세 = 초입!)

전날에도 같은 이유로 볼밴 3차 체결이 **0건**이었다 (사유 전부 "Fix114 정점 미확인").
→ 볼밴 호출만 min_swings=0. **다른 호출자는 기본값(2) 그대로.**
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app.services.peak_confirmation import MIN_PEAK_COUNT_15M, confirm_peak
from app.services.stage_entry_signal import check_stage_entry_signal

WORKERS = Path(__file__).resolve().parents[2] / "app" / "workers"
STAGE_TRIGGER = WORKERS / "stage_trigger_worker.py"


def test_min_swings_is_optional_and_defaults_to_old_behaviour():
    """다른 호출자(정점 SHORT / 바닥 LONG)의 동작은 **바뀌면 안 된다**."""
    sig = inspect.signature(confirm_peak)
    assert "min_swings" in sig.parameters
    p = sig.parameters["min_swings"]
    assert p.default is None, "기본값이 None 이 아니면 기존 호출자 동작이 바뀐다"
    assert p.kind is inspect.Parameter.KEYWORD_ONLY, "위치 인자면 오호출 위험"
    assert MIN_PEAK_COUNT_15M >= 2, "기본 반복 요구가 사라졌다"


def test_signal_passes_it_through():
    """check_stage_entry_signal 이 값을 전달하지 않으면 볼밴 완화가 무효다."""
    sig = inspect.signature(check_stage_entry_signal)
    assert "min_swings" in sig.parameters
    assert sig.parameters["min_swings"].default is None
    src = inspect.getsource(check_stage_entry_signal)
    assert "min_swings=min_swings" in src, "받아만 놓고 confirm_peak 에 안 넘긴다"


def test_bbsplit_call_site_uses_zero():
    """🚨 볼밴 경로가 실제로 0 을 넘기는가 — 이게 없으면 지금 상태 그대로다."""
    src = "\n".join(
        ln for ln in STAGE_TRIGGER.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")      # 주석이 통과시키면 안 된다 (헌법 122)
    )
    assert "min_swings=0" in src, (
        "볼밴 2·3차가 여전히 반복 저점 2회를 요구한다 — "
        "실측상 '반복하락 0회 < 2' 로 100% 차단된다"
    )


def test_only_bbsplit_is_relaxed():
    """완화가 **볼밴에만** 적용돼야 한다 — 전역으로 새면 다른 전략 안전망이 뚫린다."""
    tree = ast.parse(STAGE_TRIGGER.read_text(encoding="utf-8"))
    zeros = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if (
                    kw.arg == "min_swings"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value == 0
                ):
                    zeros += 1
    assert zeros == 1, f"min_swings=0 호출이 {zeros}건 — 볼밴 한 곳이어야 한다"


def test_indicator_turn_gate_is_still_there():
    """음성 대조군 — [B] 지표 꺾임까지 없애면 게이트가 통째로 무의미해진다."""
    src = inspect.getsource(confirm_peak)
    assert "MIN_TURNS" in src, "지표 꺾임 관문이 사라졌다 = 아무 조정도 확인 안 한다"
    assert "지표 꺾임" in src
