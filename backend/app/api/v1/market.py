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


@router.get("/ticker24h")
def ticker_24hr(
    symbol: str = Query(..., min_length=1, max_length=30),
    testnet: bool = Query(default=True),
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
    limit: int = Query(default=24, ge=1, le=500),
    testnet: bool = Query(default=True),
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
