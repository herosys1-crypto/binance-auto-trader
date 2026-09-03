"""Fix 318 — 손절도 「부분 손절」이어야 한다.

사장님 2026-09-03:
  "전략인스턴스에 선택한 옵션으로 **부분 손절**하고 다음 트리거 단가에 포지션 진입"
  "왜 이것도 **10usdt 남기고 부분손절**을 해야 하는데 왜 이런거야"

🚨 Fix 304 는 「단계 진입 **직전** 정리」에만 붙어 있었다. 손절선에 먼저 닿으면
   전량 청산이 나가고 전략이 종료됐다 (#2046 AKEUSDT 실사고).
"""
import ast
from pathlib import Path

from app.services import tp_sl_orchestrator as O

SRC = Path(O.__file__).read_text(encoding="utf-8")


def _fn(name: str) -> str:
    tree = ast.parse(SRC)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return ast.get_source_segment(SRC, n) or ""
    raise AssertionError(f"{name} 없음")


def test_손절이_compute_trim_으로_수량을_정한다():
    src = _fn("_execute_stop_loss")
    assert "compute_trim" in src, "손절 수량이 전량 고정이면 사장님 사양이 깨진다"
    assert "trim_enabled(self.db, strategy)" in src, "전략별 판정이어야 한다"


def test_TRIM_일_때만_부분_손절():
    """SKIP/BLOCK 이면 전량 — 손절을 건너뛰면 손실이 무한정 커진다."""
    src = _fn("_execute_stop_loss")
    assert "if _act == ACTION_TRIM and _c > 0:" in src


def test_판정_실패는_전량_청산():
    """🚨 단계 진입과 fail 방향이 **반대**다.
    진입은 막으면 그만이지만, 손절은 막으면 손실이 커진다."""
    src = _fn("_execute_stop_loss")
    blk = src[src.index("except Exception as _fe:"):]
    blk = blk[:blk.index("try:", 10)] if "try:" in blk[10:] else blk[:400]
    assert "전량 청산" in blk


def test_잔량이_남으면_전략을_종료하지_않는다():
    """🚨 STOPPING 을 찍으면 stream_service 가 STOPPED(터미널)로 확정해
    「전략 인스턴스에 남겨두기」와 다음 단계 진입이 모두 깨진다."""
    src = _fn("_execute_stop_loss")
    i_keep = src.index("if _keep_qty > 0:")
    i_stop = src.index('strategy.status = "STOPPING"')
    assert i_keep < i_stop, "잔량 검사가 STOPPING 보다 먼저여야 한다"
    blk = src[i_keep:i_stop]
    assert "return" in blk, "잔량이 있으면 종료 경로로 안 가야 한다"


def test_전환_플래그를_넘겨_주문취소를_막는다():
    """부분 손절인데 cancel_all_orders 가 돌면 다음 단계 LIMIT 이 사라진다."""
    src = _fn("_execute_stop_loss")
    assert "for_stage_transition=bool(_keep_qty > 0)" in src


def test_전량_손절도_여전히_가능하다():
    """trim 이 꺼졌거나 소액이면 옛 동작 그대로."""
    src = _fn("_execute_stop_loss")
    assert "_close_qty = current_qty" in src, "기본값이 전량이어야 한다"


def test_실측_근거가_주석에_남아_있다():
    src = _fn("_execute_stop_loss")
    assert "#2046" in src and "부분 손절" in src
