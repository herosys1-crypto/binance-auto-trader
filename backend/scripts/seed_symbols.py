"""Binance USDⓈ-M futures exchangeInfo 공개 API 로 symbols 테이블 채우기.

API 키가 필요 없습니다. Binance `/fapi/v1/exchangeInfo` 는 unsigned public endpoint.

사용 예:
    # 전체 심볼 동기화 (수백 개)
    python scripts/seed_symbols.py

    # 특정 심볼만
    python scripts/seed_symbols.py --symbol BTCUSDT --symbol ETHUSDT

    # testnet 의 exchangeInfo 를 쓰고 싶다면
    python scripts/seed_symbols.py --testnet --symbol BTCUSDT
"""
from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from decimal import Decimal  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.integrations.binance.client import BinanceClient  # noqa: E402
from app.models.symbol import Symbol  # noqa: E402


def _upsert_symbol(db, item: dict) -> str:
    symbol_name = item.get("symbol")
    if not symbol_name:
        return "skip:no_name"

    tick_size = step_size = min_qty = min_notional = None
    for f in item.get("filters", []):
        ft = f.get("filterType")
        if ft == "PRICE_FILTER":
            tick_size = Decimal(str(f.get("tickSize", "0")))
        elif ft == "LOT_SIZE":
            step_size = Decimal(str(f.get("stepSize", "0")))
            min_qty = Decimal(str(f.get("minQty", "0")))
        elif ft == "MIN_NOTIONAL":
            min_notional = Decimal(str(f.get("notional", "0")))

    existing = db.execute(select(Symbol).where(Symbol.symbol == symbol_name)).scalar_one_or_none()
    if existing is None:
        db.add(
            Symbol(
                symbol=symbol_name,
                base_asset=item.get("baseAsset"),
                quote_asset=item.get("quoteAsset"),
                contract_type=item.get("contractType"),
                status=item.get("status"),
                price_precision=item.get("pricePrecision"),
                quantity_precision=item.get("quantityPrecision"),
                tick_size=tick_size,
                step_size=step_size,
                min_qty=min_qty,
                min_notional=min_notional,
                raw_exchange_info=item,
            )
        )
        return "inserted"
    else:
        existing.base_asset = item.get("baseAsset")
        existing.quote_asset = item.get("quoteAsset")
        existing.contract_type = item.get("contractType")
        existing.status = item.get("status")
        existing.price_precision = item.get("pricePrecision")
        existing.quantity_precision = item.get("quantityPrecision")
        existing.tick_size = tick_size
        existing.step_size = step_size
        existing.min_qty = min_qty
        existing.min_notional = min_notional
        existing.raw_exchange_info = item
        return "updated"


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed symbols table from Binance exchangeInfo")
    parser.add_argument(
        "--symbol",
        action="append",
        default=None,
        help="Restrict sync to these symbols (repeatable). If omitted, all symbols are synced.",
    )
    parser.add_argument("--testnet", action="store_true", help="Use testnet exchangeInfo endpoint")
    args = parser.parse_args()

    # API 키가 필요 없어서 빈 문자열로 client 생성 — unsigned call 만 사용
    client = BinanceClient(api_key="", api_secret="", is_testnet=args.testnet)
    print(f"[seed_symbols] fetching exchangeInfo from {client.base_url} ...")
    exchange_info = client.get_exchange_info()
    all_items = exchange_info.get("symbols", [])
    print(f"[seed_symbols] {len(all_items)} symbols received")

    if args.symbol:
        wanted = {s.upper() for s in args.symbol}
        items = [it for it in all_items if it.get("symbol", "").upper() in wanted]
        missing = wanted - {it.get("symbol", "").upper() for it in items}
        if missing:
            print(f"[seed_symbols] WARN not found in exchangeInfo: {', '.join(sorted(missing))}")
    else:
        items = all_items

    db = SessionLocal()
    try:
        inserted = 0
        updated = 0
        for item in items:
            result = _upsert_symbol(db, item)
            if result == "inserted":
                inserted += 1
            elif result == "updated":
                updated += 1
        db.commit()
        print(f"[seed_symbols] done. inserted={inserted}, updated={updated}, total processed={len(items)}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
