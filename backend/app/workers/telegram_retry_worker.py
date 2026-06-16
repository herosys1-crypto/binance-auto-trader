"""Telegram Retry Worker — 사장님 실패 알림 자동 재시도 (v56).

사장님 critical 사상 (2026-06-16):
> '[send_error] HTTPSConnectionPool' = Telegram 일시 끊김 = 사장님 알림 X!

= 매 5분 = 최근 1시간 동안 = 실패 알림 자동 재시도!
= 사장님 = critical 알림 = 영구 보장!
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, desc

from app.core.database import SessionLocal
from app.models.notification import Notification
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


def run_telegram_retry_once() -> dict:
    """매 5분 = 실패 알림 자동 재시도."""
    db = SessionLocal()
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "failed_found": 0,
        "retry_sent": 0,
        "retry_failed": 0,
    }
    try:
        # 최근 1시간 = 실패 알림 조회
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        failed = db.execute(
            select(Notification)
            .where(Notification.send_status == "FAILED")
            .where(Notification.channel == "TELEGRAM")
            .where(Notification.created_at >= cutoff)
            .order_by(desc(Notification.id))
            .limit(30)  # 한번에 30개씩!
        ).scalars().all()
        result["failed_found"] = len(failed)

        if not failed:
            logger.info("[telegram-retry] 실패 알림 0건!")
            return result

        notif_service = NotificationService(db)
        for n in failed:
            try:
                # [send_error] 표시 제거 후 = retry!
                clean_body = (n.body or "").split("\n\n[send_error")[0]
                external_id = notif_service._send_telegram(title=n.title, body=clean_body)
                n.send_status = "SENT"
                n.external_message_id = external_id
                n.sent_at = datetime.now(timezone.utc)
                n.body = clean_body  # 깨끗하게 정리!
                result["retry_sent"] += 1
                logger.info("[telegram-retry] ✅ 재전송 성공 #%s: %s", n.id, n.title[:50])
            except Exception as e:
                result["retry_failed"] += 1
                logger.warning("[telegram-retry] ❌ 재전송 실패 #%s: %s", n.id, e)
        db.commit()

        logger.info(
            "[telegram-retry] %d failed → %d sent, %d still failed",
            result["failed_found"], result["retry_sent"], result["retry_failed"],
        )
    finally:
        db.close()
    return result


if __name__ == "__main__":
    import json
    r = run_telegram_retry_once()
    print(json.dumps(r, indent=2, ensure_ascii=False))
