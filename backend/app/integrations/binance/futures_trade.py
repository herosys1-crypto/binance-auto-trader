"""High-level trade helpers built on top of ``BinanceClient``.

``BinanceFuturesTradeClient`` is a thin convenience wrapper so that services
don't have to assemble the raw order payload every time. The underlying REST
call is still routed through the execution adapter layer (see
``execution/plain_order_adapter.py``) so that algo-order routing can be added
later without touching the service layer.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.integrations.binance.client import BinanceClient


class BinanceFuturesTradeClient:
    def __init__(self, client: BinanceClient) -> None:
        self.client = client

    # ------------------------------------------------------------------
    # Market orders
    # ------------------------------------------------------------------
    def place_market_order(
        self,
        *,
        symbol: str,
        side: str,
        position_side: str,
        quantity: Decimal,
        new_client_order_id: str,
        reduce_only: bool | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "positionSide": position_side,
            "type": "MARKET",
            "quantity": str(quantity),
            "newClientOrderId": new_client_order_id,
        }
        if reduce_only is not None:
            payload["reduceOnly"] = "true" if reduce_only else "false"
        return self.client.place_order(payload)

    # ------------------------------------------------------------------
    # Limit orders
    # ------------------------------------------------------------------
    def place_limit_order(
        self,
        *,
        symbol: str,
        side: str,
        position_side: str,
        quantity: Decimal,
        price: Decimal,
        new_client_order_id: str,
        time_in_force: str = "GTC",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "positionSide": position_side,
            "type": "LIMIT",
            "quantity": str(quantity),
            "price": str(price),
            "timeInForce": time_in_force,
            "newClientOrderId": new_client_order_id,
        }
        return self.client.place_order(payload)

    # ------------------------------------------------------------------
    # Stop / Take-profit orders (plain, non-algo)
    # ------------------------------------------------------------------
    def place_stop_market_order(
        self,
        *,
        symbol: str,
        side: str,
        position_side: str,
        stop_price: Decimal,
        quantity: Decimal | None = None,
        close_position: bool = False,
        new_client_order_id: str,
        working_type: str = "MARK_PRICE",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "positionSide": position_side,
            "type": "STOP_MARKET",
            "stopPrice": str(stop_price),
            "workingType": working_type,
            "newClientOrderId": new_client_order_id,
        }
        if close_position:
            payload["closePosition"] = "true"
        elif quantity is not None:
            payload["quantity"] = str(quantity)
        return self.client.place_order(payload)

    def place_take_profit_market_order(
        self,
        *,
        symbol: str,
        side: str,
        position_side: str,
        stop_price: Decimal,
        quantity: Decimal | None = None,
        close_position: bool = False,
        new_client_order_id: str,
        working_type: str = "MARK_PRICE",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "positionSide": position_side,
            "type": "TAKE_PROFIT_MARKET",
            "stopPrice": str(stop_price),
            "workingType": working_type,
            "newClientOrderId": new_client_order_id,
        }
        if close_position:
            payload["closePosition"] = "true"
        elif quantity is not None:
            payload["quantity"] = str(quantity)
        return self.client.place_order(payload)
