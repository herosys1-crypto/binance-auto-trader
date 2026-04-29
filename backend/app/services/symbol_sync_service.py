import logging
from decimal import Decimal
from sqlalchemy import select
from app.models.symbol import Symbol

logger = logging.getLogger(__name__)


class SymbolSyncService:
    def __init__(self, db, client) -> None:
        self.db = db
        self.client = client

    def sync(self) -> int:
        """Bug #9 fix (2026-04-29): row-level 에러 격리 + per-row commit.

        이전 버전은 모든 row 를 마지막에 한 번에 commit 했는데, 한 row 라도 schema
        제약(NOT NULL 등) 에 걸리면 트랜잭션 전체가 rollback 되어 0 개만 저장되는
        bug 가 있었음. 이제 row 단위 try/except 와 savepoint 기반 commit 으로
        실패한 row 는 건너뛰고 나머지는 정상 저장.
        """
        exchange_info = self.client.get_exchange_info()
        symbols = exchange_info.get("symbols", [])
        succeeded = 0
        failed = 0
        for item in symbols:
            symbol_name = item.get("symbol")
            if not symbol_name:
                continue
            # 필수 필드 누락 시 스킵 (NOT NULL 위반 사전 차단)
            if not item.get("baseAsset") or not item.get("quoteAsset") or not item.get("status"):
                failed += 1
                logger.warning("symbol_sync skip %s: missing required field(s)", symbol_name)
                continue
            try:
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
                existing = self.db.execute(
                    select(Symbol).where(Symbol.symbol == symbol_name)
                ).scalar_one_or_none()
                if existing is None:
                    s = Symbol(
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
                    self.db.add(s)
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
                # row 단위 commit — 일부 실패해도 나머지 보존
                self.db.commit()
                succeeded += 1
            except Exception as e:
                self.db.rollback()
                failed += 1
                logger.warning("symbol_sync failed %s: %s", symbol_name, e)
        logger.info("symbol_sync complete: succeeded=%d failed=%d", succeeded, failed)
        return succeeded
