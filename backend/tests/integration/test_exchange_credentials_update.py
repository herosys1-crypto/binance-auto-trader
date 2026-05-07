"""PATCH /exchange-accounts/{id}/credentials — API 키 회전 + testnet ↔ mainnet 전환.

배경 (2026-05-07 사용자 요청):
testnet 운영 후 mainnet 전환을 위해 키만 바꿔야 하는데 기존엔 row 삭제 + 재등록만
가능했음 (해당 계정의 strategy 모두 망가짐). 이 endpoint 가:
  1. 새 키로 Binance 호출 검증 (실패 시 DB 변경 0)
  2. 환경 전환 시 활성 strategy 가드 (포지션 mismatch 방지)
  3. 성공 시 audit 알림 (텔레그램 + DB)
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.exchange_accounts import (
    ExchangeAccountCredentialsUpdate,
    update_credentials,
)
from app.core.crypto import decrypt_text
from app.models.exchange_account import ExchangeAccount
from app.models.notification import Notification


def _patch_binance(monkeypatch, *, fail: bool = False) -> None:
    """BinanceClient 를 fake — get_account 호출만 mock."""
    class _FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
        def get_account(self):
            if fail:
                raise Exception("API key invalid (-2015 simulated)")
            return {"availableBalance": "1000", "totalMarginBalance": "1000", "totalMaintMargin": "0"}
    monkeypatch.setattr("app.api.v1.exchange_accounts.BinanceClient", _FakeClient)


class TestCredentialsRotation:
    def test_valid_keys_rotate_and_encrypt(
        self, db_session, make_user, make_exchange_account, monkeypatch
    ) -> None:
        """새 키 → Fernet 암호화 후 DB 저장, decrypt 시 원래 plain."""
        _patch_binance(monkeypatch)
        u = make_user()
        ea = make_exchange_account(user=u, is_testnet=True)
        old_enc = ea.api_key_enc

        resp = update_credentials(
            exchange_account_id=ea.id,
            payload=ExchangeAccountCredentialsUpdate(
                api_key="new-mainnet-api-key-1234567890",
                api_secret="new-mainnet-secret-abcdefghij",
            ),
            db=db_session,
            user_id=u.id,
        )
        assert resp.id == ea.id

        db_session.refresh(ea)
        assert ea.api_key_enc != old_enc  # 변경됨
        assert decrypt_text(ea.api_key_enc) == "new-mainnet-api-key-1234567890"
        assert decrypt_text(ea.api_secret_enc) == "new-mainnet-secret-abcdefghij"
        assert ea.is_testnet is True  # 명시 안 했으니 유지

    def test_invalid_keys_rejected_db_unchanged(
        self, db_session, make_user, make_exchange_account, monkeypatch
    ) -> None:
        """Binance 인증 실패 시 400 + DB 변경 0."""
        _patch_binance(monkeypatch, fail=True)
        u = make_user()
        ea = make_exchange_account(user=u)
        old_enc = ea.api_key_enc

        with pytest.raises(HTTPException) as ei:
            update_credentials(
                exchange_account_id=ea.id,
                payload=ExchangeAccountCredentialsUpdate(
                    api_key="will-fail-binance-validation-xx",
                    api_secret="will-fail-binance-validation-yy",
                ),
                db=db_session,
                user_id=u.id,
            )
        assert ei.value.status_code == 400
        assert "Binance 인증 실패" in ei.value.detail

        db_session.refresh(ea)
        assert ea.api_key_enc == old_enc  # 변경 안 됨

    def test_flip_testnet_to_mainnet_no_active_strategies(
        self, db_session, make_user, make_exchange_account, monkeypatch
    ) -> None:
        """활성 strategy 없으면 testnet → mainnet 전환 가능."""
        _patch_binance(monkeypatch)
        u = make_user()
        ea = make_exchange_account(user=u, is_testnet=True)

        update_credentials(
            exchange_account_id=ea.id,
            payload=ExchangeAccountCredentialsUpdate(
                api_key="mainnet-key-abcdefghijkl",
                api_secret="mainnet-secret-opqrstuvwxyz",
                is_testnet=False,
            ),
            db=db_session,
            user_id=u.id,
        )
        db_session.refresh(ea)
        assert ea.is_testnet is False

    def test_flip_testnet_with_active_strategy_rejected(
        self, db_session, make_user, make_exchange_account, make_strategy, monkeypatch
    ) -> None:
        """활성 strategy 있으면 환경 전환 거부 (포지션 mismatch 방지)."""
        _patch_binance(monkeypatch)
        u = make_user()
        ea = make_exchange_account(user=u, is_testnet=True)
        make_strategy(user=u, exchange_account=ea, status="STAGE1_OPEN")

        with pytest.raises(HTTPException) as ei:
            update_credentials(
                exchange_account_id=ea.id,
                payload=ExchangeAccountCredentialsUpdate(
                    api_key="mainnet-key-need-be-blocked",
                    api_secret="mainnet-secret-need-be-blocked",
                    is_testnet=False,
                ),
                db=db_session,
                user_id=u.id,
            )
        assert ei.value.status_code == 400
        assert "환경 전환 불가" in ei.value.detail
        assert "활성 strategy" in ei.value.detail

        db_session.refresh(ea)
        assert ea.is_testnet is True  # 변경 안 됨

    def test_key_rotation_with_active_strategy_allowed(
        self, db_session, make_user, make_exchange_account, make_strategy, monkeypatch
    ) -> None:
        """환경 유지 (is_testnet 미지정) + 키만 회전 — 활성 strategy 있어도 허용."""
        _patch_binance(monkeypatch)
        u = make_user()
        ea = make_exchange_account(user=u, is_testnet=True)
        make_strategy(user=u, exchange_account=ea, status="STAGE1_OPEN")

        update_credentials(
            exchange_account_id=ea.id,
            payload=ExchangeAccountCredentialsUpdate(
                api_key="rotated-testnet-key-xx",
                api_secret="rotated-testnet-secret-yy",
                # is_testnet 미지정 → 유지
            ),
            db=db_session,
            user_id=u.id,
        )
        db_session.refresh(ea)
        assert ea.is_testnet is True
        assert decrypt_text(ea.api_key_enc) == "rotated-testnet-key-xx"

    def test_other_user_account_returns_404(
        self, db_session, make_user, make_exchange_account, monkeypatch
    ) -> None:
        """다른 user 의 계정 PATCH 시도 → 404 (정보 노출 방지)."""
        _patch_binance(monkeypatch)
        owner = make_user()
        ea = make_exchange_account(user=owner)
        intruder = make_user()

        with pytest.raises(HTTPException) as ei:
            update_credentials(
                exchange_account_id=ea.id,
                payload=ExchangeAccountCredentialsUpdate(
                    api_key="malicious-attempt-by-other",
                    api_secret="malicious-attempt-by-other",
                ),
                db=db_session,
                user_id=intruder.id,
            )
        assert ei.value.status_code == 404

    def test_audit_notification_sent_on_success(
        self, db_session, make_user, make_exchange_account, monkeypatch
    ) -> None:
        """키 변경 성공 시 텔레그램 audit alert 발송 (Notification row 생성)."""
        _patch_binance(monkeypatch)
        u = make_user()
        ea = make_exchange_account(user=u)

        update_credentials(
            exchange_account_id=ea.id,
            payload=ExchangeAccountCredentialsUpdate(
                api_key="audit-test-new-key-xx",
                api_secret="audit-test-new-secret-yy",
            ),
            db=db_session,
            user_id=u.id,
        )

        notifs = db_session.execute(
            select(Notification).where(Notification.title.like(f"%API 키 변경%#{ea.id}%"))
        ).scalars().all()
        assert len(notifs) == 1
        # 환경 전환 안 했으니 본문에 "환경 ... → ..." 없음
        assert "환경" not in notifs[0].body or "→" not in notifs[0].body or notifs[0].body.count("환경") == 1

    def test_passphrase_explicit_empty_clears(
        self, db_session, make_user, make_exchange_account, monkeypatch
    ) -> None:
        """passphrase="" 명시 시 NULL 처리. None 미지정과 다름."""
        _patch_binance(monkeypatch)
        u = make_user()
        ea = make_exchange_account(user=u)
        # 기존 passphrase 있다고 가정 — fixture default 가 None 이라 직접 채움
        from app.core.crypto import encrypt_text
        ea.passphrase_enc = encrypt_text("old-passphrase-value")
        db_session.commit()

        update_credentials(
            exchange_account_id=ea.id,
            payload=ExchangeAccountCredentialsUpdate(
                api_key="new-key-passphrase-test-x",
                api_secret="new-secret-passphrase-test-y",
                passphrase="",  # 명시적 빈 문자열 → NULL 처리
            ),
            db=db_session,
            user_id=u.id,
        )
        db_session.refresh(ea)
        assert ea.passphrase_enc is None
