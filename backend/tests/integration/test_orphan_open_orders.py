"""사용자 #VICUSDT 보고 (2026-05-15) — 거래소 open order 좀비 감지.

배경:
- 5-13 발송된 LIMIT order (Open Short 397 VIC, filled 0) 가 5-15 까지 거래소에 머물러 있음
- 매칭 active strategy 없음 (archive/stop 시 cancel_all_orders 누락 의심)
- detect_orphan_exchange_positions 는 포지션만 감지 — open order 는 별도 필요

신규: detect_orphan_exchange_open_orders
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.order import Order
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance


class _MockClient:
    """list_open_orders 만 mock (다른 메서드는 사용 안 함)."""
    def __init__(self, *args, open_orders_response=None, **kwargs):
        self._oo = open_orders_response or []

    def list_open_orders(self, symbol=None):
        return self._oo


@pytest.fixture
def patched_binance_open_orders(monkeypatch):
    """detect_orphan_exchange_open_orders 가 호출하는 BinanceClient 패치."""
    state = {"open_orders": []}

    class _Patched(_MockClient):
        def __init__(self, *args, **kwargs):
            super().__init__(open_orders_response=state["open_orders"])

    monkeypatch.setattr(
        "app.integrations.binance.client.BinanceClient",
        _Patched,
    )
    return state


class TestDetectOrphanExchangeOpenOrders:
    """사용자 #VICUSDT 시나리오 — 거래소 open order 좀비 감지."""

    def test_orphan_open_order_emits_warn(
        self,
        db_session,
        make_user,
        make_exchange_account,
        identity_decrypt,
        patched_binance_open_orders,
    ):
        """거래소에 open order 있는데 매칭 active strategy 없음 → WARN RiskEvent."""
        from app.services.zombie_guardian import detect_orphan_exchange_open_orders

        u = make_user()
        ea = make_exchange_account(user=u)

        # 2일 전 발송된 LIMIT order (사용자 #VICUSDT 사례)
        order_time_ms = int((datetime.now(timezone.utc).timestamp() - 2 * 86400) * 1000)
        patched_binance_open_orders["open_orders"] = [{
            "symbol": "VICUSDT",
            "positionSide": "SHORT",
            "side": "SELL",
            "type": "LIMIT",
            "origQty": "397",
            "price": "0.0754",
            "clientOrderId": "VICUSDT_ENTRY_abcd1234",
            "orderId": 12345,
            "time": order_time_ms,
        }]

        n = detect_orphan_exchange_open_orders(
            db_session, decrypt_func=identity_decrypt, auto_cancel=False,
        )
        assert n == 1, "orphan open order 1건 감지 필수"

        # WARN RiskEvent 발생 확인
        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "ZOMBIE_ORPHAN_OPEN_ORDER")
        ).scalars().all()
        assert len(events) == 1
        assert events[0].severity == "WARN"
        assert "VICUSDT" in events[0].title
        # age 정보 표시 (사용자가 「오래된 좀비」 인지 빠르게 판단)
        assert "h" in events[0].title  # age 시간 단위

    def test_open_order_with_matching_active_strategy_no_warn(
        self,
        db_session,
        make_user,
        make_exchange_account,
        make_symbol,
        make_template,
        make_strategy,
        identity_decrypt,
        patched_binance_open_orders,
    ):
        """매칭 active strategy 있으면 정상 — WARN 발송 안 함."""
        from app.services.zombie_guardian import detect_orphan_exchange_open_orders

        u = make_user()
        ea = make_exchange_account(user=u)
        sym = make_symbol("VICUSDT")
        tpl = make_template()
        s = make_strategy(
            user=u, exchange_account=ea, symbol_obj=sym, template=tpl,
            symbol_str="VICUSDT", side="SHORT", status="STAGE1_OPEN_PENDING",
        )

        patched_binance_open_orders["open_orders"] = [{
            "symbol": "VICUSDT",
            "positionSide": "SHORT",
            "side": "SELL",
            "type": "LIMIT",
            "origQty": "397",
            "price": "0.0754",
            "clientOrderId": "VICUSDT_ENTRY_xyz",
            "orderId": 99999,
            "time": int(datetime.now(timezone.utc).timestamp() * 1000),
        }]

        n = detect_orphan_exchange_open_orders(
            db_session, decrypt_func=identity_decrypt,
        )
        # symbol/side 매칭 active strategy 있으니 orphan 아님
        assert n == 0

    def test_open_order_with_matching_local_order_no_warn(
        self,
        db_session,
        make_user,
        make_exchange_account,
        make_symbol,
        make_template,
        make_strategy,
        identity_decrypt,
        patched_binance_open_orders,
    ):
        """clientOrderId 가 DB Order 와 일치 + strategy active → 정상."""
        from app.services.zombie_guardian import detect_orphan_exchange_open_orders

        u = make_user()
        ea = make_exchange_account(user=u)
        sym = make_symbol("BTCUSDT")
        tpl = make_template()
        s = make_strategy(
            user=u, exchange_account=ea, symbol_obj=sym, template=tpl,
            symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN_PENDING",
        )
        # 정확히 매칭되는 DB Order
        db_session.add(Order(
            strategy_instance_id=s.id, symbol="BTCUSDT", side="SELL",
            position_side="SHORT", order_type="LIMIT", purpose="ENTRY",
            client_order_id="BTCUSDT_ENTRY_match1", status="NEW",
        ))
        db_session.commit()

        patched_binance_open_orders["open_orders"] = [{
            "symbol": "BTCUSDT",
            "positionSide": "SHORT",
            "side": "SELL",
            "type": "LIMIT",
            "origQty": "0.5",
            "price": "50000",
            "clientOrderId": "BTCUSDT_ENTRY_match1",
            "orderId": 11111,
            "time": int(datetime.now(timezone.utc).timestamp() * 1000),
        }]

        n = detect_orphan_exchange_open_orders(
            db_session, decrypt_func=identity_decrypt,
        )
        assert n == 0

    def test_open_order_archived_strategy_still_orphan(
        self,
        db_session,
        make_user,
        make_exchange_account,
        make_symbol,
        make_template,
        make_strategy,
        identity_decrypt,
        patched_binance_open_orders,
    ):
        """archived strategy 의 LIMIT 잔재 → orphan (사용자 #VICUSDT 패턴)."""
        from app.services.zombie_guardian import detect_orphan_exchange_open_orders

        u = make_user()
        ea = make_exchange_account(user=u)
        sym = make_symbol("VICUSDT")
        tpl = make_template()
        s = make_strategy(
            user=u, exchange_account=ea, symbol_obj=sym, template=tpl,
            symbol_str="VICUSDT", side="SHORT", status="STOPPED",
            current_position_qty=Decimal("0"),
        )
        s.is_archived = True
        s.archived_at = datetime.now(timezone.utc)
        # archived strategy 의 LIMIT order 가 DB 에 남아있음
        db_session.add(Order(
            strategy_instance_id=s.id, symbol="VICUSDT", side="SELL",
            position_side="SHORT", order_type="LIMIT", purpose="ENTRY",
            client_order_id="VICUSDT_ENTRY_old", status="NEW",
        ))
        db_session.commit()

        patched_binance_open_orders["open_orders"] = [{
            "symbol": "VICUSDT",
            "positionSide": "SHORT",
            "side": "SELL",
            "type": "LIMIT",
            "origQty": "397",
            "price": "0.0754",
            "clientOrderId": "VICUSDT_ENTRY_old",
            "orderId": 22222,
            "time": int(datetime.now(timezone.utc).timestamp() * 1000),
        }]

        n = detect_orphan_exchange_open_orders(
            db_session, decrypt_func=identity_decrypt,
        )
        # archived strategy 의 stale LIMIT → orphan
        assert n == 1
        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "ZOMBIE_ORPHAN_OPEN_ORDER")
        ).scalars().all()
        assert len(events) == 1
