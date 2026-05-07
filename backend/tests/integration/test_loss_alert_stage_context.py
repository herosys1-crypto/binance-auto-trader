"""-50% 손실 알림에 단계 진입 상황 표시 검증 (사용자 #5-08 보고).

배경: 「강제 청산 임박」 메시지가 단계 미완료시에도 발송돼 사용자 오해.
실제 강제 청산 (evaluate_stop_loss) 은 모든 단계 진입 후만 발동 — 알림에
현재 단계 / 전체 단계 명시해 정확한 정보 제공.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.models.notification import Notification
from app.services.notification_service import NotificationService


class TestLossAlertStageContext:
    def test_alert_includes_partial_stage_status(self, db_session, make_user, make_exchange_account, make_strategy) -> None:
        """단계 미완료 (3/5) — 알림에 「강제 청산 미발동」 안내 포함."""
        u = make_user()
        ea = make_exchange_account(user=u)
        s = make_strategy(user=u, exchange_account=ea)

        NotificationService(db_session).send_loss_threshold_alert(
            strategy_instance_id=s.id,
            symbol="BTCUSDT", side="SHORT",
            pnl_pct="-55.5", threshold_pct="-50",
            current_stage=3, total_stages=5,
        )
        notif = db_session.execute(
            select(Notification).where(Notification.strategy_instance_id == s.id)
        ).scalar_one()
        assert "단계: 3/5" in notif.body
        assert "강제 청산 미발동" in notif.body
        # 모든 단계 완료시 안내 미포함
        assert "다음 cycle 강제 청산" not in notif.body

    def test_alert_includes_all_stages_complete(self, db_session, make_user, make_exchange_account, make_strategy) -> None:
        """모든 단계 진입 완료 (5/5) — 알림에 「강제 청산 발동 예정」 포함."""
        u = make_user()
        ea = make_exchange_account(user=u)
        s = make_strategy(user=u, exchange_account=ea)

        NotificationService(db_session).send_loss_threshold_alert(
            strategy_instance_id=s.id,
            symbol="BTCUSDT", side="SHORT",
            pnl_pct="-55.5", threshold_pct="-50",
            current_stage=5, total_stages=5,
        )
        notif = db_session.execute(
            select(Notification).where(Notification.strategy_instance_id == s.id)
        ).scalar_one()
        assert "5/5" in notif.body
        assert "모두 진입 완료" in notif.body
        assert "강제 청산 발동 예정" in notif.body
        # 단계 미완료 안내 포함 안 됨
        assert "강제 청산 미발동" not in notif.body

    def test_backward_compat_no_stage_args(self, db_session, make_user, make_exchange_account, make_strategy) -> None:
        """단계 인자 없이 호출 (호환) — 기존 표현 유지."""
        u = make_user()
        ea = make_exchange_account(user=u)
        s = make_strategy(user=u, exchange_account=ea)

        NotificationService(db_session).send_loss_threshold_alert(
            strategy_instance_id=s.id,
            symbol="BTCUSDT", side="SHORT",
            pnl_pct="-55.5", threshold_pct="-50",
            # current_stage / total_stages 미전달
        )
        notif = db_session.execute(
            select(Notification).where(Notification.strategy_instance_id == s.id)
        ).scalar_one()
        assert "모든 단계 진입 후" in notif.body  # 호환 fallback 메시지
