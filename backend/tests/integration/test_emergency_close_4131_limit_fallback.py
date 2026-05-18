"""emergency_close -4131 (PERCENT_PRICE) → LIMIT 폴백 회귀.

배경 (사용자 보고 2026-05-19, #62 MLNUSDT):
- 저유동성 심볼 강제 청산이 MARKET 으로 발송됐는데 호가창이 얇아
  Binance -4131 "counterparty's best price does not meet the PERCENT_PRICE
  filter limit" 로 거부 → 포지션 stuck + 매 cycle 재시도 루프
- qty>0 라 기존 qty=0 guard 도 안 걸림 (rate-limit fix 와 별개 원인)

Fix: MARKET 이 -4131 거부되면 PERCENT_PRICE 밴드 경계가 LIMIT GTC 폴백.
- SELL(롱청산): 하한가 ceil-to-tick (밴드 내 최저 = 가장 공격적)
- BUY(숏청산): 상한가 floor-to-tick (밴드 내 최고)

이 테스트는 밴드 계산 + 폴백 주문 페이로드를 결정적으로 검증.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.execution_service import ExecutionService


@pytest.fixture
def execution(db_session):
    return ExecutionService(
        db_session, api_key="enc:k", api_secret="enc:s", is_testnet=True,
    )


class _StubClient:
    """place_order 만 기록. _emergency_close_limit_fallback 검증용."""
    def __init__(self):
        self.placed: list[dict] = []

    def place_order(self, payload: dict) -> dict:
        self.placed.append(payload)
        return {
            "orderId": 555, "status": "NEW",
            "price": payload.get("price"), "executedQty": "0",
            "clientOrderId": payload.get("newClientOrderId"),
        }


class TestPercentPriceBounds:
    def test_uses_exchange_filter(self, db_session, execution, make_symbol):
        """raw_exchange_info 의 PERCENT_PRICE multiplier 사용."""
        make_symbol(
            "MLNUSDT", tick_size=Decimal("0.001"),
            raw_exchange_info={"filters": [
                {"filterType": "PERCENT_PRICE",
                 "multiplierUp": "1.20", "multiplierDown": "0.80"},
            ]},
        )
        lower, upper, tick = execution._percent_price_bounds("MLNUSDT", Decimal("10"))
        assert lower == Decimal("8.0")    # 10 * 0.80
        assert upper == Decimal("12.0")   # 10 * 1.20
        assert tick == Decimal("0.001")

    def test_fallback_when_no_filter(self, db_session, execution, make_symbol):
        """필터 없으면 보수적 ±5%."""
        make_symbol("FOOUSDT", tick_size=Decimal("0.01"), raw_exchange_info={"filters": []})
        lower, upper, tick = execution._percent_price_bounds("FOOUSDT", Decimal("100"))
        assert lower == Decimal("95.00")
        assert upper == Decimal("105.00")
        assert tick == Decimal("0.01")


class TestLimitFallbackOrder:
    def test_sell_uses_lower_bound_ceiled(
        self, db_session, execution, make_symbol, make_template, make_strategy, monkeypatch
    ):
        """롱 청산(SELL): 하한가를 tick ceil — 밴드 내 최저, 거래소 수락."""
        make_symbol(
            "MLNUSDT", tick_size=Decimal("0.001"),
            raw_exchange_info={"filters": [
                {"filterType": "PERCENT_PRICE",
                 "multiplierUp": "1.05", "multiplierDown": "0.95"},
            ]},
        )
        tpl = make_template()
        s = make_strategy(symbol_str="MLNUSDT", side="LONG", status="TP3_DONE_PARTIAL",
                          current_position_qty=Decimal("373.09"), template=tpl)
        monkeypatch.setattr(execution, "_fetch_current_mark_price",
                            lambda sym: Decimal("0.0754"))
        stub = _StubClient()
        execution.client = stub

        execution._emergency_close_limit_fallback(
            s, side="SELL", position_side="LONG",
            quantity=Decimal("373.09"), client_order_id="MLNUSDT_EXIT_x",
        )
        assert len(stub.placed) == 1
        p = stub.placed[0]
        assert p["type"] == "LIMIT" and p["timeInForce"] == "GTC"
        assert p["side"] == "SELL" and p["positionSide"] == "LONG"
        # lower = 0.0754 * 0.95 = 0.071630 → tick(0.001) ceil = 0.072
        assert Decimal(p["price"]) == Decimal("0.072")
        assert Decimal(p["price"]) >= Decimal("0.0754") * Decimal("0.95")  # 밴드 내

    def test_buy_uses_upper_bound_floored(
        self, db_session, execution, make_symbol, make_template, make_strategy, monkeypatch
    ):
        """숏 청산(BUY): 상한가를 tick floor — 밴드 내 최고, 거래소 수락."""
        make_symbol(
            "MLNUSDT", tick_size=Decimal("0.001"),
            raw_exchange_info={"filters": [
                {"filterType": "PERCENT_PRICE",
                 "multiplierUp": "1.05", "multiplierDown": "0.95"},
            ]},
        )
        tpl = make_template()
        s = make_strategy(symbol_str="MLNUSDT", side="SHORT", status="TP3_DONE_PARTIAL",
                          current_position_qty=Decimal("-373.09"), template=tpl)
        monkeypatch.setattr(execution, "_fetch_current_mark_price",
                            lambda sym: Decimal("0.0754"))
        stub = _StubClient()
        execution.client = stub

        execution._emergency_close_limit_fallback(
            s, side="BUY", position_side="SHORT",
            quantity=Decimal("373.09"), client_order_id="MLNUSDT_EXIT_y",
        )
        p = stub.placed[0]
        assert p["side"] == "BUY" and p["type"] == "LIMIT"
        # upper = 0.0754 * 1.05 = 0.079170 → tick(0.001) floor = 0.079
        assert Decimal(p["price"]) == Decimal("0.079")
        assert Decimal(p["price"]) <= Decimal("0.0754") * Decimal("1.05")  # 밴드 내
