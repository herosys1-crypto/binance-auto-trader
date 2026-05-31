"""api_backoff — Binance rate limit / IP ban 감지 + 자동 skip (Layer 4).

배경 (2026-05-09 #120 사후): 178건 reconcile 실패 사고 — 같은 호출을 매 cycle
반복하던 것을 ban 감지 시 자동 skip 으로 전환.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.core.api_backoff import (
    ACCOUNT_INVALID_COOLDOWN_SECONDS,
    check_api_ban,
    maybe_record_ban_from_exc,
    parse_account_invalid_error,
    parse_rate_limit_error,
    record_account_invalid_ban,
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


# ============================================================================
# 2026-05-31 추가 — account invalid (-1109 류) 감지 + 1h 쿨다운
# ============================================================================
class TestParseAccountInvalidError:
    def test_code_minus_1109_detected(self):
        """code=-1109 (Binance Demo 차단 / 키 권한 미스 등) → 1h 후 ban_until."""
        e = Exception("Binance API error: status=400, code=-1109, msg=Invalid account.")
        result = parse_account_invalid_error(e)
        assert result is not None
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        delta_s = (result - now_ms) / 1000
        # 약 3600초 (1h) — 호출 시점 차이 고려해 wide window
        assert 3590 <= delta_s <= 3610

    def test_code_minus_2014_detected(self):
        """code=-2014 (API-key format invalid) → 동일 처리."""
        e = Exception("Binance API error: status=400, code=-2014, msg=API-key format invalid.")
        assert parse_account_invalid_error(e) is not None

    def test_code_minus_2015_detected(self):
        """code=-2015 (Invalid API-key, IP, or permissions) → 동일 처리."""
        e = Exception(
            "Binance API error: status=401, code=-2015, "
            "msg=Invalid API-key, IP, or permissions for action."
        )
        assert parse_account_invalid_error(e) is not None

    def test_keyword_invalid_account_caseinsensitive(self):
        """code 추출 못 해도 「invalid account」 키워드로 fallback 감지."""
        e = Exception("Some weird wrapper: INVALID ACCOUNT.")
        assert parse_account_invalid_error(e) is not None

    def test_rate_limit_error_returns_none(self):
        """-1003 / -418 등 rate limit 은 별도 함수 영역 — 여기선 None."""
        e = Exception("Binance API error: status=429, code=-1003, msg=Too many requests")
        assert parse_account_invalid_error(e) is None

    def test_other_error_returns_none(self):
        """일반 에러 (-4164 가격필터 등) → None."""
        e = Exception("Binance API error: status=400, code=-4164, msg=Order's notional too small")
        assert parse_account_invalid_error(e) is None

    def test_cooldown_constant_is_one_hour(self):
        """문서화된 1h cooldown 상수 확인 (회귀 방지)."""
        assert ACCOUNT_INVALID_COOLDOWN_SECONDS == 3600


class TestRecordAccountInvalidBan:
    def _fake_redis(self) -> tuple[MagicMock, dict]:
        """간단한 Redis stub — setex/get/delete 만 지원."""
        store = {}
        client = MagicMock()
        def _setex(key, ttl, value):
            store[key] = (value, ttl)
        def _get(key):
            v = store.get(key)
            return v[0].encode() if v else None
        def _delete(*keys):
            for k in keys:
                store.pop(k, None)
        client.setex.side_effect = _setex
        client.get.side_effect = _get
        client.delete.side_effect = _delete
        return client, store

    def test_record_and_check(self):
        """account-invalid ban 기록 → is_banned True 반환 (rate limit ban 과 같은 키)."""
        client, store = self._fake_redis()
        future_ms = int(datetime.now(timezone.utc).timestamp() * 1000) + 3600_000
        result = record_account_invalid_ban(client, 1, future_ms)
        assert result is True
        is_banned, _ = check_api_ban(client, 1)
        assert is_banned is True

    def test_telegram_message_contains_action_guide(self):
        """알림 메시지에 운영자 조치 가이드 포함 (rate limit 알림과 차별)."""
        client, _ = self._fake_redis()
        notif = MagicMock()
        future_ms = int(datetime.now(timezone.utc).timestamp() * 1000) + 3600_000
        record_account_invalid_ban(
            client, 1, future_ms, notification_service=notif,
            error_message="Invalid account.",
        )
        notif.send_system_alert.assert_called_once()
        body = notif.send_system_alert.call_args.kwargs.get("body") or notif.send_system_alert.call_args.args[1]
        # 운영자 조치 키워드 확인
        assert "운영자 조치" in body or "API 키" in body
        assert "Demo" in body or "demo" in body or "권한" in body  # Demo 정책 안내

    def test_telegram_dedup(self):
        """동일 ban 윈도우 내 중복 호출 → Telegram 한 번만."""
        client, _ = self._fake_redis()
        notif = MagicMock()
        future_ms = int(datetime.now(timezone.utc).timestamp() * 1000) + 3600_000
        record_account_invalid_ban(client, 1, future_ms, notification_service=notif)
        record_account_invalid_ban(client, 1, future_ms, notification_service=notif)
        assert notif.send_system_alert.call_count == 1


class TestMaybeRecordBanFromExcHandlesAccountInvalid:
    def _fake_redis(self) -> MagicMock:
        store = {}
        client = MagicMock()
        client.setex.side_effect = lambda k, ttl, v: store.update({k: v})
        client.get.side_effect = lambda k: store.get(k, "").encode() if store.get(k) else None
        client.delete.side_effect = lambda *ks: [store.pop(k, None) for k in ks]
        return client

    def test_rate_limit_caught_first(self, monkeypatch):
        """rate limit 우선 — short cooldown 적용."""
        client = self._fake_redis()
        e = Exception("Binance API error: status=429, code=-1003, msg=Too many requests")
        result = maybe_record_ban_from_exc(e, 1, redis_client=client)
        assert result is True
        is_banned, expiry = check_api_ban(client, 1)
        assert is_banned is True
        # rate limit = 60s 짧은 쿨다운
        delta_s = (expiry - int(datetime.now(timezone.utc).timestamp() * 1000)) / 1000
        assert 50 <= delta_s <= 70

    def test_account_invalid_caught_as_fallback(self):
        """rate limit 아니지만 -1109 면 account-invalid 분기 → 1h 쿨다운."""
        client = self._fake_redis()
        e = Exception("Binance API error: status=400, code=-1109, msg=Invalid account.")
        result = maybe_record_ban_from_exc(e, 1, redis_client=client)
        assert result is True
        is_banned, expiry = check_api_ban(client, 1)
        assert is_banned is True
        # account invalid = 1h 긴 쿨다운
        delta_s = (expiry - int(datetime.now(timezone.utc).timestamp() * 1000)) / 1000
        assert 3590 <= delta_s <= 3610

    def test_other_error_returns_false(self):
        """rate limit 도 account invalid 도 아닌 에러 → False (caller 가 평소 처리)."""
        client = self._fake_redis()
        e = Exception("Binance API error: status=400, code=-4164, msg=Order's notional too small")
        result = maybe_record_ban_from_exc(e, 1, redis_client=client)
        assert result is False
        is_banned, _ = check_api_ban(client, 1)
        assert is_banned is False
