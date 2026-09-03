"""Fix 317/321 — 다단계 전략에서 손절이 마지막 단계까지 보류되던 문제.

사장님 2026-09-03: "일단 급한건 기본 방식이야 이건 확실하게 해줘야해
                   그래야 지금까지 잃은걸 다시 벌수 있어"

실측: 단계 계획이 있는 전략 1,221건 중 **371건(30%)** 이 이 게이트에 걸려
      손절이 열리지 않고 있었다. 사장님이 -3% 로 설정해도 3단계를 다 채우기
      전에는 손절이 안 된다.

🚨 Fix 321: 면제 판정이 **세 곳에 흩어져** 있고 force SL 한 곳에만 있었다.
   그래서 Fix 315 가 신규 전략을 3단계로 바꾸자 일반 SL 이 그대로 잠겼다.
   → `_stage_gate_exempt` 공용 메서드로 모았다.
   면제 규칙 자체의 상세 검증은 `tests/test_stage_gate_exempt.py` 참조.
"""
import ast
from pathlib import Path

from app.services import risk_service as R

SRC = Path(R.__file__).read_text(encoding="utf-8")


def _fn(name: str) -> str:
    tree = ast.parse(SRC)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return ast.get_source_segment(SRC, n) or ""
    raise AssertionError(f"{name} 없음")


def test_force_SL이_면제를_확인한다():
    """🚨 사장님이 화면에서 정하는 손절(-5%/-10%)이 타는 경로."""
    src = _fn("evaluate_force_stop_loss")
    assert "_stage_gate_exempt(strategy)" in src
    assert "if _exempt_fsl:" in src


def test_일반_SL도_면제를_확인한다():
    """🚨 Fix 317 은 force SL 만 열었다. 일반 SL(-80~90%)은 그대로 잠겨 있었다."""
    src = _fn("evaluate_stop_loss")
    assert "_stage_gate_exempt(strategy)" in src
    assert "if not _exempt and" in src


def test_v130_게이트에도_면제가_걸린다():
    """`evaluate_force_stop_loss` 안의 v130 SL 분기."""
    assert "_ex2, _why2 = self._stage_gate_exempt(strategy)" in SRC
    assert "if not _ex2 and _current_stage < _total_stages:" in SRC


def test_게이트_자체는_남아_있다():
    """trim 이 꺼진 옛 물타기 전략은 v130 동작 그대로여야 한다 —
    남의 전략을 바꾸지 않는다."""
    assert "_current_stage_fsl < _total_stages_fsl" in SRC
    assert "_current_stage < _total_stages" in SRC


def test_사유_로그가_어느_모드인지_밝힌다():
    """🚨 「왜 게이트를 건너뛰었나」가 로그에 남아야 사장님이 확인할 수 있다."""
    src = _fn("evaluate_force_stop_loss")
    assert "_why_fsl" in src
    helper = _fn("_stage_gate_exempt")
    for label in ("청산 후 재진입", "split_entry", "stage_ladder", "Fix304"):
        assert label in helper, label


def test_실측_근거가_주석에_남아_있다():
    """다음에 무심코 게이트를 되돌리지 않도록."""
    src = _fn("_stage_gate_exempt")
    assert "371건" in src and "1,221건" in src
    assert "#2046" in src, "실제 사례가 남아 있어야 한다"


def test_면제_판정이_한_곳에만_정의된다():
    """🚨 흩어져 있으면 한쪽만 고치는 사고가 또 난다 (이번 사고의 뿌리)."""
    assert SRC.count("def _stage_gate_exempt") == 1
    assert SRC.count("self._stage_gate_exempt(strategy)") == 3
    # 옛 개별 조건 잔재가 남아 있으면 안 된다
    assert "_retry_flow or _split_mode" not in SRC
