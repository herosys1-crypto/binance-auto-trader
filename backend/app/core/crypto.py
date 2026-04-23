from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class CryptoError(Exception):
    pass


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
