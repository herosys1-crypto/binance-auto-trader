"""알림 서비스 — Telegram + DB 영구 기록.

메시지는 한국어 + 이모지 + 천단위 콤마 포맷으로 가독성 강화.
Telegram 은 HTML parse_mode 로 발송 (굵게/줄바꿈 안전 처리).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import requests
from sqlalchemy import select

from app.core.config import settings
from app.models.notification import Notification

# 알림 dedup 윈도우 — 최근 N 초 내 동일 (strategy + title) 알림이 SENT 상태면 skip.
# user-stream 다중 인스턴스 / Binance 이벤트 재전송으로 인한 중복 방어.
NOTIFICATION_DEDUP_WINDOW_SECONDS = 60


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
    def _is_recent_duplicate(self, *, strategy_instance_id: int | None, title: str) -> bool:
        """최근 NOTIFICATION_DEDUP_WINDOW_SECONDS 초 내에 동일한
        (strategy_instance_id, title) 로 SENT 또는 PENDING 인 알림이 있으면 True.

        - SENT: 이미 발송 완료 → skip
        - PENDING: 다른 트랜잭션이 발송 중 → skip (race condition 방어)

        atomic UPDATE WHERE 가 있어도 다중 user-stream 인스턴스나 Binance
        이벤트 재전송으로 인한 중복을 한 번 더 차단한다. DB 가 단일 source-of-truth
        이므로 모든 인스턴스가 같은 결과를 보게 된다.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=NOTIFICATION_DEDUP_WINDOW_SECONDS)
        # PENDING 은 created_at, SENT 는 sent_at 으로 비교하지만 조건을 OR 로 합치면
        # 인덱스 사용이 어렵다. 단순화 — created_at 만으로 검사 (PENDING/SENT 둘 다 cover).
        # NOTE: created_at 은 server_default=func.now() 이므로 Notification 생성 시점.
        stmt = (
            select(Notification.id)
            .where(Notification.strategy_instance_id == strategy_instance_id)
            .where(Notification.title == title)
            .where(Notification.send_status.in_(["SENT", "PENDING"]))
            .where(Notification.created_at >= cutoff)
            .limit(1)
        )
        return self.db.execute(stmt).first() is not None

    def send(self, *, strategy_instance_id: int | None, channel: str, title: str, body: str) -> Notification:
        # Bug fix (2026-04-30): 1단계 진입 알림 등이 2회 발송되는 문제 방어.
        # atomic UPDATE WHERE (stage_plan.is_triggered) 만으로는 다중 user-stream
        # 컨테이너 / Binance 이벤트 재전송 시 완전 차단 안 되는 경우 관측됨.
        # 최근 60초 내 동일 (strategy + title) SENT 알림이 있으면 skip 하고
        # 기존 row 를 그대로 반환한다 (Telegram 재발송 차단).
        if channel == "TELEGRAM" and self._is_recent_duplicate(
            strategy_instance_id=strategy_instance_id, title=title
        ):
            existing = self.db.execute(
                select(Notification)
                .where(Notification.strategy_instance_id == strategy_instance_id)
                .where(Notification.title == title)
                .where(Notification.send_status.in_(["SENT", "PENDING"]))
                .order_by(Notification.id.desc())
                .limit(1)
            ).scalars().first()
            if existing is not None:
                return existing  # 중복 발송 차단

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
    # 증거금 추가 완료 (2026-05-04 신규)
    # ------------------------------------------------------------------
    def send_margin_added_alert(
        self,
        *,
        strategy_instance_id: int,
        symbol: str,
        side: str,
        amount: Any,
    ) -> Notification:
        emoji = _side_emoji(side)
        title = f"🛡 [증거금 추가] {symbol} {side}"
        lines = [
            f"{emoji} 종목         : {symbol} {side}",
            f"💵 추가 금액   : {_fmt_num(amount)} USDT",
            f"✅ 청산가 완화 효과 — 거래소 UI 에서 새 청산가 확인",
        ]
        body = "\n".join(lines)
        return self.send(
            strategy_instance_id=strategy_instance_id,
            channel="TELEGRAM", title=title, body=body,
        )

    # ------------------------------------------------------------------
    # 손실 임계 알림 (2026-05-04 신규) — -50% ROI 도달 시 1회
    # ------------------------------------------------------------------
    def send_loss_threshold_alert(
        self,
        *,
        strategy_instance_id: int,
        symbol: str,
        side: str,
        pnl_pct: Any,
        threshold_pct: Any,
    ) -> Notification:
        emoji = _side_emoji(side)
        title = f"⚠️ [손실 {_fmt_num(threshold_pct)}% 도달] {symbol} {side}"
        lines = [
            f"{emoji} 종목       : {symbol} {side}",
            f"📉 현재 ROI : {_fmt_num(pnl_pct)}% (임계 {_fmt_num(threshold_pct)}%)",
            f"⚠️ 강제 청산 (-50%) 임박 — 증거금 추가 또는 수동 청산 검토",
            f"💡 대시보드 → 해당 전략 → 「🛡 증거금 추가」 버튼으로 청산가 완화 가능",
        ]
        body = "\n".join(lines)
        return self.send(
            strategy_instance_id=strategy_instance_id,
            channel="TELEGRAM", title=title, body=body,
        )

    # ------------------------------------------------------------------
    # 전략 시작 알림 (NEW 2026-04-29) — 주문 발송 직후 (FILLED 무관)
    # ------------------------------------------------------------------
    def send_strategy_started_alert(
        self,
        *,
        strategy_instance_id: int,
        symbol: str,
        side: str,
        start_price: Any,
        leverage: Any,
        total_capital: Any,
    ) -> Notification:
        emoji = _side_emoji(side)
        title = f"{emoji} [전략 시작] {symbol} {side}"
        lines = [
            f"📌 종목       : {symbol}",
            f"🎯 방향       : {side}",
            f"💵 시작가     : {_fmt_num(start_price)}",
            f"⚖️  레버리지   : {leverage}x",
            f"💰 총 자본    : {_fmt_num(total_capital)} USDT",
            f"📋 1단계 LIMIT 주문 거래소에 발송됨",
            f"⏳ 체결되면 별도 알림 발송됨",
        ]
        body = "\n".join(lines)
        return self.send(strategy_instance_id=strategy_instance_id, channel="TELEGRAM", title=title, body=body)

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
        pnl_pct: Any | None = None,
        closed_qty: Any | None = None,
        remaining_qty: Any | None = None,
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
        if closed_qty is not None:
            lines.append(f"📤 청산 수량 : {_fmt_num(closed_qty)}")
        if remaining_qty is not None:
            try:
                rq = Decimal(str(remaining_qty))
                rq_str = _fmt_num(rq) if rq > 0 else "0 (전량 청산)"
            except Exception:
                rq_str = _fmt_num(remaining_qty)
            lines.append(f"📦 남은 수량 : {rq_str}")
        if realized_pnl is not None:
            try:
                sign = "+" if Decimal(str(realized_pnl)) >= 0 else ""
            except Exception:
                sign = ""
            lines.append(f"💎 손익 금액 : {sign}{_fmt_num(realized_pnl)} USDT")
        if pnl_pct is not None:
            try:
                sign = "+" if Decimal(str(pnl_pct)) >= 0 else ""
            except Exception:
                sign = ""
            lines.append(f"📊 수익률    : {sign}{_fmt_num(pnl_pct)}%")
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
        pnl_pct: Any | None = None,
    ) -> Notification:
        emoji = _side_emoji(side)
        title = f"🛑 [손절 발동] {symbol} {side} {emoji}"
        lines = [
            f"📌 종목       : {symbol}",
            f"🎯 방향       : {side}",
            f"💰 총 투자금  : {_fmt_num(total_capital)} USDT",
            f"📉 손익 금액  : {_fmt_num(current_loss_amount)} USDT",
        ]
        if pnl_pct is not None:
            try:
                sign = "+" if Decimal(str(pnl_pct)) >= 0 else ""
            except Exception:
                sign = ""
            lines.append(f"📊 수익률     : {sign}{_fmt_num(pnl_pct)}%")
        lines.append("🔁 상태       : 재진입 대기 (manual_ready)")
        body = "\n".join(lines)
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
    # 크라이시스 복구 모드 알림 4종 (Phase D-2)
    # ------------------------------------------------------------------
    def send_crisis_mode_entered(
        self,
        *,
        strategy_instance_id: int,
        symbol: str,
        side: str,
        current_stage: int,
        max_loss_pct: Any,
    ) -> Notification:
        emoji = _side_emoji(side)
        title = f"🚨 [크라이시스 모드 진입] {symbol} {side} {emoji}"
        body = "\n".join([
            f"📌 종목         : {symbol}",
            f"🎯 방향         : {side}",
            f"🪜 현재 단계    : {current_stage}",
            f"📉 누적 최대 손실: {_fmt_num(max_loss_pct)}%",
            "",
            "ℹ️ TP1 임계가 기존 +10% → +5% 로 낮아집니다.",
            "ℹ️ +5% TP1 발동 시 트레일링 -5% + 빠른 손절 -1% 보호 모드 활성화.",
        ])
        return self.send(strategy_instance_id=strategy_instance_id, channel="TELEGRAM", title=title, body=body)

    def send_crisis_first_tp(
        self,
        *,
        strategy_instance_id: int,
        symbol: str,
        side: str,
        pnl_pct: Any,
        closed_qty: Any,
    ) -> Notification:
        emoji = _side_emoji(side)
        title = f"⚡ [크라이시스 첫 TP +5%] {symbol} {side} {emoji}"
        body = "\n".join([
            f"📌 종목      : {symbol}",
            f"💰 현재 PnL : {_fmt_num(pnl_pct)}%",
            f"💵 청산 수량: {_fmt_qty(closed_qty)} (25%)",
            "",
            "🛡 보호 모드 [Stage 2] 활성화:",
            "   • 트레일링 -5% (피크에서 -5% 회귀 시 전량 청산)",
            "   • 빠른 손절 -1% (PnL -1% 시 전량 손절)",
        ])
        return self.send(strategy_instance_id=strategy_instance_id, channel="TELEGRAM", title=title, body=body)

    def send_crisis_trailing_full(
        self,
        *,
        strategy_instance_id: int,
        symbol: str,
        side: str,
        peak_pnl_pct: Any,
        current_pnl_pct: Any,
    ) -> Notification:
        emoji = _side_emoji(side)
        title = f"🛡 [크라이시스 트레일링 청산] {symbol} {side} {emoji}"
        body = "\n".join([
            f"📌 종목      : {symbol}",
            f"📈 피크 PnL : {_fmt_num(peak_pnl_pct)}%",
            f"📉 현재 PnL : {_fmt_num(current_pnl_pct)}%",
            f"📏 회귀     : {_fmt_num(Decimal(str(peak_pnl_pct or 0)) - Decimal(str(current_pnl_pct or 0)))}% ≥ 5%",
            "",
            "✅ 남은 전량 시장가 청산 — 차익 보호 완료.",
        ])
        return self.send(strategy_instance_id=strategy_instance_id, channel="TELEGRAM", title=title, body=body)

    def send_crisis_hard_sl(
        self,
        *,
        strategy_instance_id: int,
        symbol: str,
        side: str,
        pnl_pct: Any,
    ) -> Notification:
        emoji = _side_emoji(side)
        title = f"🚨 [크라이시스 빠른 손절 -1%] {symbol} {side} {emoji}"
        body = "\n".join([
            f"📌 종목      : {symbol}",
            f"📉 현재 PnL : {_fmt_num(pnl_pct)}%",
            "",
            "🛑 첫 TP +5% 발동 후 PnL 가 -1% 이하 도달.",
            "🛑 남은 전량 시장가 손절 → 재진입 대기 (manual_ready).",
        ])
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
