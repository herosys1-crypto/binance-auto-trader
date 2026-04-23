"""Algo order adapter (stub).

Binance's dedicated algo-order endpoints (TWAP/VP etc.) have different
authorization and payload shapes. This stub exists so ``ExecutionAdapterRouter``
can be constructed with both lanes; wire up real endpoints when algo routing
is actually needed.
"""
from __future__ import annotations

from typing import Any

from app.integrations.binance.client import BinanceClient
from app.observability.metrics import binance_algo_order_total


class AlgoOrderAdapter:
    SUPPORTED_TYPES = {"TWAP", "VP"}

    def __init__(self, client: BinanceClient) -> None:
        self.client = client

    def supports(self, order_type: str) -> bool:
        return order_type.upper() in self.SUPPORTED_TYPES

    def place_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        order_type = payload.get("type", "UNKNOWN")
        # Intentionally not implemented yet — raise a clear error so it's obvious
        # at runtime that algo routing has not been enabled.
        binance_algo_order_total.labels(order_type=order_type, status="rejected").inc()
        raise NotImplementedError(
            "Algo order routing is not enabled. "
            "Implement AlgoOrderAdapter.place_order when enabling algo orders."
        )
