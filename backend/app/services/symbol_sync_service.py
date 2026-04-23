from decimal import Decimal
from sqlalchemy import select
from app.models.symbol import Symbol

class SymbolSyncService:
    def __init__(self, db, client) -> None:
        self.db = db
        self.client = client

    def sync(self) -> int:
        exchange_info = self.client.get_exchange_info()
        symbols = exchange_info.get("symbols", [])
        updated_count = 0
        for item in symbols:
            symbol_name = item.get("symbol")
            if not symbol_name:
                continue
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
            symbol = self.db.execute(select(Symbol).where(Symbol.symbol == symbol_name)).scalar_one_or_none()
            if symbol is None:
                symbol = Symbol(symbol=symbol_name, base_asset=item.get("baseAsset"), quote_asset=item.get("quoteAsset"), contract_type=item.get("contractType"), status=item.get("status"), price_precision=item.get("pricePrecision"), quantity_precision=item.get("quantityPrecision"), tick_size=tick_size, step_size=step_size, min_qty=min_qty, min_notional=min_notional, raw_exchange_info=item)
                self.db.add(symbol)
            else:
                symbol.base_asset = item.get("baseAsset")
                symbol.quote_asset = item.get("quoteAsset")
                symbol.contract_type = item.get("contractType")
                symbol.status = item.get("status")
                symbol.price_precision = item.get("pricePrecision")
                symbol.quantity_precision = item.get("quantityPrecision")
                symbol.tick_size = tick_size
                symbol.step_size = step_size
                symbol.min_qty = min_qty
                symbol.min_notional = min_notional
                symbol.raw_exchange_info = item
            updated_count += 1
        self.db.commit()
        return updated_count
