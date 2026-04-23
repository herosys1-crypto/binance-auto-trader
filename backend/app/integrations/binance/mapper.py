"""User-stream event payload normalizers.

The user data stream sends events with compact single-letter field names
("o", "s", "q", etc.). Services downstream read human-friendly names, so we
normalize here. We keep the raw payload intact for audit/risk-event logging.
"""
from __future__ import annotations

from typing import Any


def _as_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v)
    return s or None


def map_order_update_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize an ORDER_TRADE_UPDATE event.

    Binance emits the order info under ``payload["o"]``.
    """
    order = payload.get("o") or {}
    return {
        "event_type": payload.get("e"),
        "event_time": payload.get("E"),
        "transaction_time": payload.get("T"),
        "client_order_id": _as_str(order.get("c")),
        "exchange_order_id": order.get("i"),
        "symbol": order.get("s"),
        "side": order.get("S"),
        "position_side": order.get("ps"),
        "order_type": order.get("o"),
        "time_in_force": order.get("f"),
        "orig_qty": _as_str(order.get("q")),
        "executed_qty": _as_str(order.get("z")),
        "price": _as_str(order.get("p")),
        "avg_price": _as_str(order.get("ap")),
        "stop_price": _as_str(order.get("sp")),
        "status": order.get("X"),
        "execution_type": order.get("x"),
        "last_filled_qty": _as_str(order.get("l")),
        "last_filled_price": _as_str(order.get("L")),
        "commission": _as_str(order.get("n")),
        "commission_asset": order.get("N"),
        "trade_id": order.get("t"),
        "realized_profit": _as_str(order.get("rp")),
        "raw": payload,
    }


def map_account_update_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize an ACCOUNT_UPDATE event.

    Binance emits balances & positions under ``payload["a"]``.
    Stream services need the raw position list in compact form for flexibility,
    so we pass ``positions`` through unchanged (still keyed by single-letters).
    """
    account = payload.get("a") or {}
    balances = account.get("B") or []
    positions = account.get("P") or []
    return {
        "event_type": payload.get("e"),
        "event_time": payload.get("E"),
        "transaction_time": payload.get("T"),
        "reason": account.get("m"),
        "balances": [
            {
                "asset": b.get("a"),
                "wallet_balance": _as_str(b.get("wb")),
                "cross_wallet_balance": _as_str(b.get("cw")),
                "balance_change": _as_str(b.get("bc")),
            }
            for b in balances
        ],
        "positions": positions,
        "raw": payload,
    }
