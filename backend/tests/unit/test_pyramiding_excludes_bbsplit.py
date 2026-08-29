"""🚨 Fix 213 — 피라미딩이 볼밴 분할 포지션에 얹히면 안 된다.

두 전략은 방향이 정반대다:
  볼밴 분할  = **내려갈수록** 더 산다 (평단 개선이 목적)
  피라미딩    = **올라갈수록** 더 산다 (평단 악화를 감수한 추세 추종)

실측 2026-08-29 — 볼밴 4건이 이것 때문에 죽었다:

  #1711  볼밴 1차   399개 @0.50110  (100 USDT)
         피라미딩  1146개 @0.52345  (300 USDT)   ← 더 비싸게
         피라미딩  1119개 @0.53621  (300 USDT)   ← 더 비싸게
         → 평단 0.50110 → 0.52546. 손절선이 **1차 진입가보다 위**로 올라와
           가격이 진입가로 되돌아오기만 해도 -10% 손절.

  #1721 / #1699(SHORT) / #1629 동일 패턴. 4건 합계 실현 **-252.18 USDT**
  (볼밴 전체 실현이 -39.06 이므로, 이것만 없었으면 크게 흑자였다).

결정타: 볼밴 TP1 은 **ROI +5% 부터 익절**인데 피라미딩 발동선도 ROI +5% 다.
익절해야 할 바로 그 지점에서 추가 매수가 나간다 = 사장님 설계와 정면 충돌.
게다가 mode=reset 이라 max_profit_pct 가 지워진다(#1629 는 +6.83% → None).
"""
from __future__ import annotations

import ast
from pathlib import Path

WORKERS = Path(__file__).resolve().parents[2] / "app" / "workers"
PYRAMID = WORKERS / "success_pyramiding_worker.py"

# 🚨 Fix 214 — **이미 열려 있는 전략에 계획 밖 진입을 얹을 수 있는** 워커들.
#   전부 볼밴(split_entry)을 제외해야 한다. 하나라도 새면 평단이 설계와 반대로 밀린다.
#   여기에 워커를 추가할 때는 그 워커도 같은 가드를 넣어야 한다.
MUST_EXCLUDE_BBSPLIT = (
    "success_pyramiding_worker.py",     # Fix 213 — 실제로 -252.18 USDT 를 냈다
    "resistance_reversal_worker.py",    # Fix 214 — SHORT 전략에 enter_stage_at_market
    "peak_break_reversal_worker.py",    # Fix 214 — 동일
)


def _attr_refs(path: Path, name: str) -> int:
    """모듈에서 `something.<name>` 참조 횟수 (주석·문자열은 세지 않는다 = 헌법 122)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sum(
        1 for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and n.attr == name
    )


def test_marker_value_stays_in_sync():
    """🚨 가장 깨지기 쉬운 지점 — 두 워커가 같은 문자열을 써야 한다.

    피라미딩 워커가 pump_split_entry_worker 를 import 하면 워커→워커 의존이 생겨
    값만 맞춰 뒀다. 그래서 **여기서 고정**한다. 한쪽만 바꾸면 가드가 조용히 샌다.
    """
    from app.workers.pump_split_entry_worker import MODE_MARKER
    from app.workers.success_pyramiding_worker import SPLIT_ENTRY_MODE

    assert SPLIT_ENTRY_MODE == MODE_MARKER, (
        f"볼밴 마커가 어긋났다: 피라미딩={SPLIT_ENTRY_MODE!r} 볼밴={MODE_MARKER!r} "
        "→ 피라미딩이 다시 볼밴 평단을 망가뜨린다"
    )


def test_single_source_of_truth_for_the_marker():
    """🚨 Fix 214 — 마커 문자열은 **한 곳**에만 있어야 한다.

    워커마다 "split_entry" 를 복사하면 한 곳만 오타나도 조용히 샌다.
    """
    from app.core.strategy_status import SPLIT_ENTRY_MODE
    from app.workers.pump_split_entry_worker import MODE_MARKER

    assert SPLIT_ENTRY_MODE == MODE_MARKER, (
        f"단일 출처가 어긋났다: strategy_status={SPLIT_ENTRY_MODE!r} "
        f"pump_split={MODE_MARKER!r}"
    )


def test_every_unplanned_entry_worker_excludes_bbsplit():
    """계획 밖 진입을 얹을 수 있는 워커는 **전부** 볼밴을 제외해야 한다.

    🚨 Fix 213 은 피라미딩만 막았다. 그런데 resistance_reversal / peak_break_reversal
       도 SHORT 전략에 enter_stage_at_market 를 부른다 — 그건 stage_no 가 채워져
       「계획된 단계 진입」처럼 보이지만 볼밴 트리거와 무관한 가격이다.
       볼밴 SHORT 가 드물어서 아직 안 터졌을 뿐, 구멍은 같은 종류다.
    """
    missing = [
        name for name in MUST_EXCLUDE_BBSPLIT
        if _attr_refs(WORKERS / name, "capital_management_mode") == 0
    ]
    assert not missing, (
        "볼밴 제외 가드가 없는 워커: " + ", ".join(missing)
        + " → 볼밴 평단이 설계와 반대로 밀린다 (실측 -252.18 USDT)"
    )


def test_in_loop_guard_still_present():
    """루프 안 방어 확인도 남아 있어야 한다 (헌법 138 — 집합만 믿지 않는다)."""
    src = ast.parse(PYRAMID.read_text(encoding="utf-8"))
    consts = {
        n.value for n in ast.walk(src)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert "capital_management_mode" in consts, (
        "루프 안 getattr(si, 'capital_management_mode', ...) 방어가 사라졌다"
    )


def test_detector_discriminates():
    """음성 대조군 (헌법 170) — 이 검사가 아무 모듈에서나 참이면 무의미하다.

    같은 워커 폴더의 다른 모듈에는 이 참조가 없어야 한다.
    전부 참이면 `_attr_refs` 가 고장난 것이다.
    """
    others = [
        p for p in WORKERS.glob("*.py")
        if p != PYRAMID and p.name != "__init__.py"
    ]
    assert others, "검사 대상 모듈을 못 찾았다"
    without = [p.name for p in others if _attr_refs(p, "capital_management_mode") == 0]
    assert without, (
        "모든 워커가 capital_management_mode 를 참조한다 = 이 검사는 아무것도 못 가린다"
    )
