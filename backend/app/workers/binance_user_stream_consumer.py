from __future__ import annotations
import json, logging, time
import websocket
from app.core.database import SessionLocal
from app.core.redis_client import get_redis_client
from app.core.sentry import capture_strategy_event
from app.integrations.binance.client import BinanceClient
from app.observability.metrics import user_stream_connected, user_stream_reconnect_total
from app.services.notification_service import NotificationService
from app.services.stream_service import StreamService
from app.utils.backoff import exponential_backoff

logger = logging.getLogger(__name__)

# Redis heartbeat 키 — API process 가 폴링해서 Prometheus gauge 갱신.
# TTL 60s — 60초 내 갱신 안 되면 자동 만료 → API 가 끊김으로 간주.
HEALTH_KEY_USER_STREAM = "health:user_stream:connected"
HEALTH_TTL_SECONDS = 60


def _set_user_stream_health(connected: bool) -> None:
    """Redis heartbeat 키 갱신. 실패 시 로그 남기되 stream 동작은 계속."""
    try:
        client = get_redis_client()
        if connected:
            client.setex(HEALTH_KEY_USER_STREAM, HEALTH_TTL_SECONDS, "1")
        else:
            client.delete(HEALTH_KEY_USER_STREAM)
    except Exception as e:
        # silent fail 안 함 — heartbeat 실패는 모니터링상 중요하므로 로그 남김
        logger.warning("user-stream heartbeat redis 실패: %s", e)

class BinanceUserStreamConsumer:
    def __init__(self, *, api_key: str, api_secret: str, is_testnet: bool, ws_base_url: str, on_disconnect_sleep_seconds: int = 5) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.is_testnet = is_testnet
        self.ws_base_url = ws_base_url.rstrip("/")
        self.on_disconnect_sleep_seconds = on_disconnect_sleep_seconds
        self.client = BinanceClient(api_key=api_key, api_secret=api_secret, is_testnet=is_testnet)
        self.listen_key = None
        self.ws = None

    def start(self) -> None:
        attempt = 0
        while True:
            try:
                self.listen_key = self.client.start_user_stream()["listenKey"]
                # listen key 발급 성공 = Binance API 인증 + 네트워크 정상.
                # _on_open 호출 전에도 heartbeat 한 번 set (이중 안전장치).
                _set_user_stream_health(True)
                # 2026-06-01 Critical fix: Binance 가 2026-04-23 부터 레거시 /ws/<listenKey>
                # 경로를 차단함 (WebSocket Change Notice). 신 endpoint /private/ws/<listenKey>
                # 필수. 차단 후엔 연결은 되지만 ORDER_TRADE_UPDATE / ACCOUNT_UPDATE 등
                # private event 가 단 한 건도 수신되지 않음 → mainnet Sub-account 운영의
                # 모든 chain 문제 (PENDING 머무름, realized_pnl 0, 통계 부정확 등) 의 root cause.
                #
                # 2026-06-03 보강 (binance_changelog_monitor 자동 감지 + 사장님 요청):
                # Binance WebSocket Change Notice 페이지 update 감지 → 최신 권장 형식 채택.
                # path 형식 (/private/ws/<key>) 도 계속 작동하지만, Binance 가 query string
                # 형식 (/private/ws?listenKey=<key>) 을 신규 표준으로 제시 → 사전 마이그레이션.
                # events 필터는 미사용 (모든 이벤트 수신 — listenKeyExpired 등 critical 누락 방지).
                ws_url = f"{self.ws_base_url}/private/ws?listenKey={self.listen_key}"
                logger.info("Starting Binance user stream consumer: %s", ws_url)
                self.ws = websocket.WebSocketApp(ws_url, on_open=self._on_open, on_message=self._on_message, on_error=self._on_error, on_close=self._on_close)
                self.ws.run_forever(ping_interval=20, ping_timeout=10)
                attempt = 0
            except Exception as e:
                attempt += 1
                delay = exponential_backoff(attempt, base=1.0, cap=60.0, jitter=True)
                user_stream_reconnect_total.inc()
                # 재연결 대기 중에는 heartbeat 키 만료시켜 "끊김" 표시
                _set_user_stream_health(False)
                self._notify_system_error(f"User stream consumer crashed: {e}; retry in {delay:.2f}s")
                # Sentry: 첫 reconnect 는 일시적 네트워크 이슈일 수 있으니 warning,
                # 5회 이상 연속이면 백엔드 장애 신호 → error.
                capture_strategy_event(
                    f"Binance user stream crashed (attempt {attempt})",
                    level="warning" if attempt < 5 else "error",
                    error=e,
                    extras={"attempt": attempt, "retry_delay_s": round(delay, 2)},
                    tags={"event_type": "USER_STREAM_CRASH", "is_testnet": str(self.is_testnet)},
                )
                time.sleep(delay)

    def _on_open(self, ws) -> None:
        user_stream_connected.set(1)
        _set_user_stream_health(True)

    def _on_message(self, ws, message: str) -> None:
        # 메시지 수신할 때마다 heartbeat 갱신 (60s TTL refresh)
        _set_user_stream_health(True)
        data = json.loads(message)
        event_type = data.get("e")
        # 2026-06-01 fix: endpoint_health_monitor 가 ORDER 이벤트 빈도 검사용 카운터 증가.
        # 12시간 동안 ORDER 이벤트 0건 + 활성 strategy >0 이면 Telegram critical 알림.
        if event_type == "ORDER_TRADE_UPDATE":
            try:
                from app.core.redis_client import get_redis_client
                get_redis_client().incr("metrics:user_stream:order_events_total")
            except Exception:
                pass  # 카운터 실패해도 거래 흐름 영향 X
        db = SessionLocal()
        try:
            service = StreamService(db)
            if event_type == "ORDER_TRADE_UPDATE":
                service.handle_order_trade_update(data)
            elif event_type == "ACCOUNT_UPDATE":
                service.handle_account_update(data)
            elif event_type == "listenKeyExpired":
                service.handle_listen_key_expired(data)
                self._notify_system_error("listenKeyExpired received; reconnect required")
                ws.close()
        finally:
            db.close()

    def _on_error(self, ws, error) -> None:
        logger.error("Binance user stream error: %s", error)
        # WebSocket 콜백 에러 (예: 인증 실패, listenKeyExpired race) — Sentry 캡처.
        # error 가 Exception 객체인 경우와 문자열인 경우 모두 처리.
        err_obj = error if isinstance(error, BaseException) else None
        capture_strategy_event(
            f"Binance user stream WS error: {error}",
            level="error",
            error=err_obj,
            tags={"event_type": "USER_STREAM_WS_ERROR", "is_testnet": str(self.is_testnet)},
        )

    def _on_close(self, ws, close_status_code, close_msg) -> None:
        user_stream_connected.set(0)
        _set_user_stream_health(False)
        logger.warning("Binance user stream closed code=%s msg=%s", close_status_code, close_msg)

    def _notify_system_error(self, message: str) -> None:
        db = SessionLocal()
        try:
            NotificationService(db).send_system_alert(title="[시스템 경고] Binance User Stream", body=message)
        finally:
            db.close()
