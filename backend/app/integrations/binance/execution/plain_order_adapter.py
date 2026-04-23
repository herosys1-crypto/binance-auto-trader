"""Plain (non-algo) order adapter.

Routes LIMIT / MARKET / STOP_MARKET / TAKE_PROFIT_MARKET orders through the
regular ``/fapi/v1/order`` endpoint.
"""
from __future__ import annotations

from typing import Any

from app.integrations.binance.client import BinanceClient


class PlainOrderAdapter:
    SUPPORTED_TYPES = {
        "LIMIT",
        "MARKET",
        "STOP",
        "STOP_MARKET",
        "TAKE_PROFIT",
        "TAKE_PROFIT_MARKET",
        "TRAILING_STOP_MARKET",
    }

    def __init__(self, client: BinanceClient) -> None:
        self.client = client

    def supports(self, order_type: str) -> bool:
        return order_type.upper() in self.SUPPORTED_TYPES

    def place_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.place_order(payload)
