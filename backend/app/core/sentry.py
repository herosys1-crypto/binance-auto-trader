from __future__ import annotations

from typing import Any

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from app.core.config import settings


def sentry_before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    request = event.get("request", {})
    url = request.get("url", "") or ""

    if "/health" in url or "/metrics" in url or "/admin/test-telegram" in url:
        return None

    exc_info = hint.get("exc_info")
    if exc_info:
        exc_type, exc_value, _ = exc_info
        status_code = getattr(exc_value, "status_code", None)
        if status_code in {401, 403, 404}:
            return None

        exc_name = getattr(exc_type, "__name__", "")
        if exc_name in {"BinanceAPIError", "RedisLockError"}:
            message = str(exc_value)
            noisy_markers = [
                "Idempotency-Key reused with different payload",
                "Invalid credentials",
            ]
            if any(marker in message for marker in noisy_markers):
                return None

    headers = request.get("headers", {})
    if "authorization" in headers:
        headers["authorization"] = "[Filtered]"
    if "cookie" in headers:
        headers["cookie"] = "[Filtered]"
    request["headers"] = headers
    event["request"] = request
    return event


def init_sentry() -> None:
    if not settings.sentry_dsn:
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        integrations=[FastApiIntegration(), SqlalchemyIntegration()],
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        before_send=sentry_before_send,
        send_default_pii=False,
    )
