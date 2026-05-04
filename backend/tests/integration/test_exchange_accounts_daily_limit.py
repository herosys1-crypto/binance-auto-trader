"""ExchangeAccount API — daily_loss_limit_usdt 노출 회귀.

audit 발견: alembic 0010 으로 컬럼은 추가됐지만 API 에서 noop. SQL update 만
가능했음. 이제 create + PATCH + response 모두에서 노출.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.exchange_accounts import (
    ExchangeAccountCreate,
    ExchangeAccountDailyLimitUpdate,
    create_exchange_account,
    list_exchange_accounts,
    update_daily_loss_limit,
)
from app.models.exchange_account import ExchangeAccount


@pytest.fixture
def real_encryption_key(monkeypatch):
    """default 'change_me' 가 invalid Fernet key 이므로 테스트용 valid 키 주입."""
    from cryptography.fernet import Fernet
    monkeypatch.setattr("app.core.config.settings.encryption_key", Fernet.generate_key().decode())


class TestCreateWithDailyLimit:
    def test_create_with_daily_limit(
        self, db_session, make_user, real_encryption_key
    ) -> None:
        u = make_user()
        payload = ExchangeAccountCreate(
            api_key="testkey1234567890",
            api_secret="testsecret1234567890",
            is_testnet=True,
            daily_loss_limit_usdt=Decimal("75"),
        )
        resp = create_exchange_account(payload=payload, db=db_session, user_id=u.id)
        assert resp.daily_loss_limit_usdt == Decimal("75")

        # DB 검증
        row = db_session.execute(select(ExchangeAccount).where(ExchangeAccount.id == resp.id)).scalar_one()
        assert row.daily_loss_limit_usdt == Decimal("75")

    def test_create_without_daily_limit_defaults_none(
        self, db_session, make_user, real_encryption_key
    ) -> None:
        u = make_user()
        payload = ExchangeAccountCreate(
            api_key="testkey1234567890",
            api_secret="testsecret1234567890",
            is_testnet=True,
        )
        resp = create_exchange_account(payload=payload, db=db_session, user_id=u.id)
        assert resp.daily_loss_limit_usdt is None

    def test_create_with_zero_limit(
        self, db_session, make_user, real_encryption_key
    ) -> None:
        """0 = 비활성 의도. 저장됨 (0 != None 의미 보존)."""
        u = make_user()
        payload = ExchangeAccountCreate(
            api_key="testkey1234567890",
            api_secret="testsecret1234567890",
            is_testnet=True,
            daily_loss_limit_usdt=Decimal("0"),
        )
        resp = create_exchange_account(payload=payload, db=db_session, user_id=u.id)
        assert resp.daily_loss_limit_usdt == Decimal("0")

    def test_negative_limit_rejected_by_validator(
        self, db_session, make_user
    ) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ExchangeAccountCreate(
                api_key="testkey1234567890",
                api_secret="testsecret1234567890",
                is_testnet=True,
                daily_loss_limit_usdt=Decimal("-10"),
            )


class TestUpdateDailyLimit:
    def test_update_to_new_value(
        self, db_session, make_user, make_exchange_account
    ) -> None:
        u = make_user()
        ea = make_exchange_account(user=u, daily_loss_limit_usdt=None)
        resp = update_daily_loss_limit(
            exchange_account_id=ea.id,
            payload=ExchangeAccountDailyLimitUpdate(daily_loss_limit_usdt=Decimal("100")),
            db=db_session,
            user_id=u.id,
        )
        assert resp.daily_loss_limit_usdt == Decimal("100")

    def test_update_to_null_falls_back_to_global(
        self, db_session, make_user, make_exchange_account
    ) -> None:
        u = make_user()
        ea = make_exchange_account(user=u, daily_loss_limit_usdt=Decimal("50"))
        resp = update_daily_loss_limit(
            exchange_account_id=ea.id,
            payload=ExchangeAccountDailyLimitUpdate(daily_loss_limit_usdt=None),
            db=db_session,
            user_id=u.id,
        )
        assert resp.daily_loss_limit_usdt is None

    def test_update_other_user_account_404(
        self, db_session, make_user, make_exchange_account
    ) -> None:
        owner = make_user()
        ea = make_exchange_account(user=owner)
        intruder = make_user()  # 다른 user

        with pytest.raises(HTTPException) as ei:
            update_daily_loss_limit(
                exchange_account_id=ea.id,
                payload=ExchangeAccountDailyLimitUpdate(daily_loss_limit_usdt=Decimal("99")),
                db=db_session,
                user_id=intruder.id,  # 다른 user
            )
        assert ei.value.status_code == 404

    def test_update_nonexistent_404(
        self, db_session, make_user
    ) -> None:
        u = make_user()
        with pytest.raises(HTTPException) as ei:
            update_daily_loss_limit(
                exchange_account_id=99999,
                payload=ExchangeAccountDailyLimitUpdate(daily_loss_limit_usdt=Decimal("99")),
                db=db_session,
                user_id=u.id,
            )
        assert ei.value.status_code == 404


class TestListIncludesDailyLimit:
    def test_list_returns_daily_limit_field(
        self, db_session, make_user, make_exchange_account
    ) -> None:
        u = make_user()
        make_exchange_account(user=u, daily_loss_limit_usdt=Decimal("60"))

        rows = list_exchange_accounts(db=db_session, user_id=u.id)
        assert len(rows) == 1
        assert rows[0].daily_loss_limit_usdt == Decimal("60")
