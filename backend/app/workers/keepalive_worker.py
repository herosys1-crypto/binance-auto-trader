from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.core.database import SessionLocal
from app.integrations.binance.client import BinanceClient
from app.models.exchange_account import ExchangeAccount
from app.models.stream_session import StreamSession
from app.observability.metrics import listen_key_keepalive_total
from app.services.notification_service import NotificationService

def run_keepalive_once(decrypt_func) -> None:
    db = SessionLocal()
    try:
        rows = db.execute(
            select(StreamSession, ExchangeAccount)
            .join(ExchangeAccount, StreamSession.exchange_account_id == ExchangeAccount.id)
            .where(StreamSession.status == "ACTIVE")
            .where(ExchangeAccount.is_active.is_(True))
        ).all()
        notifier = NotificationService(db)
        for stream_session, account in rows:
            try:
                client = BinanceClient(api_key=decrypt_func(account.api_key_enc), api_secret=decrypt_func(account.api_secret_enc), is_testnet=account.is_testnet)
                client.keepalive_user_stream()
                now = datetime.now(timezone.utc)
                stream_session.last_keepalive_at = now
                stream_session.expires_at = now + timedelta(minutes=60)
                listen_key_keepalive_total.labels(status="success").inc()
            except Exception as e:
                stream_session.status = "ERROR"
                stream_session.notes = f"keepalive failed: {e}"
                listen_key_keepalive_total.labels(status="failed").inc()
                notifier.send_system_alert(title="[시스템 경고] listenKey keepalive 실패", body=f"exchange_account_id={account.id}, error={e}")
        db.commit()
    finally:
        db.close()
