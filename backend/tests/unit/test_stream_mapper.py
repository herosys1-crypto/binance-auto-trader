"""User stream 이벤트 매퍼 단위 테스트."""
from __future__ import annotations

from app.integrations.binance.mapper import (
    map_account_update_event,
    map_order_update_event,
)


class TestOrderUpdateMapper:
    def _sample(self) -> dict:
        # Binance ORDER_TRADE_UPDATE 실사 payload 의 축약본
        return {
            "e": "ORDER_TRADE_UPDATE",
            "E": 1568879465651,
            "T": 1568879465650,
            "o": {
                "s": "BTCUSDT",
                "c": "my-client-order-01",
                "S": "BUY",
                "o": "LIMIT",
                "f": "GTC",
                "q": "0.001",
                "p": "50000",
                "ap": "0",
                "sp": "0",
                "x": "NEW",
                "X": "NEW",
                "i": 8389765543,
                "l": "0",
                "z": "0",
                "L": "0",
                "n": "0",
                "N": "USDT",
                "T": 1568879465650,
                "t": 0,
                "ps": "LONG",
                "rp": "0",
            },
        }

    def test_core_fields_extracted(self) -> None:
        out = map_order_update_event(self._sample())
        assert out["event_type"] == "ORDER_TRADE_UPDATE"
        assert out["symbol"] == "BTCUSDT"
        assert out["client_order_id"] == "my-client-order-01"
        assert out["exchange_order_id"] == 8389765543
        assert out["side"] == "BUY"
        assert out["position_side"] == "LONG"
        assert out["order_type"] == "LIMIT"
        assert out["status"] == "NEW"

    def test_numeric_fields_as_strings(self) -> None:
        out = map_order_update_event(self._sample())
        # 소수 정확도 손실 방지 위해 전부 str
        assert out["orig_qty"] == "0.001"
        assert out["executed_qty"] == "0"
        assert out["price"] == "50000"

    def test_raw_payload_preserved(self) -> None:
        payload = self._sample()
        out = map_order_update_event(payload)
        assert out["raw"] is payload

    def test_missing_order_wrapper_returns_none_fields(self) -> None:
        out = map_order_update_event({"e": "ORDER_TRADE_UPDATE"})
        assert out["event_type"] == "ORDER_TRADE_UPDATE"
        assert out["client_order_id"] is None
        assert out["symbol"] is None


class TestAccountUpdateMapper:
    def _sample(self) -> dict:
        return {
            "e": "ACCOUNT_UPDATE",
            "E": 1568879465651,
            "T": 1568879465650,
            "a": {
                "m": "ORDER",
                "B": [
                    {"a": "USDT", "wb": "100.0", "cw": "100.0", "bc": "0"},
                ],
                "P": [
                    {"s": "BTCUSDT", "pa": "0.001", "ep": "50000", "up": "0", "ps": "LONG"},
                ],
            },
        }

    def test_core_fields(self) -> None:
        out = map_account_update_event(self._sample())
        assert out["event_type"] == "ACCOUNT_UPDATE"
        assert out["reason"] == "ORDER"

    def test_balances_normalized(self) -> None:
        out = map_account_update_event(self._sample())
        assert out["balances"] == [
            {"asset": "USDT", "wallet_balance": "100.0", "cross_wallet_balance": "100.0", "balance_change": "0"}
        ]

    def test_positions_preserved_as_is(self) -> None:
        """stream_service 가 파싱 자유도를 갖기 위해 positions 는 원본 그대로."""
        out = map_account_update_event(self._sample())
        assert len(out["positions"]) == 1
        pos = out["positions"][0]
        assert pos["s"] == "BTCUSDT"
        assert pos["pa"] == "0.001"
        assert pos["ps"] == "LONG"

    def test_empty_payload_safe(self) -> None:
        out = map_account_update_event({"e": "ACCOUNT_UPDATE"})
        assert out["balances"] == []
        assert out["positions"] == []
