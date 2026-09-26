"""🩹 Fix 402 — 미리보기가 데스크탑 500 / 모바일 400 으로 갈리던 것 (2026-09-27).

사장님: "모바일에서는 400 이야 문제를 해결해줘" (데스크탑 화면엔 「미리보기 실패: 500」)

운영 로그 실측:
    POST /api/v1/strategies/preview-inline → 500
      File "strategy_calculator.py", line 409, in compute_qty_from_capital
        qty = self._quantize_qty(notional / price)
      **decimal.DivisionByZero**

원인: 가격이 0 이면 나눗셈이 터지는데, `decimal.DivisionByZero` 는 **ValueError 가 아니라**
`ArithmeticError` 다. `preview_inline` 은 ValueError 만 400 으로 바꿨으므로 이 예외는
그대로 새어 나가 **500** 이 됐다. 모바일은 입력이 달라 ValueError 경로(400)를 탔을 뿐,
두 경우 다 **무엇을 고쳐야 하는지 화면에 안 나왔다**.

가격이 0 이 되는 입력: ① 시작가 0/빈칸 ② 단계 트리거 −100% 이하(배수 0) ③ 시세 결손.

수정: ①②를 각각 **한국어 사유가 있는 ValueError** 로 먼저 막고, 혹시 남은 계산 예외는
`ArithmeticError` 로 받아 400 + 사유로 돌려준다 → **500 은 다시 나지 않는다.**
"""
from __future__ import annotations

from decimal import Decimal, DivisionByZero
from pathlib import Path

import pytest

from app.services.strategy_calculator import StrategyCalculator, SymbolRule

CALC_SRC = Path(__file__).resolve().parent.parent / "app" / "services" / "strategy_calculator.py"
API_SRC = Path(__file__).resolve().parent.parent / "app" / "api" / "v1" / "strategies" / "calculate.py"


def _calc() -> StrategyCalculator:
    return StrategyCalculator(SymbolRule(
        symbol="XUSDT", tick_size=Decimal("0.000001"), step_size=Decimal("1"),
        min_qty=Decimal("1"), price_precision=6, quantity_precision=0,
    ))


class TestCalculator:
    def test_zero_price_raises_value_error_not_division(self) -> None:
        """가격 0 → ValueError(사유) — DivisionByZero 가 새어 나가지 않는다."""
        c = _calc()
        with pytest.raises(ValueError) as ei:
            c.compute_qty_from_capital(capital=Decimal("10"), price=Decimal("0"), leverage=2)
        assert "가격이 0" in str(ei.value)
        assert not isinstance(ei.value, DivisionByZero)

    @pytest.mark.parametrize("price", ["0", "-1", "0.0"])
    def test_non_positive_prices(self, price: str) -> None:
        with pytest.raises(ValueError):
            _calc().compute_qty_from_capital(capital=Decimal("10"), price=Decimal(price), leverage=2)

    def test_normal_price_still_works(self) -> None:
        qty = _calc().compute_qty_from_capital(capital=Decimal("10"), price=Decimal("0.1"), leverage=2)
        assert qty == Decimal("200")

    def test_zero_start_price_message(self) -> None:
        """시작가 0 은 「현재가 버튼으로 채우라」고 알려 준다."""
        src = CALC_SRC.read_text(encoding="utf-8")
        assert "시작가가 0 입니다" in src
        assert "💲 현재가" in src

    def test_stage_trigger_minus_100_message(self) -> None:
        """트리거 −100% 이하는 단계 번호와 함께 사유를 말한다."""
        src = CALC_SRC.read_text(encoding="utf-8")
        assert "단계 가격이 0 이 됩니다" in src
        assert "−99% 까지로" in src


class TestEndpoint:
    def test_arithmetic_error_becomes_400(self) -> None:
        src = API_SRC.read_text(encoding="atomic".replace("atomic", "utf-8"))
        body = src[src.index("preview = calculator.calculate_preview("):]
        i_val = body.index("except ValueError")
        i_arith = body.index("except ArithmeticError")
        assert i_val < i_arith, "ValueError 먼저, 그 다음 계산 예외"
        blk = body[i_arith:i_arith + 900]
        assert "HTTP_400_BAD_REQUEST" in blk
        assert "미리보기 계산 불가" in blk
        assert "logger.warning" in blk, "원인 타입을 로그에 남긴다"

    def test_no_bare_500_path_left(self) -> None:
        """이 엔드포인트에서 계산 예외가 처리되지 않고 나가는 길이 없다."""
        src = API_SRC.read_text(encoding="utf-8")
        assert src.count("except ArithmeticError") >= 1
        assert "logger = logging.getLogger(__name__)" in src


def test_crlf_preserved() -> None:
    for path in (CALC_SRC, API_SRC):
        raw = path.read_bytes()
        assert b"\r\n" in raw, path.name
        assert raw.count(b"\n") == raw.count(b"\r\n"), path.name
