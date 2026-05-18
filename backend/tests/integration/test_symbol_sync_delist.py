"""SymbolSyncService — stale 심볼 DELISTED sweep 회귀.

배경 (사용자 보고 2026-05-18):
- EDENUSDT 등 testnet exchangeInfo 에 없는 심볼이 dropdown 에 다수 잔존
- 원인: 과거 sync (mainnet 연결/구 testnet) 잔재가 status=TRADING 영구 유지
- symbol_sync 가 add/update 만 하고 사라진 심볼 비활성화를 안 했음

Fix: 매 sync 마다 현재 exchangeInfo 에 없는 TRADING 심볼 → DELISTED.
일일 03:00 cron 이 자동으로 stale 정리 (사용자가 원한 「하루 1회 검색·등록」).
"""
from __future__ import annotations

from sqlalchemy import select

from app.models.symbol import Symbol
from app.services.symbol_sync_service import SymbolSyncService


class _FakeClient:
    def __init__(self, exchange_info: dict) -> None:
        self._info = exchange_info

    def get_exchange_info(self) -> dict:
        return self._info


def _sym_item(name: str, status: str = "TRADING") -> dict:
    return {
        "symbol": name,
        "baseAsset": name.replace("USDT", ""),
        "quoteAsset": "USDT",
        "contractType": "PERPETUAL",
        "status": status,
        "pricePrecision": 2,
        "quantityPrecision": 3,
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
            {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
            {"filterType": "MIN_NOTIONAL", "notional": "5"},
        ],
    }


def _status(db_session, name: str) -> str | None:
    row = db_session.execute(
        select(Symbol).where(Symbol.symbol == name)
    ).scalar_one_or_none()
    return row.status if row else None


class TestSymbolSyncDelistSweep:
    def test_stale_symbol_marked_delisted(self, db_session, make_symbol):
        """exchangeInfo 에 없는 기존 TRADING 심볼 → DELISTED 로 sweep."""
        make_symbol("BTCUSDT")            # 거래소에 살아있음
        make_symbol("EDENUSDT")           # testnet 에 없음 (stale, 사용자 보고 사례)

        client = _FakeClient({"symbols": [_sym_item("BTCUSDT")]})
        SymbolSyncService(db_session, client).sync()

        assert _status(db_session, "BTCUSDT") == "TRADING", "거래소에 있으면 유지"
        assert _status(db_session, "EDENUSDT") == "DELISTED", \
            "exchangeInfo 에 없으면 DELISTED — only_trading 필터에서 제외"

    def test_new_symbol_registered_and_no_false_delist(self, db_session, make_symbol):
        """신규 심볼 등록 + 살아있는 심볼은 DELIST 안 됨."""
        make_symbol("ETHUSDT")

        client = _FakeClient({"symbols": [_sym_item("ETHUSDT"), _sym_item("SOLUSDT")]})
        n = SymbolSyncService(db_session, client).sync()
        assert n == 2

        assert _status(db_session, "ETHUSDT") == "TRADING"
        assert _status(db_session, "SOLUSDT") == "TRADING"

    def test_empty_exchange_info_does_not_delist_everything(self, db_session, make_symbol):
        """exchangeInfo fetch 실패(빈 symbols) 시 전체 DELIST 방지 (안전장치)."""
        make_symbol("BTCUSDT")

        client = _FakeClient({"symbols": []})
        SymbolSyncService(db_session, client).sync()

        assert _status(db_session, "BTCUSDT") == "TRADING", \
            "빈 exchangeInfo 면 기존 심볼 보존 (대량 오삭제 방지)"

    def test_already_delisted_stays_delisted(self, db_session, make_symbol):
        """이미 DELISTED 인 심볼은 재sweep 대상 아님 (idempotent — TRADING 만 sweep)."""
        make_symbol("OLDUSDT", status="DELISTED")

        client = _FakeClient({"symbols": [_sym_item("BTCUSDT")]})
        SymbolSyncService(db_session, client).sync()

        assert _status(db_session, "OLDUSDT") == "DELISTED"
        assert _status(db_session, "BTCUSDT") == "TRADING"
