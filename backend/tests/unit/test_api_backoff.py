"""api_backoff — Binance rate limit / IP ban 감지 + 자동 skip (Layer 4).

배경 (2026-05-09 #120 사후): 178건 reconcile 실패 사고 — 같은 호출을 매 cycle
반복하던 것을 ban 감지 시 자동 skip 으로 전환.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.core.api_backoff import (
    check_api_ban,
    parse_rate_limit_error,
    record_api_ban,
    reset_api_ban,
)


class TestParseRateLimitError:
    def test_status_418_with_explicit_ban_until(self):
        """status=418 + 「banned until <ms>」 → 명시 시각 추출."""
        e = Exception(
            "Binance API error: status=418, code=-1003, "
            "msg=Way too many requests; IP(130.176.187.74) banned until 1778277772630."
        )
        result = parse_rate_limit_error(e)
        assert result == 1778277772630

    def test_status_429_without_banned_msg(self):
        """status=429 만 — 만료 시각 없음 → 60s 후 default."""
        e = Exception(
            "Binance API error: status=429, code=-1003, "
            "msg=Too many requests; current limit of IP(130.176.187.73) is 6000 requests per minute."
        )
        result = parse_rate_limit_error(e)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        # ~60s 후 (정확한 시각 비교 X — 테스트 시각 차이 고려)
        assert result is not None
        assert now_ms < result <= now_ms + 65_000

    def test_non_rate_limit_returns_none(self):
        """일반 에러 (rate limit 아님) → None."""
        e = Exception("Binance API error: status=400, code=-2010, msg=Order does not exist")
        assert parse_rate_limit_error(e) is None

    def test_code_minus_1003_lowercase(self):
        """code=-1003 + lowercase 「too many requests」 매칭."""
        e = Exception("status=429 code=-1003 msg=too many requests")
        result = parse_rate_limit_error(e)
        assert result is not None  # 60s default

    def test_banned_keyword_matches(self):
        """「banned」 키워드만 있어도 rate limit 으로 분류."""
        e = Exception("IP(130.176.187.74) banned until 1778277772630")
        result = parse_rate_limit_error(e)
        assert result == 1778277772630


class TestCheckAndRecordApiBan:
    def _fake_redis(self):
        """간단한 in-memory Redis fake."""
        store = {}
        ttls = {}
        client = MagicMock()
        client.setex = lambda key, ttl, value: store.update({key: str(value)}) or ttls.update({key: ttl}) or True
        client.get = lambda key: store.get(key)
        client.delete = lambda key: (store.pop(key, None), ttls.pop(key, None))
        return client, store

    def test_no_ban_initially(self):
        client, _ = self._fake_redis()
        is_banned, expiry = check_api_ban(client, account_id=1)
        assert is_banned is False
        assert expiry is None

    def test_record_ban_then_check_returns_banned(self):
        client, store = self._fake_redis()
        future_ms = int(datetime.now(timezone.utc).timestamp() * 1000) + 60_000  # 60s 후
        recorded = record_api_ban(client, account_id=1, expiry_ms=future_ms)
        assert recorded is True

        is_banned, expiry = check_api_ban(client, account_id=1)
        assert is_banned is True
        assert expiry == future_ms

    def test_expired_ban_auto_cleared(self):
        client, store = self._fake_redis()
        # 과거 시각으로 ban 마킹
        past_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - 60_000
        store["api_backoff:account:1:ban_until_ms"] = str(past_ms)

        is_banned, expiry = check_api_ban(client, account_id=1)
        assert is_banned is False  # 만료
        assert expiry is None

    def test_telegram_notified_only_once(self):
        client, _ = self._fake_redis()
        notif = MagicMock()
        future_ms = int(datetime.now(timezone.utc).timestamp() * 1000) + 60_000

        # 1회: 알림 발송
        first = record_api_ban(client, 1, future_ms, notification_service=notif)
        assert first is True
        assert notif.send_system_alert.call_count == 1

        # 2회: 같은 ban → 알림 skip (cooldown)
        second = record_api_ban(client, 1, future_ms, notification_service=notif)
        assert second is False
        assert notif.send_system_alert.call_count == 1  # 그대로

    def test_reset_clears_ban(self):
        client, _ = self._fake_redis()
        future_ms = int(datetime.now(timezone.utc).timestamp() * 1000) + 60_000
        record_api_ban(client, 1, future_ms)
        is_banned, _ = check_api_ban(client, 1)
        assert is_banned is True

        reset_api_ban(client, 1)
        is_banned, _ = check_api_ban(client, 1)
        assert is_banned is False

    def test_redis_none_safe_noop(self):
        """Redis 미접속 환경 — 모든 함수가 안전하게 no-op."""
        is_banned, expiry = check_api_ban(None, 1)
        assert is_banned is False
        assert expiry is None

        result = record_api_ban(None, 1, 1234567890000)
        assert result is False

        reset_api_ban(None, 1)  # 예외 없음
