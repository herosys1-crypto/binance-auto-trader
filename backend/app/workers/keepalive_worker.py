from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.core.database import SessionLocal
from app.integrations.binance.client import BinanceClient
from app.models.exchange_account import ExchangeAccount
from app.models.stream_session import StreamSession
from app.observability.metrics import listen_key_keepalive_total
from app.services.notification_service import NotificationService


def run_keepalive_once(decrypt_func) -> None:
    """Refresh Binance listenKey for each active exchange account.

    Bug #3 fix (2026-04-28): 이전 버전은 stream_sessions 테이블의 ACTIVE row 만
    keepalive 했는데, user-stream worker 가 stream_sessions 에 row 를 안 만들고
    있어서 결국 keepalive 가 한 번도 실행 안 됨 → 60 분마다 listenKey 만료 →
    알림 폭탄. Binance 의 PUT /fapi/v1/listenKey 는 listenKey 값 자체가 아닌
    API 키 단위로 동작하므로, exchange_accounts 를 직접 순회하면 stream_sessions
    의존성을 제거하고도 정상 동작한다.
    """
    db = SessionLocal()
    try:
        accounts = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_active.is_(True))
        ).scalars().all()
        notifier = NotificationService(db)
        for account in accounts:
            try:
                client = BinanceClient(
                    api_key=decrypt_func(account.api_key_enc),
                    api_secret=decrypt_func(account.api_secret_enc),
                    is_testnet=account.is_testnet,
                )
                client.keepalive_user_stream()
                listen_key_keepalive_total.labels(status="success").inc()

                # 부가: stream_sessions 가 있으면 갱신, 없으면 새로 INSERT 해서
                # 가시성 + 향후 추적 가능하게 한다.
                now = datetime.now(timezone.utc)
                latest = db.execute(
                    select(StreamSession)
                    .where(StreamSession.exchange_account_id == account.id)
                    .where(StreamSession.status == "ACTIVE")
                    .order_by(StreamSession.id.desc())
                    .limit(1)
                ).scalars().first()
                if latest:
                    latest.last_keepalive_at = now
                    latest.expires_at = now + timedelta(minutes=60)
                else:
                    db.add(StreamSession(
                        exchange_account_id=account.id,
                        listen_key="(managed-by-worker)",
                        status="ACTIVE",
                        started_at=now,
                        last_keepalive_at=now,
                        expires_at=now + timedelta(minutes=60),
                        notes="auto-created by keepalive_worker",
                    ))
            except Exception as e:
                listen_key_keepalive_total.labels(status="failed").inc()
                # 알림은 invalid API key 같은 영구적 실패에만 보내고,
                # 일시적 네트워크 오류는 silent 하게 처리하여 알림 폭탄 방지.
                error_msg = str(e)
                if any(s in error_msg for s in ["API-key format invalid", "Invalid API-key", "-2014", "-2015"]):
                    # Account 자체가 깨진 경우 — 30분마다 한 번 알림 (지나치게 많지 않음)
                    notifier.send_system_alert(
                        title="[시스템 경고] listenKey keepalive 실패 (API 키 문제)",
                        body=f"exchange_account_id={account.id}, error={error_msg}",
                    )
                # 그 외 일시 오류는 메트릭만 카운트, 알림 안 보냄.
        db.commit()
    finally:
        db.close()
