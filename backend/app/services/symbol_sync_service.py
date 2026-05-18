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
        # 2026-05-18 (사용자 보고 — EDENUSDT 등 testnet 에 없는 심볼 잔존):
        # exchangeInfo 에 실제 존재하는 심볼명 집합. 아래 loop 후 이 집합에 없는
        # DB 심볼 (이전 sync 잔재 / mainnet↔testnet 차이) 은 DELISTED 로 마킹해
        # only_trading 필터에서 자동 제외 (UI dropdown + 전략생성에서 사라짐).
        live_symbol_names = {
            item.get("symbol") for item in symbols if item.get("symbol")
        }
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
        # ----- stale 심볼 비활성화 (exchangeInfo 에 없는 TRADING 심볼 → DELISTED) -----
        # 사용자 보고 (5-18): EDENUSDT 등 testnet 에 없는 심볼이 dropdown 에 다수.
        # 원인: 과거 sync (mainnet 연결/구 testnet) 잔재가 status=TRADING 영구 유지.
        # 매 sync 마다 「현재 exchangeInfo 에 없으면 DELISTED」 처리 → 일일 cron 이
        # 자동으로 stale 정리 (사용자가 원한 「하루 1회 검색·등록」 = 이미 03:00 cron,
        # 이 fix 로 등록뿐 아니라 정리까지 일관).
        delisted = 0
        if live_symbol_names:  # exchangeInfo fetch 실패(빈값) 시엔 전체 DELIST 방지
            try:
                stale_rows = self.db.execute(
                    select(Symbol).where(
                        Symbol.status == "TRADING",
                        Symbol.symbol.notin_(live_symbol_names),
                    )
                ).scalars().all()
                for s in stale_rows:
                    s.status = "DELISTED"
                    delisted += 1
                if delisted:
                    self.db.commit()
            except Exception as e:
                self.db.rollback()
                logger.warning("symbol_sync delist sweep 실패: %s", e)
        logger.info(
            "symbol_sync complete: succeeded=%d failed=%d delisted=%d",
            succeeded, failed, delisted,
        )
        return succeeded
