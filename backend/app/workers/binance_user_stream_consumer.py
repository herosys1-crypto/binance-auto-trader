from __future__ import annotations
import json, logging, time
import websocket
from app.core.database import SessionLocal
from app.integrations.binance.client import BinanceClient
from app.observability.metrics import user_stream_connected, user_stream_reconnect_total
from app.services.notification_service import NotificationService
from app.services.stream_service import StreamService
from app.utils.backoff import exponential_backoff

logger = logging.getLogger(__name__)

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
                ws_url = f"{self.ws_base_url}/ws/{self.listen_key}"
                logger.info("Starting Binance user stream consumer: %s", ws_url)
                self.ws = websocket.WebSocketApp(ws_url, on_open=self._on_open, on_message=self._on_message, on_error=self._on_error, on_close=self._on_close)
                self.ws.run_forever(ping_interval=20, ping_timeout=10)
                attempt = 0
            except Exception as e:
                attempt += 1
                delay = exponential_backoff(attempt, base=1.0, cap=60.0, jitter=True)
                user_stream_reconnect_total.inc()
                self._notify_system_error(f"User stream consumer crashed: {e}; retry in {delay:.2f}s")
                time.sleep(delay)

    def _on_open(self, ws) -> None:
        user_stream_connected.set(1)

    def _on_message(self, ws, message: str) -> None:
        data = json.loads(message)
        event_type = data.get("e")
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

    def _on_close(self, ws, close_status_code, close_msg) -> None:
        user_stream_connected.set(0)
        logger.warning("Binance user stream closed code=%s msg=%s", close_status_code, close_msg)

    def _notify_system_error(self, message: str) -> None:
        db = SessionLocal()
        try:
            NotificationService(db).send_system_alert(title="[시스템 경고] Binance User Stream", body=message)
        finally:
            db.close()
