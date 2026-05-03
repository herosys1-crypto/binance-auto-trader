"""stream_service.handle_order_trade_update — 옵션 C 1~10단계 status 전이 회귀.

배경: 2026-05-04 까지 stream_service 가 stage 1~4 만 dict 매핑 →
5+ 단계 ENTRY FILLED 시 status 변경 안 됨 → STAGE4_OPEN 에 stuck. UI/reconcile
모두 영향. fix 후 1~10 모두 STAGE{N}_OPEN 으로 정확 전이.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.stream_service import StreamService


def _entry_filled_payload(client_order_id: str, exec_qty: str) -> dict:
    return {
        "e": "ORDER_TRADE_UPDATE",
        "E": 1, "T": 1,
        "o": {
            "s": "BTCUSDT", "c": client_order_id, "S": "SELL",
            "o": "LIMIT", "f": "GTC",
            "q": exec_qty, "p": "50000", "ap": "50000", "sp": "0",
            "x": "TRADE", "X": "FILLED", "i": 5000,
            "l": exec_qty, "z": exec_qty, "L": "50000",
            "n": "0", "N": "USDT", "T": 1, "t": 1,
            "ps": "SHORT", "rp": "0",
        },
    }


def _build_service(strategy: SimpleNamespace, order: SimpleNamespace) -> StreamService:
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


class TestStageOpenStatusForAllStages:
    """1~10단계 ENTRY FILLED → strategy.status 가 STAGE{N}_OPEN 으로 전이."""

    @pytest.mark.parametrize("stage_no", list(range(1, 11)))
    def test_entry_filled_transitions_to_stage_n_open(self, stage_no: int) -> None:
        strategy = SimpleNamespace(
            id=1000 + stage_no,
            symbol="BTCUSDT", side="SHORT",
            current_position_qty=Decimal("0"),
            avg_entry_price=Decimal("50000"),
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
            status=f"STAGE{stage_no}_OPEN_PENDING",
            reentry_ready=False,
        )
        order = SimpleNamespace(
            client_order_id=f"entry-stage{stage_no}",
            exchange_order_id=None,
            status="NEW",
            executed_qty=Decimal("0"),
            avg_price=Decimal("0"),
            price=Decimal("50000"),
            purpose="ENTRY",
            stage_no=stage_no,
            strategy_instance_id=strategy.id,
        )

        service = _build_service(strategy, order)
        service.handle_order_trade_update(_entry_filled_payload(f"entry-stage{stage_no}", "0.5"))

        assert strategy.status == f"STAGE{stage_no}_OPEN", (
            f"stage {stage_no} ENTRY FILLED 시 STAGE{stage_no}_OPEN 으로 전이해야 함 "
            f"(이전 1~4 hardcoded 버그 회귀 방어)"
        )

    def test_invalid_stage_no_does_not_change_status(self) -> None:
        """stage_no 가 범위 밖 (0 이나 11) 이면 status 변경 안 함 (방어적)."""
        strategy = SimpleNamespace(
            id=2000,
            symbol="BTCUSDT", side="SHORT",
            current_position_qty=Decimal("0"),
            avg_entry_price=Decimal("50000"),
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
            status="STAGE2_OPEN",  # 기존 status
            reentry_ready=False,
        )
        order = SimpleNamespace(
            client_order_id="entry-bogus",
            exchange_order_id=None,
            status="NEW",
            executed_qty=Decimal("0"),
            avg_price=Decimal("0"),
            price=Decimal("50000"),
            purpose="ENTRY",
            stage_no=11,  # 범위 밖
            strategy_instance_id=strategy.id,
        )
        service = _build_service(strategy, order)
        service.handle_order_trade_update(_entry_filled_payload("entry-bogus", "0.5"))

        assert strategy.status == "STAGE2_OPEN"  # 변경 없음
