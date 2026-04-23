from datetime import datetime, timezone
import requests
from app.core.config import settings
from app.models.notification import Notification

class NotificationService:
    def __init__(self, db) -> None:
        self.db = db

    def send(self, *, strategy_instance_id: int | None, channel: str, title: str, body: str) -> Notification:
        notification = Notification(strategy_instance_id=strategy_instance_id, channel=channel, title=title, body=body, send_status="PENDING")
        self.db.add(notification)
        self.db.flush()
        try:
            if channel == "TELEGRAM":
                external_id = self._send_telegram(title=title, body=body)
            else:
                external_id = "local-only"
            notification.send_status = "SENT"
            notification.external_message_id = external_id
            notification.sent_at = datetime.now(timezone.utc)
        except Exception as e:
            notification.send_status = "FAILED"
            notification.body = f"{body}\n\n[send_error] {e}"
        self.db.commit()
        self.db.refresh(notification)
        return notification

    def send_system_alert(self, *, title: str, body: str) -> Notification:
        return self.send(strategy_instance_id=None, channel="TELEGRAM", title=title, body=body)

    def send_stop_loss_alert(self, *, strategy_instance_id: int, symbol: str, side: str, total_capital: str, current_loss_amount: str) -> Notification:
        return self.send(strategy_instance_id=strategy_instance_id, channel="TELEGRAM", title=f"[손절 알림] {symbol} {side}", body=f"{symbol} {side} 전략이 손절되었습니다.\n총 투자금: {total_capital}\n누적 손실: {current_loss_amount}\n상태: 재진입 대기 준비")

    def send_take_profit_alert(self, *, strategy_instance_id: int, symbol: str, side: str, level: str) -> Notification:
        return self.send(strategy_instance_id=strategy_instance_id, channel="TELEGRAM", title=f"[익절 알림] {symbol} {side} {level}", body=f"{symbol} {side} 전략에서 {level} 익절이 체결되었습니다.")

    def _send_telegram(self, *, title: str, body: str) -> str:
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            raise ValueError("Telegram settings are missing")
        response = requests.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": settings.telegram_chat_id, "text": f"{title}\n\n{body}"},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        return str(data.get("result", {}).get("message_id", ""))
