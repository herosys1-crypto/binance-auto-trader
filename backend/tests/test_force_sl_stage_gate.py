"""Fix 317 — 다단계 전략에서 손절이 마지막 단계까지 보류되던 문제.

사장님 2026-09-03: "일단 급한건 기본 방식이야 이건 확실하게 해줘야해
                   그래야 지금까지 잃은걸 다시 벌수 있어"

실측: 단계 계획이 있는 전략 1,221건 중 **371건(30%)** 이 이 게이트에 걸려
      손절이 열리지 않고 있었다. 사장님이 -3% 로 설정해도 3단계를 다 채우기
      전에는 손절이 안 된다.
"""
import ast
from pathlib import Path

from app.services import risk_service as R

SRC = Path(R.__file__).read_text(encoding="utf-8")


def _force_sl_src() -> str:
    tree = ast.parse(SRC)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == "evaluate_force_stop_loss":
            return ast.get_source_segment(SRC, n) or ""
    raise AssertionError("evaluate_force_stop_loss 없음")


def test_단계_정리_모드는_게이트를_건너뛴다():
    """🚨 trim ON = 「단계마다 청산하고 다음 단계」 → 손절도 단계마다 열려야 한다."""
    src = _force_sl_src()
    assert "_trim_mode" in src
    assert "if _retry_flow or _split_mode or _ladder_mode or _trim_mode:" in src


def test_네_가지_모드가_모두_게이트를_건너뛴다():
    src = _force_sl_src()
    for mode in ("_retry_flow", "_split_mode", "_ladder_mode", "_trim_mode"):
        assert mode in src, mode


def test_trim_판정_실패는_옛_동작을_유지한다():
    """🚨 여기서 fail-open 하면 물타기 전략의 손절까지 앞당겨진다 —
    남의 전략을 바꾸지 않는다는 이 파일의 원칙."""
    src = _force_sl_src()
    blk = src[src.index("_trim_mode = False"):]
    blk = blk[:blk.index("if _retry_flow")]
    assert "except Exception" in blk
    assert "_trim_mode = False" in blk.split("try:")[0]


def test_게이트_자체는_남아_있다():
    """trim 이 꺼진 전략(옛 물타기)은 v130 동작 그대로여야 한다."""
    src = _force_sl_src()
    assert "_current_stage_fsl < _total_stages_fsl" in src


def test_사유_로그가_어느_모드인지_밝힌다():
    """🚨 「왜 게이트를 건너뛰었나」가 로그에 남아야 사장님이 확인할 수 있다."""
    src = _force_sl_src()
    assert "단계 정리(Fix304)" in src


def test_실측_근거가_주석에_남아_있다():
    src = _force_sl_src()
    assert "371건" in src and "1,221건" in src
    assert "#2046" in src or "AKEUSDT" in src
