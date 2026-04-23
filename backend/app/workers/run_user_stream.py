from sqlalchemy import select
from app.core.crypto import decrypt_text
from app.core.database import SessionLocal
from app.models.exchange_account import ExchangeAccount
from app.workers.binance_user_stream_consumer import BinanceUserStreamConsumer

def main() -> None:
    db = SessionLocal()
    try:
        account = db.execute(select(ExchangeAccount).where(ExchangeAccount.exchange_name == "binance", ExchangeAccount.is_active.is_(True))).scalar_one_or_none()
        if not account:
            raise RuntimeError("No active Binance exchange account found")
        api_key = decrypt_text(account.api_key_enc)
        api_secret = decrypt_text(account.api_secret_enc)
        ws_base_url = "wss://fstream.binance.com"
        consumer = BinanceUserStreamConsumer(api_key=api_key, api_secret=api_secret, is_testnet=account.is_testnet, ws_base_url=ws_base_url)
        consumer.start()
    finally:
        db.close()

if __name__ == "__main__":
    main()
