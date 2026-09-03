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


# ═══════════════════════════════════════════════════════════════════════════
# 🚨 2026-09-03: 이 파일의 `requests.get` 은 Fix 116 회로 차단기를 안 탄다
#
# 이 라우터는 `BinanceClient._request` 를 거치지 않고 `requests.get` 을 직접 부른다.
# 그래서 다음 두 안전장치를 **통째로 우회**한다:
#   · Fix 116 IP ban 전역 회로 차단기 (client.py:652)
#   · Fix 124 weight 거버너 / Fix 118 호출량 계측 (client.py:667)
#
# 2026-08-26 사고의 핵심은 「**ban 중에 보낸 요청이 ban 을 연장한다**」였다
# (06:08 → 06:28 → 06:30 → 06:34 로 계속 밀렸다). 즉 ban 이 걸린 뒤에도
# 계속 두드리는 경로가 하나라도 있으면 수십 분짜리 전면 정지가 된다.
#
# 이 경로는 「사람이 보는 화면」이 부르는 것이라 워커보다 빈도가 낮지만,
# 선물거래 터미널(perp-terminal.html)처럼 **상시 열어 두는 화면**이 생기면서
# 심볼 전환·탭 복귀마다 klines/depth/ticker24h 3개가 같이 나간다.
#
# 전체를 BinanceClient 로 옮기지 않은 이유:
#   이 라우터는 index.html 등 기존 화면 여러 곳이 이미 쓰고 있고, 응답을
#   Binance 원본 그대로 흘려보내는 계약이다. 옮기면 예외 타입·응답 형태가
#   바뀌어 기존 화면이 조용히 깨질 수 있다(헌법 = 기존 파일 최소 수정).
#
# 그래서 **ban 판정만** 공유한다. 캐시·거버너는 각 소비자가 이미 갖고 있지만
# 「ban 중에는 아무도 두드리지 않는다」는 것은 예외 없이 지켜져야 한다.
# ═══════════════════════════════════════════════════════════════════════════
def _guard_ip_ban() -> None:
    """IP ban 중이면 네트워크로 나가기 전에 끊는다 (ban 연장 되먹임 차단).

    503 + Retry-After 로 준다. 프런트는 이것을 「지금은 조회 불가」로 표시하면 되고,
    「값이 0」으로 오해할 여지가 없다.
    """
    try:
        from app.integrations.binance.client import get_ip_ban_remaining_sec
        left = get_ip_ban_remaining_sec()
    except Exception:      # 진단 함수 때문에 시세 화면이 죽으면 안 된다
        return
    if left > 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Binance IP 차단(418) 중입니다 — {left}초 후 자동 복구됩니다. "
                   f"지금 요청을 보내면 차단이 연장됩니다 (Fix 116).",
            headers={"Retry-After": str(max(1, left))},
        )


def _note_ip_ban(resp: "requests.Response") -> None:
    """418/429 응답을 **전역 ban 플래그에 반영**한다.

    🚨 이게 없으면 이 라우터가 ban 을 유발해도 아무도 모른다.
    `BinanceClient._request` 는 418/429 를 받으면 `_mark_ip_ban_from_response` 로
    전역 마킹해서 **모든 컨테이너의 다음 요청을 멈춘다**(Fix 116). 그런데 이 파일은
    그 경로를 안 타므로, ban 을 처음 맞는 곳이 여기라면 워커들은 계속 두드리게 된다.
    → ban 판정을 「읽기만」 하지 말고 「쓰기」도 같이 해야 회로 차단기가 완성된다.
    """
    try:
        if resp.status_code in (418, 429):
            from app.integrations.binance.client import _mark_ip_ban_from_response
            _mark_ip_ban_from_response(resp)
    except Exception:      # 진단이 시세 화면을 죽이면 안 된다
        pass


# 2026-05-04 (사용자 요청): 「💉 포지션 추가」 모달의 현재가 표시용 — 가벼운 단일 가격 endpoint.
@router.get("/ticker")
def ticker_price(
    symbol: str = Query(..., min_length=1, max_length=30),
    testnet: bool = Query(default=False),  # 2026-06-01 fix: testnet deprecated (Binance Demo 통합) — mainnet 으로 default 변경
) -> dict[str, Any]:
    """단일 가격 (lastPrice). 「💉 포지션 추가」 모달의 미리보기용."""
    _guard_ip_ban()      # 🚨 ban 중 요청은 ban 을 연장한다 (Fix 116)
    try:
        r = requests.get(
            f"{_base_url(testnet)}/fapi/v1/ticker/price",
            params={"symbol": symbol.upper()},
            timeout=5,
        )
        _note_ip_ban(r)          # 🚨 418/429 를 전역 회로 차단기에 알린다
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
    _guard_ip_ban()      # 🚨 ban 중 요청은 ban 을 연장한다 (Fix 116)
    try:
        r = requests.get(
            f"{_base_url(testnet)}/fapi/v1/ticker/24hr",
            params={"symbol": symbol.upper()},
            timeout=5,
        )
        _note_ip_ban(r)          # 🚨 418/429 를 전역 회로 차단기에 알린다
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
    _guard_ip_ban()      # 🚨 ban 중 요청은 ban 을 연장한다 (Fix 116)
    try:
        r = requests.get(
            f"{_base_url(testnet)}/fapi/v1/klines",
            params={"symbol": symbol.upper(), "interval": interval, "limit": limit},
            timeout=5,
        )
        _note_ip_ban(r)          # 🚨 418/429 를 전역 회로 차단기에 알린다
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
    _guard_ip_ban()      # 🚨 ban 중 요청은 ban 을 연장한다 (Fix 116)
    try:
        r = requests.get(
            f"{_base_url(testnet)}/fapi/v1/depth",
            params={"symbol": symbol.upper(), "limit": limit},
            timeout=5,
        )
        _note_ip_ban(r)          # 🚨 418/429 를 전역 회로 차단기에 알린다
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Binance depth API error: {e}",
        ) from e
