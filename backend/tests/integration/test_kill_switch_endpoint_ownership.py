"""admin kill-switch endpoint — 소유권 검증 회귀.

audit 발견 (2026-05-04): /admin/kill-switch/{id}/enable 과 /disable 가
exchange_account_id 만으로 호출 가능. user_id 검증 없어 multi-user 시
다른 user 의 계정을 임의로 enable/disable 가능 (보안 결함).

Fix: _verify_account_ownership 헬퍼로 본인 소유 검증. 다른 user 의 계정 ID
호출 시 404 (정보 노출 방지 — "not found" 와 동일 메시지).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.admin import disable_kill_switch, enable_kill_switch
from app.models.account_kill_switch import AccountKillSwitch


class TestKillSwitchOwnership:
    def test_owner_can_enable(
        self, db_session, make_user, make_exchange_account
    ) -> None:
        u = make_user()
        ea = make_exchange_account(user=u)
        resp = enable_kill_switch(
            exchange_account_id=ea.id,
            reason_code="MANUAL",
            reason_message="test",
            db=db_session,
            user_id=u.id,
        )
        assert "enabled" in resp.message.lower()
        ks = db_session.execute(
            select(AccountKillSwitch).where(
                AccountKillSwitch.exchange_account_id == ea.id
            )
        ).scalar_one_or_none()
        assert ks is not None and ks.is_enabled

    def test_other_user_enable_returns_404(
        self, db_session, make_user, make_exchange_account
    ) -> None:
        owner = make_user()
        ea = make_exchange_account(user=owner)
        intruder = make_user()  # 다른 user
        with pytest.raises(HTTPException) as ei:
            enable_kill_switch(
                exchange_account_id=ea.id,
                reason_code="MALICIOUS",
                reason_message="attempt",
                db=db_session,
                user_id=intruder.id,
            )
        assert ei.value.status_code == 404
        # 정보 노출 방지: "본인 소유 아님" 명시 (또는 "not found")
        assert "not found" in ei.value.detail.lower() or "본인 소유" in ei.value.detail

        # kill-switch 발동 안 됨
        ks = db_session.execute(select(AccountKillSwitch)).scalar_one_or_none()
        assert ks is None

    def test_owner_can_disable(
        self, db_session, make_user, make_exchange_account
    ) -> None:
        from datetime import datetime, timezone
        u = make_user()
        ea = make_exchange_account(user=u)
        # 미리 활성화
        ks = AccountKillSwitch(
            exchange_account_id=ea.id, is_enabled=True,
            reason_code="MANUAL", reason_message="prev",
            triggered_at=datetime.now(timezone.utc),
        )
        db_session.add(ks)
        db_session.commit()

        resp = disable_kill_switch(
            exchange_account_id=ea.id,
            db=db_session,
            user_id=u.id,
        )
        assert "cleared" in resp.message.lower()

        db_session.refresh(ks)
        assert ks.is_enabled is False

    def test_other_user_disable_returns_404(
        self, db_session, make_user, make_exchange_account
    ) -> None:
        from datetime import datetime, timezone
        owner = make_user()
        ea = make_exchange_account(user=owner)
        ks = AccountKillSwitch(
            exchange_account_id=ea.id, is_enabled=True,
            reason_code="LEGIT", reason_message="x",
            triggered_at=datetime.now(timezone.utc),
        )
        db_session.add(ks)
        db_session.commit()

        intruder = make_user()
        with pytest.raises(HTTPException) as ei:
            disable_kill_switch(
                exchange_account_id=ea.id,
                db=db_session,
                user_id=intruder.id,
            )
        assert ei.value.status_code == 404

        # kill-switch 그대로 활성 (intruder 가 못 끔)
        db_session.refresh(ks)
        assert ks.is_enabled is True

    def test_nonexistent_account_returns_404(
        self, db_session, make_user
    ) -> None:
        u = make_user()
        with pytest.raises(HTTPException) as ei:
            enable_kill_switch(
                exchange_account_id=99999,
                reason_code="MANUAL", reason_message="test",
                db=db_session, user_id=u.id,
            )
        assert ei.value.status_code == 404
