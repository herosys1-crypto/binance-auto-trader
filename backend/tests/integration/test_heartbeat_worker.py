"""run_heartbeat_once — 24/7 운영 신뢰성 알림 발송 검증.

배경 (2026-05-07): VPS 운영 시 시스템 정상 동작 신호 필요.
heartbeat 알림은 6시간마다 시스템 상태 요약을 텔레그램 발송.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.notification import Notification
from app.workers import heartbeat_worker


@pytest.fixture
def patched_hb_session(monkeypatch, engine):
    from sqlalchemy.orm import sessionmaker
    fac = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    monkeypatch.setattr("app.workers.heartbeat_worker.SessionLocal", fac)
    return fac


class TestHeartbeat:
    def test_healthy_state_sends_green(self, db_session, patched_hb_session) -> None:
        """KS 0 + CRITICAL 0 → 「💚 정상」 알림 1건."""
        heartbeat_worker.run_heartbeat_once()

        notifs = db_session.execute(
            select(Notification).where(Notification.title.like("%[System Heartbeat]%"))
        ).scalars().all()
        assert len(notifs) == 1
        assert "💚" in notifs[0].title
        assert "정상" in notifs[0].title
        assert "활성 strategy" in notifs[0].body

    def test_unhealthy_with_kill_switch_sends_warning(
        self, db_session, make_user, make_exchange_account, patched_hb_session
    ) -> None:
        """KS 활성 시 「⚠️ 주의 필요」 알림."""
        from app.models.account_kill_switch import AccountKillSwitch
        u = make_user()
        ea = make_exchange_account(user=u)
        ks = AccountKillSwitch(
            exchange_account_id=ea.id, is_enabled=True,
            reason_code="MANUAL", reason_message="test",
            triggered_at=datetime.now(timezone.utc),
        )
        db_session.add(ks)
        db_session.commit()

        heartbeat_worker.run_heartbeat_once()

        notifs = db_session.execute(
            select(Notification).where(Notification.title.like("%[System Heartbeat]%"))
        ).scalars().all()
        assert len(notifs) == 1
        assert "⚠️" in notifs[0].title
        assert "주의 필요" in notifs[0].title
        assert "1건 활성" in notifs[0].body

    def test_active_strategy_count_in_body(
        self, db_session, make_strategy, patched_hb_session
    ) -> None:
        """활성 strategy 수가 body 에 정확히 포함."""
        first = make_strategy(symbol_str="BTCUSDT", status="STAGE1_OPEN")
        make_strategy(symbol_str="ETHUSDT", status="STAGE2_OPEN", user=first.user, exchange_account=first.exchange_account)
        # 종료된 strategy 는 카운트 X
        make_strategy(symbol_str="SOLUSDT", status="CLOSED_BY_TP", user=first.user, exchange_account=first.exchange_account)

        heartbeat_worker.run_heartbeat_once()

        notifs = db_session.execute(
            select(Notification).where(Notification.title.like("%[System Heartbeat]%"))
        ).scalars().all()
        assert len(notifs) == 1
        # 활성 2건 (CLOSED_BY_TP 는 종료라 제외)
        assert "활성 strategy : 2" in notifs[0].body

    def test_body_contains_required_metrics(
        self, db_session, patched_hb_session
    ) -> None:
        """알림 body 가 운영 핵심 메트릭 모두 포함 — 시각/strategy/KS/CRITICAL/알림."""
        heartbeat_worker.run_heartbeat_once()
        notif = db_session.execute(
            select(Notification).where(Notification.title.like("%[System Heartbeat]%"))
        ).scalar_one()
        # 핵심 라벨 모두 존재 (운영자가 한눈에 파악 가능해야)
        assert "시각" in notif.body
        assert "활성 strategy" in notif.body
        assert "Kill-Switch" in notif.body
        assert "CRITICAL" in notif.body
        assert "알림" in notif.body  # "6h 알림: ..."
