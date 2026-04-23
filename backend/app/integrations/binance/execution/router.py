"""Execution adapter router.

Selects the correct adapter (plain vs algo) for a given order type so the
service layer can stay agnostic to exchange routing details.
"""
from __future__ import annotations

from typing import Any, Protocol


class OrderAdapter(Protocol):
    def supports(self, order_type: str) -> bool: ...
    def place_order(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class ExecutionAdapterRouter:
    def __init__(self, *, plain_adapter: OrderAdapter, algo_adapter: OrderAdapter | None = None) -> None:
        self.plain_adapter = plain_adapter
        self.algo_adapter = algo_adapter

    def route_for_type(self, order_type: str) -> OrderAdapter:
        order_type = (order_type or "").upper()
        if self.algo_adapter is not None and self.algo_adapter.supports(order_type):
            return self.algo_adapter
        if self.plain_adapter.supports(order_type):
            return self.plain_adapter
        raise ValueError(f"No adapter available for order_type={order_type}")
