"""알림 서비스 — Telegram + DB 영구 기록.

메시지는 한국어 + 이모지 + 천단위 콤마 포맷으로 가독성 강화.
Telegram 은 HTML parse_mode 로 발송 (굵게/줄바꿈 안전 처리).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import requests

from app.core.config import settings
from app.models.notification import Notification


def _fmt_num(value: Any, *, decimals: int = 2) -> str:
    """숫자를 보기 좋게 — 천단위 콤마 + 소수점 자릿수 통일.

    예: Decimal('12345.6789') → '12,345.68'
    """
    if value is None:
        return "-"
    try:
        d = Decimal(str(value))
    except Exception:
        return str(value)
    quantizer = Decimal(10) ** -decimals
    return f"{d.quantize(quantizer):,}"


def _fmt_qty(value: Any) -> str:
    """수량 포맷 (소수점 8자리, 끝의 0 제거)."""
    if value is None:
        return "-"
    try:
        d = Decimal(str(value))
        s = format(d, "f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s or "0"
    except Exception:
        return str(value)


def _side_emoji(side: str) -> str:
    return "📉" if side.upper() == "SHORT" else "📈"


class NotificationService:
    def __init__(self, db) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Core send (DB 기록 + Telegram 발송)
    # ------------------------------------------------------------------
    def send(self, *, strategy_instance_id: int | None, channel: str, title: str, body: str) -> Notification:
        notification = Notification(
            strategy_instance_id=strategy_instance_id,
            channel=channel,
            title=title,
            body=body,
            send_status="PENDING",
        )
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

    # ------------------------------------------------------------------
    # 시스템 일반 알림
    # ------------------------------------------------------------------
    def send_system_alert(self, *, title: str, body: str) -> Notification:
        return self.send(strategy_instance_id=None, channel="TELEGRAM", title=title, body=body)

    # ------------------------------------------------------------------
    # 단계 진입 알림 (NEW)
    # ------------------------------------------------------------------
    def send_stage_entered_alert(
        self,
        *,
        strategy_instance_id: int,
        symbol: str,
        side: str,
        stage_no: int,
        entry_price: Any,
        qty: Any,
        invested_capital: Any,
        avg_entry_price: Any | None = None,
    ) -> Notification:
        emoji = _side_emoji(side)
        title = f"{emoji} [{stage_no}단계 진입] {symbol} {side}"
        lines = [
            f"📌 종목       : {symbol}",
            f"🎯 방향       : {side}",
            f"🔢 단계       : {stage_no}",
            f"💵 진입가     : {_fmt_num(entry_price)}",
            f"📊 수량       : {_fmt_qty(qty)}",
            f"💰 투입 자본  : {_fmt_num(invested_capital)} USDT",
        ]
        if avg_entry_price is not None:
            lines.append(f"📐 평균 단가  : {_fmt_num(avg_entry_price)}")
        body = "\n".join(lines)
        return self.send(strategy_instance_id=strategy_instance_id, channel="TELEGRAM", title=title, body=body)

    # ------------------------------------------------------------------
    # 익절 알림
    # ------------------------------------------------------------------
    def send_take_profit_alert(
        self,
        *,
        strategy_instance_id: int,
        symbol: str,
        side: str,
        level: str,
        realized_pnl: Any | None = None,
        avg_exit_price: Any | None = None,
    ) -> Notification:
        emoji = _side_emoji(side)
        title = f"✅ [{level} 익절 체결] {symbol} {side} {emoji}"
        lines = [
            f"📌 종목      : {symbol}",
            f"🎯 방향      : {side}",
            f"🪜 레벨      : {level}",
        ]
        if avg_exit_price is not None:
            lines.append(f"💵 청산 단가 : {_fmt_num(avg_exit_price)}")
        if realized_pnl is not None:
            lines.append(f"💎 실현 손익 : {_fmt_num(realized_pnl)} USDT")
        body = "\n".join(lines)
        return self.send(strategy_instance_id=strategy_instance_id, channel="TELEGRAM", title=title, body=body)

    # ------------------------------------------------------------------
    # 손절 알림
    # ------------------------------------------------------------------
    def send_stop_loss_alert(
        self,
        *,
        strategy_instance_id: int,
        symbol: str,
        side: str,
        total_capital: Any,
        current_loss_amount: Any,
    ) -> Notification:
        emoji = _side_emoji(side)
        title = f"🛑 [손절 발동] {symbol} {side} {emoji}"
        body = "\n".join(
            [
                f"📌 종목       : {symbol}",
                f"🎯 방향       : {side}",
                f"💰 총 투자금  : {_fmt_num(total_capital)} USDT",
                f"📉 누적 손실  : {_fmt_num(current_loss_amount)} USDT",
                "🔁 상태       : 재진입 대기 (manual_ready)",
            ]
        )
        return self.send(strategy_instance_id=strategy_instance_id, channel="TELEGRAM", title=title, body=body)

    # ------------------------------------------------------------------
    # Kill-switch 발동 (NEW)
    # ------------------------------------------------------------------
    def send_kill_switch_alert(
        self,
        *,
        exchange_account_id: int,
        reason_code: str,
        reason_message: str,
    ) -> Notification:
        title = f"⚠️🔴 [Kill-Switch 발동] account #{exchange_account_id}"
        body = "\n".join(
            [
                f"🚨 사유 코드 : {reason_code}",
                f"📝 상세      : {reason_message}",
                f"⏱ 시각      : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
                "",
                "👉 신규 주문은 자동 차단됩니다.",
                "👉 해제하려면 admin 에서 disable 호출 필요.",
            ]
        )
        return self.send(strategy_instance_id=None, channel="TELEGRAM", title=title, body=body)

    # ------------------------------------------------------------------
    # 일일 손실 한도 경고 (NEW)
    # ------------------------------------------------------------------
    def send_daily_loss_warning(
        self,
        *,
        exchange_account_id: int,
        realized_pnl: Any,
        unrealized_pnl: Any,
        daily_limit: Any,
    ) -> Notification:
        total = Decimal(str(realized_pnl or 0)) + Decimal(str(unrealized_pnl or 0))
        title = f"⚠️ [일일 손실 한도 임계치 도달] account #{exchange_account_id}"
        body = "\n".join(
            [
                f"💎 실현 손익     : {_fmt_num(realized_pnl)} USDT",
                f"📊 미실현 손익   : {_fmt_num(unrealized_pnl)} USDT",
                f"➡️ 합계         : {_fmt_num(total)} USDT",
                f"🛑 한도         : -{_fmt_num(daily_limit)} USDT",
                "",
                "⚠️ 한도 초과 시 자동으로 Kill-Switch 가 발동됩니다.",
            ]
        )
        return self.send(strategy_instance_id=None, channel="TELEGRAM", title=title, body=body)

    # ------------------------------------------------------------------
    # 청산 임박 경고 (NEW)
    # ------------------------------------------------------------------
    def send_liquidation_warning(
        self,
        *,
        strategy_instance_id: int,
        symbol: str,
        side: str,
        current_price: Any,
        liquidation_price: Any,
        buffer_percent: Any,
    ) -> Notification:
        emoji = _side_emoji(side)
        title = f"🚨 [청산 임박] {symbol} {side} {emoji}"
        body = "\n".join(
            [
                f"📌 종목         : {symbol}",
                f"💵 현재가       : {_fmt_num(current_price)}",
                f"💀 청산가       : {_fmt_num(liquidation_price)}",
                f"📏 버퍼          : {_fmt_num(buffer_percent)}%",
                "",
                "⚠️ 마지막 단계 트리거가 곧 발동될 수 있습니다.",
            ]
        )
        return self.send(strategy_instance_id=strategy_instance_id, channel="TELEGRAM", title=title, body=body)

    # ------------------------------------------------------------------
    # Telegram 발송 (plain text — 한국어/이모지/특수문자 안전)
    # ------------------------------------------------------------------
    def _send_telegram(self, *, title: str, body: str) -> str:
        """parse_mode 미사용 (plain text). HTML/Markdown 의 특수문자 escape 부담 제거.

        과거 HTML 모드에서 일부 메시지가 400 Bad Request 거부되던 문제 해결.
        """
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            raise ValueError("Telegram settings are missing")
        text = f"{title}\n\n{body}"
        # Telegram 메시지 길이 제한 4096자
        if len(text) > 4000:
            text = text[:3997] + "..."
        response = requests.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={
                "chat_id": settings.telegram_chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if not response.ok:
            # 응답 본문에 정확한 에러 사유가 들어있음 (description 필드)
            try:
                err_detail = response.json().get("description", response.text)
            except Exception:
                err_detail = response.text
            raise ValueError(f"Telegram API {response.status_code}: {err_detail}")
        data = response.json()
        return str(data.get("result", {}).get("message_id", ""))
