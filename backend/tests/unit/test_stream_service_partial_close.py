"""StreamService.handle_order_trade_update — partial vs full close 회귀 테스트.

배경: 2026-04-30 #58 NAORISUSDT 사례에서 TP1 25% 부분 청산 후
strategy.current_position_qty 가 무조건 0 으로 리셋되어 잔량 6,011 lots 가
모니터링에서 빠지고 거래소엔 SHORT 그대로 남는 stuck 버그 발생.
fix (origin 0da0f55): cur_qty/exec_qty 의 abs 차이로 잔량 계산,
remaining_abs ≤ 1e-8 이면 전체 청산, 아니면 sign 곱해 잔량 유지 + status 보존.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.stream_service import StreamService


def _make_payload(client_order_id: str, status: str, exec_qty: str, avg_price: str) -> dict:
    return {
        "e": "ORDER_TRADE_UPDATE",
        "E": 1,
        "T": 1,
        "o": {
            "s": "NAORISUSDT",
            "c": client_order_id,
            "S": "BUY",
            "o": "MARKET",
            "f": "GTC",
            "q": exec_qty,
            "p": "0",
            "ap": avg_price,
            "sp": "0",
            "x": "TRADE",
            "X": status,
            "i": 9999,
            "l": exec_qty,
            "z": exec_qty,
            "L": avg_price,
            "n": "0",
            "N": "USDT",
            "T": 1,
            "t": 1,
            "ps": "SHORT",
            "rp": "0",
        },
    }


def _build_service(strategy: SimpleNamespace, order: SimpleNamespace) -> StreamService:
    """db 의 select(Order) / get(StrategyInstance) / sa_update / commit 을 모두 mock 한 인스턴스."""
    db = MagicMock()
    order_result = MagicMock()
    order_result.scalar_one_or_none.return_value = order
    update_result = MagicMock()
    update_result.rowcount = 0
    plan_result = MagicMock()
    plan_result.scalars.return_value.first.return_value = None
    db.execute.side_effect = [order_result, update_result, plan_result]
    db.get.return_value = strategy
    return StreamService(db)


class TestExitFilledPartialClose:
    """SHORT TP1 25% 부분 청산 → 잔량 75% 보존, status STAGE 유지."""

    def test_short_partial_close_preserves_remaining_qty_and_status(self) -> None:
        # given: SHORT 8014, 평균진입 0.12571546, status STAGE4_OPEN
        strategy = SimpleNamespace(
            id=58,
            symbol="NAORISUSDT",
            side="SHORT",
            current_position_qty=Decimal("-8014"),
            avg_entry_price=Decimal("0.12571546"),
            unrealized_pnl=Decimal("-1.0"),
            realized_pnl=Decimal("0"),
            status="STAGE4_OPEN",
            reentry_ready=False,
        )
        order = SimpleNamespace(
            client_order_id="exit-tp1-58",
            exchange_order_id=None,
            status="NEW",
            executed_qty=Decimal("0"),
            avg_price=Decimal("0"),
            price=Decimal("0"),
            purpose="EXIT",
            stage_no=None,
            strategy_instance_id=58,
        )

        # when: TP1 2003 lots 부분 청산 FILLED 이벤트
        service = _build_service(strategy, order)
        order.executed_qty = Decimal("2003")
        order.avg_price = Decimal("0.11687")
        order.status = "FILLED"
        service.handle_order_trade_update(_make_payload("exit-tp1-58", "FILLED", "2003", "0.11687"))

        # then: 잔량 -6011 보존 (== 비교, quantize 결과도 동일), status 그대로,
        # reentry_ready False, realized_pnl 누적
        assert strategy.current_position_qty == Decimal("-6011")
        assert strategy.status == "STAGE4_OPEN"  # REENTRY_READY 로 빠지면 안 됨
        assert strategy.reentry_ready is False
        assert strategy.realized_pnl == Decimal("17.72")

    def test_short_full_close_sets_reentry_ready_and_zero_qty(self) -> None:
        # given: 잔량 6011 (TP1 후) 수동 전체 청산 직전
        strategy = SimpleNamespace(
            id=58,
            symbol="NAORISUSDT",
            side="SHORT",
            current_position_qty=Decimal("-6011"),
            avg_entry_price=Decimal("0.12571546"),
            unrealized_pnl=Decimal("-2.5"),
            realized_pnl=Decimal("17.72"),
            status="STAGE4_OPEN",
            reentry_ready=False,
        )
        order = SimpleNamespace(
            client_order_id="exit-manual-58",
            exchange_order_id=None,
            status="NEW",
            executed_qty=Decimal("0"),
            avg_price=Decimal("0"),
            price=Decimal("0"),
            purpose="EXIT",
            stage_no=None,
            strategy_instance_id=58,
        )
        order.executed_qty = Decimal("6011")
        order.avg_price = Decimal("0.11684")
        order.status = "FILLED"

        service = _build_service(strategy, order)
        service.handle_order_trade_update(_make_payload("exit-manual-58", "FILLED", "6011", "0.11684"))

        # then: 0 으로 리셋, REENTRY_READY 전환, unrealized_pnl 도 0, 누적 realized 약 +71.07
        assert strategy.current_position_qty == Decimal("0")
        assert strategy.unrealized_pnl == Decimal("0")
        assert strategy.status == "REENTRY_READY"
        assert strategy.reentry_ready is True
        assert strategy.realized_pnl == Decimal("71.07")  # 17.72 + 53.35

    def test_long_partial_close_preserves_positive_qty(self) -> None:
        strategy = SimpleNamespace(
            id=99,
            symbol="BTCUSDT",
            side="LONG",
            current_position_qty=Decimal("100.5"),
            avg_entry_price=Decimal("50000"),
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
            status="STAGE2_OPEN",
            reentry_ready=False,
        )
        order = SimpleNamespace(
            client_order_id="exit-tp-99",
            exchange_order_id=None,
            status="NEW",
            executed_qty=Decimal("0"),
            avg_price=Decimal("0"),
            price=Decimal("0"),
            purpose="EXIT",
            stage_no=None,
            strategy_instance_id=99,
        )
        order.executed_qty = Decimal("30")
        order.avg_price = Decimal("51000")
        order.status = "FILLED"

        service = _build_service(strategy, order)
        service.handle_order_trade_update(_make_payload("exit-tp-99", "FILLED", "30", "51000"))

        assert strategy.current_position_qty == Decimal("70.5")
        assert strategy.status == "STAGE2_OPEN"
        assert strategy.reentry_ready is False
        # realized = 30 * (51000 - 50000) = 30000
        assert strategy.realized_pnl == Decimal("30000.00")

    def test_completed_status_is_preserved_on_full_close(self) -> None:
        """_execute_take_profit 가 이미 COMPLETED 로 세팅한 경우 REENTRY_READY 로 덮어쓰지 않음."""
        strategy = SimpleNamespace(
            id=42,
            symbol="ETHUSDT",
            side="LONG",
            current_position_qty=Decimal("10"),
            avg_entry_price=Decimal("3000"),
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
            status="COMPLETED",
            reentry_ready=False,
        )
        order = SimpleNamespace(
            client_order_id="exit-completed-42",
            exchange_order_id=None,
            status="NEW",
            executed_qty=Decimal("0"),
            avg_price=Decimal("0"),
            price=Decimal("0"),
            purpose="EXIT",
            stage_no=None,
            strategy_instance_id=42,
        )
        order.executed_qty = Decimal("10")
        order.avg_price = Decimal("3100")
        order.status = "FILLED"

        service = _build_service(strategy, order)
        service.handle_order_trade_update(_make_payload("exit-completed-42", "FILLED", "10", "3100"))

        assert strategy.status == "COMPLETED"
        assert strategy.reentry_ready is False  # COMPLETED 면 reentry 안 함
        assert strategy.current_position_qty == Decimal("0")

    def test_over_execution_clamps_to_zero(self) -> None:
        """ACCOUNT_UPDATE 가 먼저 와서 cur_qty 가 이미 줄어든 상태에서 ORDER_TRADE_UPDATE 가
        원래 청산 주문량으로 도착하는 경우 잔량이 음수로 가지 않도록 처리.
        origin 의 fix 는 remaining_abs = 70 - 100 = -30 → ≤ 1e-8 → full close 로 자연스럽게 처리됨."""
        strategy = SimpleNamespace(
            id=11,
            symbol="ALGOUSDT",
            side="LONG",
            current_position_qty=Decimal("70"),  # 이미 ACCOUNT_UPDATE 가 70 으로 줄임
            avg_entry_price=Decimal("0.5"),
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
            status="STAGE3_OPEN",
            reentry_ready=False,
        )
        order = SimpleNamespace(
            client_order_id="exit-overexec-11",
            exchange_order_id=None,
            status="NEW",
            executed_qty=Decimal("0"),
            avg_price=Decimal("0"),
            price=Decimal("0"),
            purpose="EXIT",
            stage_no=None,
            strategy_instance_id=11,
        )
        order.executed_qty = Decimal("100")  # 원래 청산 주문 전체량
        order.avg_price = Decimal("0.55")
        order.status = "FILLED"

        service = _build_service(strategy, order)
        service.handle_order_trade_update(_make_payload("exit-overexec-11", "FILLED", "100", "0.55"))

        # 70-100=-30 → ≤ 1e-8 → full close
        assert strategy.current_position_qty == Decimal("0")
        assert strategy.status == "REENTRY_READY"
