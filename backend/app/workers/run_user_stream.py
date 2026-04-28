import logging
import threading
import time

from sqlalchemy import select

# logging.basicConfig 호출 (이게 없으면 logger.info 가 stdout 에 안 보임)
import app.core.logging  # noqa: F401
from app.core.crypto import decrypt_text
from app.core.database import SessionLocal
from app.core.redis_client import get_redis_client
from app.models.exchange_account import ExchangeAccount
from app.workers.binance_user_stream_consumer import BinanceUserStreamConsumer

logger = logging.getLogger(__name__)


def _heartbeat_loop() -> None:
    """별도 thread 에서 30초마다 Redis 에 heartbeat 갱신.

    consumer 의 _on_open / _on_message 가 호출 안 되어도 worker 가 살아있으면
    heartbeat 가 유지되도록 보장.
    """
    while True:
        try:
            client = get_redis_client()
            client.setex("health:user_stream:connected", 60, "1")
        except Exception as e:
            logger.warning("user-stream heartbeat thread 실패: %s", e)
        time.sleep(30)

# Binance USDⓈ-M Futures user data stream WebSocket endpoints.
#   mainnet : wss://fstream.binance.com
#   testnet : wss://stream.binancefuture.com
WS_BASE_URL_MAINNET = "wss://fstream.binance.com"
WS_BASE_URL_TESTNET = "wss://stream.binancefuture.com"


def main() -> None:
    db = SessionLocal()
    try:
        # 여러 active 계정이 있을 때 가장 작은 id (= 가장 먼저 등록된 계정) 사용.
        # MultipleResultsFound 방지 + 신규 계정이 들어와도 stream 안정성 유지.
        account = db.execute(
            select(ExchangeAccount)
            .where(
                ExchangeAccount.exchange_name == "binance",
                ExchangeAccount.is_active.is_(True),
            )
            .order_by(ExchangeAccount.id.asc())
            .limit(1)
        ).scalar_one_or_none()
        if not account:
            raise RuntimeError("No active Binance exchange account found")

        api_key = decrypt_text(account.api_key_enc)
        api_secret = decrypt_text(account.api_secret_enc)
        ws_base_url = WS_BASE_URL_TESTNET if account.is_testnet else WS_BASE_URL_MAINNET
        print(f"[user-stream] is_testnet={account.is_testnet}, ws_base_url={ws_base_url}")

        # heartbeat thread 시작 (consumer 와 별개로 worker 자체 생존 신호)
        hb_thread = threading.Thread(target=_heartbeat_loop, daemon=True, name="user-stream-heartbeat")
        hb_thread.start()
        logger.info("[user-stream] heartbeat thread started")

        consumer = BinanceUserStreamConsumer(
            api_key=api_key,
            api_secret=api_secret,
            is_testnet=account.is_testnet,
            ws_base_url=ws_base_url,
        )
        consumer.start()
    finally:
        db.close()


if __name__ == "__main__":
    main()
