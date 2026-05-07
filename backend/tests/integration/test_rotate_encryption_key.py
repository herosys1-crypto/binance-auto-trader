"""scripts/rotate_encryption_key.py 의 rotate() / restore() 단위 검증.

배경 (MAINNET-CHECKLIST.md 1-3): mainnet 전 ENCRYPTION_KEY 회전 시 데이터 손실 위험
방지 — 회전 로직이 옛 cipher 를 정확히 새 cipher 로 변환하고, 백업으로 복원 가능한지
사전 검증.
"""
from __future__ import annotations

import os
import sys

import pytest
from cryptography.fernet import Fernet

# scripts/ 를 import path 에 추가
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_SCRIPTS = os.path.join(_BACKEND_ROOT, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from app.models.exchange_account import ExchangeAccount  # noqa: E402
from app.models.user import User  # noqa: E402
from rotate_encryption_key import ENCRYPTED_COLUMNS, restore, rotate  # noqa: E402


def _make_user(db) -> User:
    u = User(
        email="rt@example.com",
        password_hash="x",
        full_name="rotate test user",
        role="admin",
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_account(db, user_id: int, fernet: Fernet, *, with_passphrase: bool = False) -> ExchangeAccount:
    """fernet 으로 암호화된 자격증명 row 1개 생성."""
    a = ExchangeAccount(
        user_id=user_id,
        exchange_name="binance",
        market_type="usds_m_futures",
        api_key_enc=fernet.encrypt(b"plain-api-key-for-rotation-test").decode("utf-8"),
        api_secret_enc=fernet.encrypt(b"plain-api-secret-for-rotation-test").decode("utf-8"),
        passphrase_enc=(
            fernet.encrypt(b"plain-passphrase").decode("utf-8") if with_passphrase else None
        ),
        is_testnet=True,
        is_active=True,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


class TestRotateEncryptionKey:
    def test_rotate_dry_run_no_db_change(self, db_session) -> None:
        """dry_run 시 DB 의 cipher 가 변경되지 않아야 함."""
        old_key = Fernet.generate_key().decode("utf-8")
        new_key = Fernet.generate_key().decode("utf-8")
        old_f = Fernet(old_key.encode())
        new_f = Fernet(new_key.encode())

        u = _make_user(db_session)
        a = _make_account(db_session, u.id, old_f, with_passphrase=True)
        old_api_key_enc = a.api_key_enc
        old_secret_enc = a.api_secret_enc
        old_pass_enc = a.passphrase_enc

        result = rotate(db_session, old_f, new_f, dry_run=True)
        db_session.rollback()  # 스크립트와 동일 — dry-run 시 caller 가 rollback

        assert result["rows"] == 1
        assert len(result["rotated"]) == 1
        assert len(result["failed"]) == 0

        # DB 는 그대로
        db_session.refresh(a)
        assert a.api_key_enc == old_api_key_enc
        assert a.api_secret_enc == old_secret_enc
        assert a.passphrase_enc == old_pass_enc

    def test_rotate_real_change_decryptable_with_new_key(self, db_session) -> None:
        """실 회전 후 새 키로 복호화한 plain 이 원래 plain 과 같아야."""
        old_key = Fernet.generate_key().decode("utf-8")
        new_key = Fernet.generate_key().decode("utf-8")
        old_f = Fernet(old_key.encode())
        new_f = Fernet(new_key.encode())

        u = _make_user(db_session)
        a = _make_account(db_session, u.id, old_f, with_passphrase=True)

        result = rotate(db_session, old_f, new_f, dry_run=False)
        db_session.commit()
        assert len(result["failed"]) == 0

        db_session.refresh(a)
        # 새 키로 복호화 시 원래 plain
        assert new_f.decrypt(a.api_key_enc.encode()).decode() == "plain-api-key-for-rotation-test"
        assert new_f.decrypt(a.api_secret_enc.encode()).decode() == "plain-api-secret-for-rotation-test"
        assert new_f.decrypt(a.passphrase_enc.encode()).decode() == "plain-passphrase"

        # 옛 키로는 복호화 실패해야 (회전 완료 입증)
        from cryptography.fernet import InvalidToken
        with pytest.raises(InvalidToken):
            old_f.decrypt(a.api_key_enc.encode())

    def test_rotate_passphrase_null_preserved(self, db_session) -> None:
        """passphrase_enc=NULL 은 회전 후에도 NULL 유지."""
        old_key = Fernet.generate_key().decode("utf-8")
        new_key = Fernet.generate_key().decode("utf-8")
        old_f = Fernet(old_key.encode())
        new_f = Fernet(new_key.encode())

        u = _make_user(db_session)
        a = _make_account(db_session, u.id, old_f, with_passphrase=False)

        rotate(db_session, old_f, new_f, dry_run=False)
        db_session.commit()
        db_session.refresh(a)
        assert a.passphrase_enc is None

    def test_rotate_old_key_mismatch_fails_and_db_unchanged(self, db_session) -> None:
        """옛 키 불일치 시 failed 에 기록 + 새 키로 변경 안 됨."""
        old_key = Fernet.generate_key().decode("utf-8")
        wrong_old_key = Fernet.generate_key().decode("utf-8")  # 의도적 불일치
        new_key = Fernet.generate_key().decode("utf-8")
        old_f = Fernet(old_key.encode())
        wrong_f = Fernet(wrong_old_key.encode())
        new_f = Fernet(new_key.encode())

        u = _make_user(db_session)
        a = _make_account(db_session, u.id, old_f, with_passphrase=False)
        original_api_key_enc = a.api_key_enc

        # 잘못된 옛 키로 회전 시도
        result = rotate(db_session, wrong_f, new_f, dry_run=False)
        db_session.rollback()

        assert len(result["failed"]) >= 1
        assert all("decrypt" in f["error"] for f in result["failed"])
        assert len(result["rotated"]) == 0

        db_session.refresh(a)
        assert a.api_key_enc == original_api_key_enc  # 변경 없음

    def test_rotate_multiple_accounts(self, db_session) -> None:
        """여러 row 모두 회전."""
        old_key = Fernet.generate_key().decode("utf-8")
        new_key = Fernet.generate_key().decode("utf-8")
        old_f = Fernet(old_key.encode())
        new_f = Fernet(new_key.encode())

        u = _make_user(db_session)
        accounts = [_make_account(db_session, u.id, old_f) for _ in range(3)]

        result = rotate(db_session, old_f, new_f, dry_run=False)
        db_session.commit()
        assert result["rows"] == 3
        assert len(result["rotated"]) == 3
        assert len(result["failed"]) == 0

        for a in accounts:
            db_session.refresh(a)
            assert new_f.decrypt(a.api_key_enc.encode()).decode() == "plain-api-key-for-rotation-test"

    def test_restore_recovers_old_cipher(self, db_session, tmp_path) -> None:
        """rotate → restore 사이클: 백업으로 옛 cipher 복원."""
        import json

        old_key = Fernet.generate_key().decode("utf-8")
        new_key = Fernet.generate_key().decode("utf-8")
        old_f = Fernet(old_key.encode())
        new_f = Fernet(new_key.encode())

        u = _make_user(db_session)
        a = _make_account(db_session, u.id, old_f, with_passphrase=True)
        original_ciphers = {col: getattr(a, col) for col in ENCRYPTED_COLUMNS}

        # 1) 회전 + 백업 저장
        result = rotate(db_session, old_f, new_f, dry_run=False)
        db_session.commit()

        backup_path = tmp_path / "backup.json"
        backup_path.write_text(
            json.dumps({"schema_version": 1, "accounts": result["rotated"]}),
            encoding="utf-8",
        )

        # 2) 새 키로 복호화 가능 확인
        db_session.refresh(a)
        assert new_f.decrypt(a.api_key_enc.encode()).decode() == "plain-api-key-for-rotation-test"

        # 3) restore 로 옛 cipher 되돌리기
        r = restore(db_session, str(backup_path))
        db_session.commit()
        assert r["restored"] == 1
        assert r["missing"] == []

        db_session.refresh(a)
        for col in ENCRYPTED_COLUMNS:
            assert getattr(a, col) == original_ciphers[col]
        # 옛 키로 다시 복호화 가능
        assert old_f.decrypt(a.api_key_enc.encode()).decode() == "plain-api-key-for-rotation-test"

    def test_rotate_zero_rows(self, db_session) -> None:
        """ExchangeAccount 가 0 row 면 정상 종료 (rotated=[])."""
        old_key = Fernet.generate_key().decode("utf-8")
        new_key = Fernet.generate_key().decode("utf-8")
        result = rotate(
            db_session,
            Fernet(old_key.encode()),
            Fernet(new_key.encode()),
            dry_run=False,
        )
        assert result == {"rows": 0, "rotated": [], "failed": []}
