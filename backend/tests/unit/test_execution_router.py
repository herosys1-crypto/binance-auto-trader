"""ExecutionAdapterRouter 라우팅 로직 단위 테스트."""
from __future__ import annotations

import pytest

from app.integrations.binance.execution.router import ExecutionAdapterRouter


class FakeAdapter:
    def __init__(self, supported: set[str]) -> None:
        self._supported = {s.upper() for s in supported}
        self.placed: list[dict] = []

    def supports(self, order_type: str) -> bool:
        return order_type.upper() in self._supported

    def place_order(self, payload: dict) -> dict:
        self.placed.append(payload)
        return {"orderId": 1, "status": "NEW"}


class TestRoutingSelection:
    def test_routes_limit_to_plain(self) -> None:
        plain = FakeAdapter({"LIMIT", "MARKET"})
        algo = FakeAdapter({"TWAP"})
        router = ExecutionAdapterRouter(plain_adapter=plain, algo_adapter=algo)

        assert router.route_for_type("LIMIT") is plain
        assert router.route_for_type("MARKET") is plain

    def test_routes_twap_to_algo(self) -> None:
        plain = FakeAdapter({"LIMIT"})
        algo = FakeAdapter({"TWAP"})
        router = ExecutionAdapterRouter(plain_adapter=plain, algo_adapter=algo)

        assert router.route_for_type("TWAP") is algo

    def test_case_insensitive(self) -> None:
        plain = FakeAdapter({"LIMIT"})
        router = ExecutionAdapterRouter(plain_adapter=plain, algo_adapter=None)
        assert router.route_for_type("limit") is plain
        assert router.route_for_type("Limit") is plain

    def test_without_algo_adapter(self) -> None:
        plain = FakeAdapter({"LIMIT"})
        router = ExecutionAdapterRouter(plain_adapter=plain, algo_adapter=None)
        assert router.route_for_type("LIMIT") is plain

    def test_unsupported_type_raises(self) -> None:
        plain = FakeAdapter({"LIMIT"})
        router = ExecutionAdapterRouter(plain_adapter=plain, algo_adapter=None)
        with pytest.raises(ValueError, match="No adapter available"):
            router.route_for_type("UNKNOWN_TYPE")

    def test_empty_type_raises(self) -> None:
        plain = FakeAdapter({"LIMIT"})
        router = ExecutionAdapterRouter(plain_adapter=plain, algo_adapter=None)
        with pytest.raises(ValueError):
            router.route_for_type("")

    def test_algo_priority_over_plain_when_both_claim(self) -> None:
        """양쪽 다 지원한다고 할 때 algo 가 우선."""
        plain = FakeAdapter({"TWAP"})
        algo = FakeAdapter({"TWAP"})
        router = ExecutionAdapterRouter(plain_adapter=plain, algo_adapter=algo)
        assert router.route_for_type("TWAP") is algo
