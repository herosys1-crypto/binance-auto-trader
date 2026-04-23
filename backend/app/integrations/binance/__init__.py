"""Binance Futures integration package.

Public entrypoints:
    - BinanceClient:              REST client (signed + unsigned endpoints)
    - BinanceFuturesTradeClient:  Order-placement convenience wrapper
    - ExecutionAdapterRouter:     Routes Plain vs Algo order payloads
"""
from app.integrations.binance.client import BinanceClient, BinanceAPIError  # noqa: F401
from app.integrations.binance.futures_trade import BinanceFuturesTradeClient  # noqa: F401
from app.integrations.binance.mapper import (  # noqa: F401
    map_order_update_event,
    map_account_update_event,
)
