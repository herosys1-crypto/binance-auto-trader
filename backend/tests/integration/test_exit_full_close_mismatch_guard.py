"""stream_service is_full_close defensive check — REENTRY_READY 오마킹 방지.

배경 (2026-05-08 #120):
  EXIT MARKET 245 가 3건 발사되어 마지막 처리 시 DB 는 잔량 0 으로 판단
  → REENTRY_READY 마킹. 그러나 거래소엔 245 잔량이 남아있어 다음 zombie scan
  이 orphan 으로 감지 → Kill-Switch 발동.

  P0-1 (idempotency lock) 으로 중복 EXIT 발사는 차단됐지만, 어떤 이유든
  DB 가 stale 상태가 되면 같은 실수 재발 가능. defense-in-depth 로
  is_full_close 가 True 라도 거래소 실 포지션 한 번 더 확인.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.models.order import Order
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from app.services.stream_service import StreamService


class TestExitFullCloseMismatchGuard:
    def _setup_strategy_and_order(self, db_session, make_template, make_strategy, qty: str, exec_qty: str):
        """진입 후 EXIT FILLED 직전 상태로 strategy + order 생성."""
        tpl = make_template()
        s = make_strategy(
            symbol_str="DYDXUSDT", side="SHORT", status="STAGE1_OPEN",
            current_position_qty=Decimal(f"-{qty}"), avg_entry_price=Decimal("0.204"),
            template=tpl,
        )
        # EXIT MARKET 주문 (FILLED 직전)
        order = Order(
            strategy_instance_id=s.id, stage_no=None, purpose="EXIT",
            symbol="DYDXUSDT", side="BUY", position_side="SHORT",
            order_type="MARKET", time_in_force=None,
            client_order_id=f"test-exit-{s.id}",
            exchange_order_id="ex-1",
            orig_qty=Decimal(exec_qty), executed_qty=Decimal("0"),
            avg_price=Decimal("0.184"), price=Decimal("0.184"),
            status="NEW",
        )
        db_session.add(order)
        db_session.commit()
        return s, order

    def test_full_close_with_exchange_remaining_blocks_reentry(
        self, db_session, make_template, make_strategy,
    ):
        """DB 는 잔량 0 이지만 거래소엔 245 남음 → REENTRY_READY 마킹 차단."""
        s, order = self._setup_strategy_and_order(
            db_session, make_template, make_strategy, qty="245", exec_qty="245",
        )
        # is_full_close 시 거래소가 245 잔량 보고
        with patch.object(StreamService, "_fetch_actual_position_qty", return_value=Decimal("245")):
            payload = {
                "o": {
                    "c": order.client_order_id, "i": order.exchange_order_id,
                    "s": "DYDXUSDT", "S": "BUY", "ps": "SHORT", "o": "MARKET",
                    "X": "FILLED", "x": "TRADE",
                    "q": "245", "z": "245", "ap": "0.184",
                }
            }
            StreamService(db_session).handle_order_trade_update(payload)

        db_session.refresh(s)
        # 차단 효과: status 그대로, qty 는 거래소값으로 정정
        assert s.status == "STAGE1_OPEN", "REENTRY_READY 마킹 차단돼야 함"
        assert s.current_position_qty == Decimal("-245.00000000"), "DB qty 정정됨"
        assert s.reentry_ready is False

        # WARN RiskEvent 기록
        ev = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "EXIT_FULL_CLOSE_MISMATCH")
        ).scalars().first()
        assert ev is not None
        assert ev.severity == "WARN"
        assert "거래소 잔량 존재" in ev.title

    def test_full_close_with_exchange_zero_proceeds_normally(
        self, db_session, make_template, make_strategy,
    ):
        """거래소도 잔량 0 이면 정상 REENTRY_READY 진행."""
        s, order = self._setup_strategy_and_order(
            db_session, make_template, make_strategy, qty="245", exec_qty="245",
        )
        with patch.object(StreamService, "_fetch_actual_position_qty", return_value=Decimal("0")):
            payload = {
                "o": {
                    "c": order.client_order_id, "i": order.exchange_order_id,
                    "s": "DYDXUSDT", "S": "BUY", "ps": "SHORT", "o": "MARKET",
                    "X": "FILLED", "x": "TRADE",
                    "q": "245", "z": "245", "ap": "0.184",
                }
            }
            StreamService(db_session).handle_order_trade_update(payload)

        db_session.refresh(s)
        assert s.status == "REENTRY_READY"
        assert s.current_position_qty == Decimal("0")
        assert s.reentry_ready is True

    def test_fetch_failure_falls_back_to_old_behavior(
        self, db_session, make_template, make_strategy,
    ):
        """거래소 조회 실패 (None) → fail-soft, 기존 동작 (REENTRY_READY)."""
        s, order = self._setup_strategy_and_order(
            db_session, make_template, make_strategy, qty="245", exec_qty="245",
        )
        with patch.object(StreamService, "_fetch_actual_position_qty", return_value=None):
            payload = {
                "o": {
                    "c": order.client_order_id, "i": order.exchange_order_id,
                    "s": "DYDXUSDT", "S": "BUY", "ps": "SHORT", "o": "MARKET",
                    "X": "FILLED", "x": "TRADE",
                    "q": "245", "z": "245", "ap": "0.184",
                }
            }
            StreamService(db_session).handle_order_trade_update(payload)

        db_session.refresh(s)
        # fail-soft: 기존 동작 유지 (REENTRY_READY)
        assert s.status == "REENTRY_READY"
        assert s.current_position_qty == Decimal("0")
