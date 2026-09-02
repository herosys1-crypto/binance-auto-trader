"""Fix 308 — 손절 이벤트 이름 불일치 (생산자 vs 소비자).

`reentry_alert_watcher` 가 찾던 세 이름은 이 저장소 **어디에서도 기록되지 않았다.**
그래서 손절 369건(30일)이 있었는데 매 사이클 `checked=0` 을 찍었고,
OBV 자동 진입은 30일간 **0건**이었다.

🚨 이 저장소가 반복해서 겪은 「생산자·소비자 스키마 불일치」다
   (Fix 208 학습 표본 전멸, Fix 197 STAGE_1_OPEN 오타와 같은 성격).
"""
import ast
from pathlib import Path

from app.workers import reentry_alert_watcher as W

SRC = Path(W.__file__).read_text(encoding="utf-8")
APP = Path(W.__file__).resolve().parents[1]


def _written_event_types() -> set:
    """`event_type=` 로 **실제로 기록되는** 이름을 소스 전체에서 뽑는다."""
    out = set()
    for p in APP.rglob("*.py"):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords or []:
                if kw.arg == "event_type" and isinstance(kw.value, ast.Constant) \
                        and isinstance(kw.value.value, str):
                    out.add(kw.value.value)
    return out


def _watched_event_types() -> set:
    """이 워커가 **조회하는** 이름."""
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "in_"
                and node.args
                and isinstance(node.args[0], ast.List)):
            vals = {e.value for e in node.args[0].elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            if any("SL" in v or "STOP" in v for v in vals):
                return vals
    return set()


def test_조회하는_이름이_실제로_기록되는_이름이다():
    """🚨 이게 이 버그의 전부다 — 두 집합이 겹치지 않으면 워커는 영원히 0건이다."""
    watched = _watched_event_types()
    assert watched, "조회 목록을 못 찾았다 — 테스트가 무력화됐다"
    written = _written_event_types()
    missing = watched - written
    assert not missing, (
        f"기록되지 않는 이름을 조회하고 있다: {sorted(missing)} "
        f"(실제 기록되는 손절 이름: "
        f"{sorted(v for v in written if 'STOP' in v or 'SL' in v)})"
    )


def test_실제_손절_이벤트를_잡는다():
    assert "FORCE_STOP_LOSS_TRIGGERED" in _watched_event_types()


def test_한_번도_기록된_적_없는_옛_이름을_지웠다():
    """남겨두면 「무언가 더 잡히겠지」라는 착시를 준다."""
    for dead in ("FORCE_SL_TRIGGERED", "SL_TRIGGERED", "STRATEGY_STOPPED_BY_SL"):
        assert f'"{dead}",' not in SRC.split("event_type.in_")[1][:200], dead


def test_근거가_주석에_남아_있다():
    assert "369" in SRC and "checked=0" in SRC
    assert "risk_service.py:428" in SRC
