"""시세 정보 프록시 API.

Binance Futures public 엔드포인트를 프록시한다.
운영자 대시보드에서 현재가 / 24h 통계 / 캔들 차트를 표시할 때 사용.
인증 불필요 (public 데이터).
"""
from __future__ import annotations

from typing import Any

import requests
from fastapi import APIRouter, HTTPException, Query, status

router = APIRouter(prefix="/market", tags=["market"])

MAINNET_BASE = "https://fapi.binance.com"
TESTNET_BASE = "https://testnet.binancefuture.com"


def _base_url(testnet: bool) -> str:
    return TESTNET_BASE if testnet else MAINNET_BASE


# 2026-05-04 (사용자 요청): 「💉 포지션 추가」 모달의 현재가 표시용 — 가벼운 단일 가격 endpoint.
@router.get("/ticker")
def ticker_price(
    symbol: str = Query(..., min_length=1, max_length=30),
    testnet: bool = Query(default=False),  # 2026-06-01 fix: testnet deprecated (Binance Demo 통합) — mainnet 으로 default 변경
) -> dict[str, Any]:
    """단일 가격 (lastPrice). 「💉 포지션 추가」 모달의 미리보기용."""
    try:
        r = requests.get(
            f"{_base_url(testnet)}/fapi/v1/ticker/price",
            params={"symbol": symbol.upper()},
            timeout=5,
        )
        r.raise_for_status()
        return r.json()  # {"symbol": "...", "price": "...", "time": ...}
    except requests.RequestException as e:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Binance ticker API error: {e}",
        ) from e


@router.get("/ticker24h")
def ticker_24hr(
    symbol: str = Query(..., min_length=1, max_length=30),
    testnet: bool = Query(default=False),  # 2026-06-01 fix: testnet deprecated — mainnet default
) -> dict[str, Any]:
    """24시간 통계 (마지막 가격 / 고저 / 변동률 / 거래량)."""
    try:
        r = requests.get(
            f"{_base_url(testnet)}/fapi/v1/ticker/24hr",
            params={"symbol": symbol.upper()},
            timeout=5,
        )
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Binance ticker API error: {e}",
        ) from e


@router.get("/klines")
def klines(
    symbol: str = Query(..., min_length=1, max_length=30),
    interval: str = Query(default="1h", description="1m/5m/15m/1h/4h/1d 등"),
    limit: int = Query(default=200, ge=1, le=1500),  # 🌟 2026-06-11 #22: 차트용 200 default + max 1500
    testnet: bool = Query(default=False),  # 2026-06-01 fix: testnet deprecated — mainnet default
) -> list[list[Any]]:
    """캔들(OHLCV) 데이터.

    각 캔들 = [open_time, open, high, low, close, volume, close_time, ...].
    프론트엔드는 close 만 사용해 라인 차트를 그린다.
    """
    try:
        r = requests.get(
            f"{_base_url(testnet)}/fapi/v1/klines",
            params={"symbol": symbol.upper(), "interval": interval, "limit": limit},
            timeout=5,
        )
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Binance klines API error: {e}",
        ) from e


# 🌟 2026-06-11 #22: Order Book = 사장님 시장 깊이!
@router.get("/depth")
def depth(
    symbol: str = Query(..., min_length=1, max_length=30),
    limit: int = Query(default=20, description="5/10/20/50/100/500/1000"),
    testnet: bool = Query(default=False),
) -> dict[str, Any]:
    """Order Book (= 매수/매도 호가) = 사장님 시장 깊이!

    응답: {"bids": [["7.93", "2000"], ...], "asks": [["7.95", "1000"], ...]}
    bids = 매수 (= 녹색) / asks = 매도 (= 적색)
    초기 fetch 후 = frontend = WebSocket wss://fstream.binance.com/ws/{symbol}@depth20 직접 연결!
    """
    if limit not in (5, 10, 20, 50, 100, 500, 1000):
        raise HTTPException(status_code=400, detail="limit must be 5/10/20/50/100/500/1000")
    try:
        r = requests.get(
            f"{_base_url(testnet)}/fapi/v1/depth",
            params={"symbol": symbol.upper(), "limit": limit},
            timeout=5,
        )
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Binance depth API error: {e}",
        ) from e
