from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class CryptoError(Exception):
    pass


def validate_encryption_key() -> None:
    """startup 시점에 encryption_key 가 valid Fernet key 인지 확인.

    2026-05-04 audit: 기본값 'change_me' 가 invalid Fernet key 라 첫 encrypt 시점에
    crash 됐음. 운영 시 재시작 후 한참 뒤 첫 거래 시점에 발견되는 문제 → 즉시 fail.
    main.py 에서 init_sentry() 직후 호출.
    """
    if not settings.encryption_key or settings.encryption_key in ("change_me", "change-me"):
        raise CryptoError(
            "ENCRYPTION_KEY 가 기본값 ('change_me') 입니다. .env 에 valid Fernet key 설정 필요. "
            "키 생성: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        Fernet(settings.encryption_key.encode("utf-8"))
    except Exception as e:
        raise CryptoError(
            f"ENCRYPTION_KEY 가 valid Fernet key 가 아닙니다 (URL-safe base64-encoded 32 bytes 필요): {e}. "
            "키 생성: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        ) from e


def _get_fernet() -> Fernet:
    try:
        return Fernet(settings.encryption_key.encode("utf-8"))
    except Exception as e:
        raise CryptoError(f"Invalid encryption key: {e}") from e


def encrypt_text(plain_text: str) -> str:
    if not plain_text:
        raise CryptoError("plain_text is empty")
    fernet = _get_fernet()
    token = fernet.encrypt(plain_text.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_text(cipher_text: str) -> str:
    if not cipher_text:
        raise CryptoError("cipher_text is empty")
    fernet = _get_fernet()
    try:
        plain = fernet.decrypt(cipher_text.encode("utf-8"))
    except InvalidToken as e:
        raise CryptoError("Failed to decrypt: invalid token") from e
    return plain.decode("utf-8")
