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


# ============================================================================
# 구조화된 캡처 헬퍼
# ============================================================================
# Sentry 알림을 strategy_id / symbol / side / account_id 로 필터링할 수 있도록
# tag 를 통일된 형식으로 부착한다. DSN 미설정 환경에서는 sentry_sdk 자체가
# no-op 이라 안전하게 호출 가능 (init 안 했어도 capture_* 가 silently 종료).
#
# 사용 예:
#   capture_strategy_event(
#       "Emergency close place_market_order failed",
#       level="error",
#       strategy_id=strategy.id, symbol=strategy.symbol, side=strategy.side,
#       account_id=strategy.exchange_account_id, error=e,
#       extras={"quantity": str(quantity)},
#   )
def capture_strategy_event(
    message: str,
    *,
    level: str = "error",
    strategy_id: int | None = None,
    symbol: str | None = None,
    side: str | None = None,
    account_id: int | None = None,
    error: BaseException | None = None,
    extras: dict[str, Any] | None = None,
    tags: dict[str, str] | None = None,
) -> None:
    """Sentry 에 구조화된 이벤트 기록. DSN 미설정 시 no-op."""
    try:
        # sentry-sdk 2.x: push_scope 가 deprecated → new_scope 사용.
        with sentry_sdk.new_scope() as scope:
            if strategy_id is not None:
                scope.set_tag("strategy_id", str(strategy_id))
            if symbol:
                scope.set_tag("symbol", symbol)
            if side:
                scope.set_tag("side", side)
            if account_id is not None:
                scope.set_tag("account_id", str(account_id))
            scope.set_tag("component", "binance_auto_trader")
            if tags:
                for k, v in tags.items():
                    scope.set_tag(k, str(v))
            if extras:
                for k, v in extras.items():
                    scope.set_extra(k, v)
            scope.level = level  # type: ignore[assignment]
            if error is not None:
                sentry_sdk.capture_exception(error)
            else:
                sentry_sdk.capture_message(message, level=level)  # type: ignore[arg-type]
    except Exception:
        # Sentry 자체 장애로 메인 흐름이 깨지면 안 됨 — silently swallow.
        pass
