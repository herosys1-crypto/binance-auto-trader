"""audit fix 회귀 — idempotency 4xx 캐시 + encryption_key startup 검증.

audit 발견 (2026-05-04):
- idempotency.py: < 500 캐시 → 4xx 에러도 1시간 캐시되어 사용자가 입력 고쳐도 같은 에러
- crypto.py: encryption_key='change_me' (default) 가 invalid Fernet key 인데 startup 검증 X
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.crypto import CryptoError, validate_encryption_key
from app.middleware.idempotency import IdempotencyMiddleware


# ============================================================================
# Idempotency: 4xx 는 캐시 안 함
# ============================================================================
class TestIdempotency4xxNotCached:
    def _build_request_response_pair(self, *, body: bytes, response_status: int, response_body: dict):
        """간단한 mock — middleware 의 dispatch 호출에 필요한 최소만.

        실제 ASGI 흐름은 모든 응답을 streaming 으로 wrapping 하므로 body_iterator 가 있음.
        테스트에선 StreamingResponse 로 비슷한 동작 시뮬레이션.
        """
        from starlette.responses import StreamingResponse

        request = MagicMock()
        request.method = "POST"
        request.headers = {"Idempotency-Key": "test-key-1"}
        request.body = AsyncMock(return_value=body)

        body_bytes = json.dumps(response_body).encode("utf-8")

        async def _body_gen():
            yield body_bytes

        async def _call_next(_req):
            return StreamingResponse(
                _body_gen(),
                status_code=response_status,
                media_type="application/json",
            )

        return request, _call_next

    @pytest.mark.parametrize("status_code", [200, 201, 204])
    def test_2xx_is_cached(self, status_code: int, monkeypatch) -> None:
        import asyncio
        asyncio.run(self._test_2xx_is_cached_impl(status_code, monkeypatch))

    async def _test_2xx_is_cached_impl(self, status_code: int, monkeypatch) -> None:
        """2xx 응답은 redis 에 캐시됨."""
        cached: dict = {}

        class _FakeRedis:
            def get(self, key):
                return cached.get(key)
            def setex(self, key, ttl, value):
                cached[key] = value

        monkeypatch.setattr("app.middleware.idempotency.get_redis_client", lambda: _FakeRedis())
        mw = IdempotencyMiddleware(app=MagicMock())
        request, call_next = self._build_request_response_pair(
            body=b'{"x":1}', response_status=status_code, response_body={"ok": True},
        )
        await mw.dispatch(request, call_next)
        assert "idempotency:test-key-1" in cached
        cached_data = json.loads(cached["idempotency:test-key-1"])
        assert cached_data["status_code"] == status_code

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422])
    def test_4xx_is_not_cached(self, status_code: int, monkeypatch) -> None:
        import asyncio
        asyncio.run(self._test_4xx_is_not_cached_impl(status_code, monkeypatch))

    async def _test_4xx_is_not_cached_impl(self, status_code: int, monkeypatch) -> None:
        """4xx 응답은 캐시되면 안 됨 — 사용자가 입력 고쳐서 재시도 시 새로 처리."""
        cached: dict = {}

        class _FakeRedis:
            def get(self, key):
                return cached.get(key)
            def setex(self, key, ttl, value):
                cached[key] = value

        monkeypatch.setattr("app.middleware.idempotency.get_redis_client", lambda: _FakeRedis())
        mw = IdempotencyMiddleware(app=MagicMock())
        request, call_next = self._build_request_response_pair(
            body=b'{"x":1}', response_status=status_code, response_body={"detail": "bad"},
        )
        await mw.dispatch(request, call_next)
        # 캐시되면 안 됨
        assert "idempotency:test-key-1" not in cached, (
            f"{status_code} 응답이 캐시됨 — 사용자가 입력 고쳐도 같은 에러 받음"
        )

    @pytest.mark.parametrize("status_code", [500, 502, 503])
    def test_5xx_is_not_cached(self, status_code: int, monkeypatch) -> None:
        import asyncio
        asyncio.run(self._test_5xx_is_not_cached_impl(status_code, monkeypatch))

    async def _test_5xx_is_not_cached_impl(self, status_code: int, monkeypatch) -> None:
        """5xx 응답도 캐시 안 함 — transient 가능."""
        cached: dict = {}

        class _FakeRedis:
            def get(self, key):
                return cached.get(key)
            def setex(self, key, ttl, value):
                cached[key] = value

        monkeypatch.setattr("app.middleware.idempotency.get_redis_client", lambda: _FakeRedis())
        mw = IdempotencyMiddleware(app=MagicMock())
        request, call_next = self._build_request_response_pair(
            body=b'{"x":1}', response_status=status_code, response_body={"detail": "err"},
        )
        await mw.dispatch(request, call_next)
        assert "idempotency:test-key-1" not in cached


# ============================================================================
# encryption_key startup 검증
# ============================================================================
class TestEncryptionKeyValidation:
    def test_default_change_me_raises(self, monkeypatch) -> None:
        monkeypatch.setattr("app.core.config.settings.encryption_key", "change_me")
        with pytest.raises(CryptoError) as ei:
            validate_encryption_key()
        assert "기본값" in str(ei.value)
        assert "Fernet" in str(ei.value)

    def test_change_dash_me_also_raises(self, monkeypatch) -> None:
        monkeypatch.setattr("app.core.config.settings.encryption_key", "change-me")
        with pytest.raises(CryptoError):
            validate_encryption_key()

    def test_empty_key_raises(self, monkeypatch) -> None:
        monkeypatch.setattr("app.core.config.settings.encryption_key", "")
        with pytest.raises(CryptoError):
            validate_encryption_key()

    def test_invalid_format_raises(self, monkeypatch) -> None:
        """랜덤 문자열은 Fernet key 형식이 아님 (URL-safe base64-encoded 32 bytes 필요)."""
        monkeypatch.setattr("app.core.config.settings.encryption_key", "this-is-not-a-fernet-key-just-a-random-string-12345")
        with pytest.raises(CryptoError) as ei:
            validate_encryption_key()
        assert "Fernet" in str(ei.value)

    def test_valid_fernet_key_passes(self, monkeypatch) -> None:
        from cryptography.fernet import Fernet
        monkeypatch.setattr("app.core.config.settings.encryption_key", Fernet.generate_key().decode())
        # raise 없이 통과
        validate_encryption_key()
