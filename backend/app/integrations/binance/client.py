"""Binance USDⓈ-M Futures REST client.

Handles request signing (HMAC-SHA256), endpoint selection (mainnet/testnet),
and a consistent error surface (``BinanceAPIError``). Also emits Prometheus
metrics on every request.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any
from urllib.parse import urlencode

import requests

from app.core.config import settings
from app.observability.metrics import (
    binance_api_request_latency_seconds,
    binance_api_requests_total,
)

logger = logging.getLogger(__name__)


class BinanceAPIError(Exception):
    """Raised when the Binance API returns an error response or HTTP failure."""

    def __init__(self, message: str, *, status_code: int | None = None, code: int | None = None, payload: Any | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.payload = payload


# ═══════════════════════════════════════════════════════════════════════════
# 🚨 Fix 116 (2026-08-26): IP ban 전역 회로 차단기
#
# 418 은 「계정」이 아니라 「IP」 ban 이다 → 프로세스/컨테이너 전체가 멈춰야 한다.
# 1차 = 프로세스 메모리 (Redis 장애에도 동작, 가장 빠름)
# 2차 = Redis (컨테이너 여러 개 = scheduler / api / user-stream 공유)
# ═══════════════════════════════════════════════════════════════════════════
_IP_BAN_REDIS_KEY = "api_backoff:ip:ban_until_ms"
_ip_ban_until_ms_local: int = 0          # 프로세스 로컬 캐시
_ip_ban_redis_checked_at: float = 0.0    # Redis 재확인 쓰로틀 (초)
_IP_BAN_REDIS_RECHECK_SEC = 5.0

_BAN_UNTIL_RE = __import__("re").compile(r"banned\s+until\s+(\d{13})", __import__("re").IGNORECASE)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _ip_ban_remaining_ms() -> int:
    """남은 IP ban 시간(ms). 0 이면 ban 아님."""
    global _ip_ban_until_ms_local, _ip_ban_redis_checked_at
    now = _now_ms()
    if _ip_ban_until_ms_local > now:
        return _ip_ban_until_ms_local - now

    # 로컬은 풀렸지만 다른 컨테이너가 ban 을 봤을 수 있다 → Redis 확인 (쓰로틀)
    mono = time.monotonic()
    if mono - _ip_ban_redis_checked_at < _IP_BAN_REDIS_RECHECK_SEC:
        return 0
    _ip_ban_redis_checked_at = mono
    try:
        from app.core.redis_client import get_redis_client
        raw = get_redis_client().get(_IP_BAN_REDIS_KEY)
        if raw:
            until = int(raw.decode() if isinstance(raw, bytes) else raw)
            if until > now:
                _ip_ban_until_ms_local = until
                return until - now
    except Exception:
        # Redis 장애 = 로컬 캐시만으로 동작 (fail-open, 기존 흐름 유지).
        # 단 재확인을 60s 뒤로 밀어 매 5초 연결 타임아웃으로 느려지는 것을 방지.
        _ip_ban_redis_checked_at = mono + 60.0
    return 0


def _set_ip_ban(until_ms: int, *, source: str = "") -> None:
    """IP ban 마킹 (로컬 + Redis). 더 늦은 만료로만 갱신."""
    global _ip_ban_until_ms_local
    now = _now_ms()
    if until_ms <= now:
        return
    if until_ms > _ip_ban_until_ms_local:
        _ip_ban_until_ms_local = until_ms
        logger.error(
            "[Fix116] 🚨 IP ban 감지 — 모든 REST 호출 로컬 차단! 만료까지 %ds (%s)",
            (until_ms - now) // 1000, source,
        )
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        raw = r.get(_IP_BAN_REDIS_KEY)
        cur = int(raw.decode() if isinstance(raw, bytes) else raw) if raw else 0
        if until_ms > cur:
            r.setex(_IP_BAN_REDIS_KEY, max(1, (until_ms - now) // 1000 + 5), str(until_ms))
    except Exception:
        pass


def _mark_ip_ban_from_response(response: "requests.Response") -> None:
    """418/429 응답에서 「banned until <ms>」 추출 → 전역 마킹.

    명시 시각이 없으면 보수적으로 60초.
    """
    try:
        text = response.text or ""
    except Exception:
        text = ""
    m = _BAN_UNTIL_RE.search(text)
    if m:
        _set_ip_ban(int(m.group(1)), source=f"status={response.status_code} explicit")
    else:
        _set_ip_ban(_now_ms() + 60_000, source=f"status={response.status_code} default60s")


def get_ip_ban_remaining_sec() -> int:
    """운영/진단용 — 남은 IP ban 초."""
    return _ip_ban_remaining_ms() // 1000


def clear_ip_ban() -> None:
    """운영자 강제 해제 (실 ban 중 사용 금지 — ban 이 연장된다!)."""
    global _ip_ban_until_ms_local
    _ip_ban_until_ms_local = 0
    try:
        from app.core.redis_client import get_redis_client
        get_redis_client().delete(_IP_BAN_REDIS_KEY)
    except Exception:
        pass


class BinanceClient:
    """Thin but complete REST client for the USDⓈ-M Futures API."""

    # recvWindow: 요청 타임스탬프가 서버 시간과 최대 이만큼 어긋나도 허용.
    # Docker Desktop on Windows 환경에서 VM 시계가 드리프트하는 경우 대비 30초로 넉넉히.
    # 보안상 너무 크게 두면 replay 공격 창이 커지므로 운영에선 5000 권장.
    RECV_WINDOW_MS = 30000
    DEFAULT_TIMEOUT_SECONDS = 10

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        is_testnet: bool = False,
        base_url: str | None = None,
        session: requests.Session | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.is_testnet = is_testnet
        if base_url:
            self.base_url = base_url.rstrip("/")
        else:
            self.base_url = (
                settings.binance_futures_testnet_base_url if is_testnet else settings.binance_futures_base_url
            ).rstrip("/")
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds or self.DEFAULT_TIMEOUT_SECONDS

    # ------------------------------------------------------------------
    # Public REST endpoints
    # ------------------------------------------------------------------
    def get_exchange_info(self) -> dict[str, Any]:
        return self._request("GET", "/fapi/v1/exchangeInfo", signed=False)

    def get_server_time(self) -> dict[str, Any]:
        return self._request("GET", "/fapi/v1/time", signed=False)

    def ping(self) -> dict[str, Any]:
        return self._request("GET", "/fapi/v1/ping", signed=False)

    def get_klines(
        self, *, symbol: str, interval: str = "1d", limit: int = 30
    ) -> list[list[Any]]:
        """Binance Futures /fapi/v1/klines — historical candle 데이터.

        반환 포맷 (Binance 표준):
          [[open_time, open, high, low, close, volume, close_time, ...], ...]
          close_time 후 ignore. interval 지원: 1m/5m/15m/1h/4h/1d/1w/1M 등.

        2026-05-06 (사용자 요청 — 변동률 순위 기능):
          period 별 가격 변화율 = (close[-1] - close[0]) / close[0] × 100
          calling: get_klines(symbol="BTCUSDT", interval="1d", limit=8) → 7일 변동률 계산.
        """
        params = {"symbol": symbol.upper(), "interval": interval, "limit": int(limit)}
        return self._request("GET", "/fapi/v1/klines", signed=False, params=params)

    def get_24hr_ticker(self, symbol: str | None = None) -> list[dict[str, Any]] | dict[str, Any]:
        """Binance Futures /fapi/v1/ticker/24hr — 24h 변동률 (priceChangePercent 등).

        symbol=None 이면 모든 심볼 반환 (list).
        """
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol.upper()
        return self._request("GET", "/fapi/v1/ticker/24hr", signed=False, params=params)

    # ------------------------------------------------------------------
    # Account / position
    # ------------------------------------------------------------------
    def get_account(self) -> dict[str, Any]:
        return self._request("GET", "/fapi/v2/account", signed=True)

    def get_balance(self) -> list[dict[str, Any]]:
        return self._request("GET", "/fapi/v2/balance", signed=True)

    def get_position_risk(self, symbol: str | None = None) -> list[dict[str, Any]] | dict[str, Any]:
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        return self._request("GET", "/fapi/v2/positionRisk", params=params, signed=True)

    def change_leverage(self, *, symbol: str, leverage: int) -> dict[str, Any]:
        return self._request(
            "POST",
            "/fapi/v1/leverage",
            params={"symbol": symbol, "leverage": leverage},
            signed=True,
        )

    def change_margin_type(self, *, symbol: str, margin_type: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/fapi/v1/marginType",
            params={"symbol": symbol, "marginType": margin_type},
            signed=True,
        )

    def change_position_mode(self, *, dual_side_position: bool) -> dict[str, Any]:
        return self._request(
            "POST",
            "/fapi/v1/positionSide/dual",
            params={"dualSidePosition": "true" if dual_side_position else "false"},
            signed=True,
        )

    def add_position_margin(
        self,
        *,
        symbol: str,
        position_side: str,
        amount: str,
        margin_type: int = 1,
    ) -> dict[str, Any]:
        """ISOLATED 마진 모드 포지션에 증거금 추가/감소.

        Binance Futures: **POST /fapi/v1/positionMargin** (사용자 #102 사례 fix 2026-05-06):
          이전 path `/fapi/v1/positionMargin/modify` 는 잘못 — Binance 가 -5000
          ("Path is invalid") 응답. 공식 endpoint 는 `/positionMargin` (no /modify).

        - margin_type=1 → 증거금 추가 (add)
        - margin_type=2 → 증거금 감소 (reduce)
        - position_side: hedge mode 시 LONG/SHORT, one-way 시 BOTH
        - **CROSS 모드 포지션은 -4046 에러 ("No need to change margin type")** 비슷한 거절.
          호출자가 사전에 isolated 인지 확인하거나 거래소 응답 에러로 처리.
        """
        return self._request(
            "POST",
            "/fapi/v1/positionMargin",
            params={
                "symbol": symbol,
                "positionSide": position_side,
                "amount": amount,
                "type": margin_type,
            },
            signed=True,
        )

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------
    def place_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/fapi/v1/order", params=payload, signed=True)

    def get_order(
        self,
        *,
        symbol: str,
        order_id: int | None = None,
        orig_client_order_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"symbol": symbol}
        if order_id is not None:
            params["orderId"] = order_id
        if orig_client_order_id is not None:
            params["origClientOrderId"] = orig_client_order_id
        return self._request("GET", "/fapi/v1/order", params=params, signed=True)

    def cancel_order(
        self,
        *,
        symbol: str,
        order_id: int | None = None,
        orig_client_order_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"symbol": symbol}
        if order_id is not None:
            params["orderId"] = order_id
        if orig_client_order_id is not None:
            params["origClientOrderId"] = orig_client_order_id
        return self._request("DELETE", "/fapi/v1/order", params=params, signed=True)

    def cancel_all_orders(self, *, symbol: str) -> dict[str, Any]:
        return self._request("DELETE", "/fapi/v1/allOpenOrders", params={"symbol": symbol}, signed=True)

    def list_open_orders(self, *, symbol: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        return self._request("GET", "/fapi/v1/openOrders", params=params, signed=True)

    # ------------------------------------------------------------------
    # User data stream
    # ------------------------------------------------------------------
    def start_user_stream(self) -> dict[str, Any]:
        return self._request("POST", "/fapi/v1/listenKey", signed=False, api_key_required=True)

    def keepalive_user_stream(self) -> dict[str, Any]:
        return self._request("PUT", "/fapi/v1/listenKey", signed=False, api_key_required=True)

    def close_user_stream(self) -> dict[str, Any]:
        return self._request("DELETE", "/fapi/v1/listenKey", signed=False, api_key_required=True)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _sign(self, query_string: str) -> str:
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        signed: bool = False,
        api_key_required: bool = False,
    ) -> Any:
        params = dict(params or {})
        url = f"{self.base_url}{path}"
        headers: dict[str, str] = {}

        if signed or api_key_required:
            headers["X-MBX-APIKEY"] = self.api_key

        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = self.RECV_WINDOW_MS
            query_string = urlencode(
                [(k, v) for k, v in params.items() if v is not None],
                doseq=True,
            )
            signature = self._sign(query_string)
            params["signature"] = signature

        # ══════════════════════════════════════════════════════════════════
        # 🚨 Fix 116 (2026-08-26): IP ban 전역 회로 차단기 (헌법 6 단일 진실)
        #
        # 사장님 실측 사고: IP(159.65.137.250) 가 418 ban 상태인데도
        #   peak_break_reversal 이 2초에 18번 호출 → 매 요청이 ban 을 연장!
        #   06:08:43 → 06:28:43 → 06:30:44 → 06:34:47 (계속 밀림)
        #   Binance 는 ban 기간의 요청도 카운트해서 ban 을 연장/승격한다.
        #
        # 왜 워커별 가드로는 못 막나:
        #   워커들은 루프 「시작 전」에 한 번만 is_account_banned() 를 본다.
        #   루프 도중 ban 이 걸리면 33개 심볼을 끝까지 다 두드린다.
        #   (_get_15m_high 처럼 418 예외를 삼키고 None 반환 = 다음 심볼로 진행!)
        #   → 워커 20개를 개별 수정하는 대신 「네트워크 나가기 직전」 한 곳에서 차단.
        #
        # 418 은 계정이 아니라 「IP」 ban 이므로 전역 키를 쓴다.
        # ══════════════════════════════════════════════════════════════════
        _ban_left = _ip_ban_remaining_ms()
        if _ban_left > 0:
            binance_api_requests_total.labels(
                endpoint=path, method=method, status="ip_banned_skip",
            ).inc()
            raise BinanceAPIError(
                f"Binance API error: status=418, code=-1003, "
                f"msg=IP ban active — request suppressed locally "
                f"({_ban_left // 1000}s left). Fix116 circuit breaker.",
                status_code=418,
                code=-1003,
            )

        start = time.perf_counter()
        status_label = "error"
        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params if method in {"GET", "DELETE"} else None,
                data=params if method in {"POST", "PUT"} else None,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            status_label = str(response.status_code)
            if response.status_code >= 400:
                # Fix 116: 418/429 = IP ban → 전역 마킹 (다음 요청부터 네트워크 X)
                if response.status_code in (418, 429):
                    _mark_ip_ban_from_response(response)
                self._raise_for_error(response)
            if not response.content:
                return {}
            return response.json()
        except requests.RequestException as e:
            logger.warning("Binance request error: method=%s path=%s error=%s", method, path, e)
            raise BinanceAPIError(f"network error: {e}") from e
        finally:
            elapsed = time.perf_counter() - start
            binance_api_requests_total.labels(endpoint=path, method=method, status=status_label).inc()
            binance_api_request_latency_seconds.labels(endpoint=path, method=method).observe(elapsed)

    @staticmethod
    def _raise_for_error(response: requests.Response) -> None:
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}
        message = payload.get("msg") if isinstance(payload, dict) else None
        code = payload.get("code") if isinstance(payload, dict) else None
        raise BinanceAPIError(
            f"Binance API error: status={response.status_code}, code={code}, msg={message}",
            status_code=response.status_code,
            code=code,
            payload=payload,
        )
