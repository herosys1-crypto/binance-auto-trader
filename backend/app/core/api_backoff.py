"""Binance API rate limit / IP ban 자동 backoff (Layer 4, 2026-05-09).

배경 (#120 사후): Binance 가 status=418 (IP banned) / 429 (Too Many Requests)
응답 시 메시지에 「banned until <timestamp_ms>」 포함. 우리는 이 신호를 감지해
다음 호출들을 ban 만료까지 자동 skip 해야 함. 이전엔 매 cycle 같은 호출 시도 →
실패 → RiskEvent 누적 → 178건/24h.

설계:
- ExchangeAccount 별 (account_id 기준) Redis 키에 ban 만료 시각 저장
- 호출 전: check_api_ban() 으로 ban 상태 확인 — banned 면 caller 가 skip
- 호출 실패 시: parse_rate_limit_error() 가 429/418 인지 + ban 만료 시각 추출
- record_api_ban() 으로 Redis 마킹 + Telegram 알림 1회 (반복 알림 방지)

사용 예 (reconcile_worker):
    is_banned, expiry = check_api_ban(redis_client, account.id)
    if is_banned:
        skip_this_cycle()
    try:
        client.get_position_risk()
    except Exception as e:
        ban_until = parse_rate_limit_error(e)
        if ban_until:
            record_api_ban(redis_client, account.id, ban_until, notification_service)
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Redis key — account 별 ban 만료 시각 (ms epoch). TTL 자동 만료로 cleanup.
_BAN_KEY = "api_backoff:account:{account_id}:ban_until_ms"
# 같은 ban 이벤트에 대해 Telegram 한 번만 발송 (cooldown 키)
_NOTIFY_KEY = "api_backoff:account:{account_id}:notified"

# Binance ban / rate limit 패턴
# - status=418: IP banned ("banned until 1778277772630")
# - status=429: Too Many Requests
# - code=-1003: Way too many requests / Too many requests
_BAN_RE = re.compile(r"banned\s+until\s+(\d{13})", re.IGNORECASE)
_STATUS_RE = re.compile(r"status\s*=\s*(\d{3})")
_CODE_RE = re.compile(r"code\s*=\s*(-?\d+)")


def parse_rate_limit_error(exc: Exception) -> Optional[int]:
    """Exception 에서 ban 만료 시각 (ms epoch) 추출.

    Returns:
        - ban 만료 ms epoch (int) — 명시적 ban 시각 있는 경우
        - 60_000ms 후 (now + 60s) — rate limit 이지만 만료 시각 없는 경우 (보수적)
        - None — rate limit 아님 (다른 에러)
    """
    msg = str(exc)
    status_match = _STATUS_RE.search(msg)
    code_match = _CODE_RE.search(msg)
    status = int(status_match.group(1)) if status_match else None
    code = int(code_match.group(1)) if code_match else None

    is_rate_limit = (
        status in (418, 429)
        or code == -1003
        or "too many requests" in msg.lower()
        or "banned" in msg.lower()
    )
    if not is_rate_limit:
        return None

    # 1순위: 명시적 「banned until <ms>」
    ban_match = _BAN_RE.search(msg)
    if ban_match:
        return int(ban_match.group(1))

    # 2순위: rate limit 이지만 만료 명시 없음 → 보수적으로 60s skip
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return now_ms + 60_000


def check_api_ban(redis_client, account_id: int) -> tuple[bool, Optional[int]]:
    """현재 ban 상태 확인.

    Returns:
        (is_banned, expiry_ms) — ban 중이면 (True, 만료 ms), 아니면 (False, None)
    """
    if redis_client is None:
        return False, None
    try:
        raw = redis_client.get(_BAN_KEY.format(account_id=account_id))
        if not raw:
            return False, None
        try:
            expiry_ms = int(raw)
        except (ValueError, TypeError):
            return False, None
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        if now_ms >= expiry_ms:
            # 만료 — Redis 정리
            try:
                redis_client.delete(_BAN_KEY.format(account_id=account_id))
                redis_client.delete(_NOTIFY_KEY.format(account_id=account_id))
            except Exception:
                pass
            return False, None
        return True, expiry_ms
    except Exception as e:
        logger.warning("check_api_ban failed: %s", e)
        return False, None


def record_api_ban(
    redis_client,
    account_id: int,
    expiry_ms: int,
    *,
    notification_service=None,
    error_message: str = "",
) -> bool:
    """ban 마킹 + 첫 발생 시 Telegram 알림 1회.

    Returns:
        True — 새로 마킹 (Telegram 발송됨)
        False — 이미 마킹된 상태 (Telegram skip)
    """
    if redis_client is None:
        return False
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    ttl_seconds = max(1, (expiry_ms - now_ms) // 1000 + 5)  # 5s 여유
    try:
        ban_key = _BAN_KEY.format(account_id=account_id)
        notify_key = _NOTIFY_KEY.format(account_id=account_id)
        redis_client.setex(ban_key, ttl_seconds, str(expiry_ms))

        # Telegram 1회 알림 (이미 보냈으면 skip)
        already_notified = redis_client.get(notify_key)
        if already_notified:
            return False
        redis_client.setex(notify_key, ttl_seconds, "1")
        if notification_service is not None:
            try:
                expiry_dt = datetime.fromtimestamp(expiry_ms / 1000, tz=timezone.utc)
                minutes_left = max(1, ttl_seconds // 60)
                notification_service.send_system_alert(
                    title=f"⚠️ [Binance API Ban] account #{account_id}",
                    body="\n".join([
                        f"⛔ Rate limit / IP ban 감지 — 다음 호출들 자동 skip",
                        f"⏱ 만료 시각  : {expiry_dt.strftime('%H:%M:%S UTC')}",
                        f"⏳ 남은 시간  : 약 {minutes_left}분",
                        f"📡 Stream    : 영향 없음 (websocket 별도)",
                        f"📝 원인 메시지: {error_message[:200]}",
                        "",
                        "🔧 자동 동작:",
                        "  • reconcile / orphan detection 일시 중단",
                        "  • 만료 시 자동 재개",
                        "  • 진행 중 거래는 stream 으로 정상 처리",
                    ]),
                )
                logger.warning(
                    "API ban recorded: account=%s expiry=%s (%ds)",
                    account_id, expiry_dt.isoformat(), ttl_seconds,
                )
            except Exception as e:
                logger.error("API ban notification failed: %s", e)
        return True
    except Exception as e:
        logger.error("record_api_ban failed: %s", e)
        return False


def reset_api_ban(redis_client, account_id: int) -> None:
    """수동 reset — 운영자가 강제로 ban 해제 (Redis 키만 삭제)."""
    if redis_client is None:
        return
    try:
        redis_client.delete(_BAN_KEY.format(account_id=account_id))
        redis_client.delete(_NOTIFY_KEY.format(account_id=account_id))
    except Exception as e:
        logger.warning("reset_api_ban failed: %s", e)


# ---------------------------------------------------------------------------
# 워커용 편의 헬퍼 (2026-05-17 — rate limit ban 스파이럴 사후).
#
# 배경: 기존엔 check_api_ban 가드가 reconcile_worker 에만 적용되어 있어,
# tp_sl / stage_trigger / auto_reentry 워커는 ban 윈도우 중에도 10초마다
# 거래소 호출을 계속 시도 → Binance 가 ban 기간 요청을 카운트해 418 을
# 연장/승격 (2분 → 13분 → ...). 아래 헬퍼로 모든 워커가 동일하게 cycle skip.
# ---------------------------------------------------------------------------

def is_account_banned(account_id: int, redis_client=None) -> bool:
    """이 account 가 현재 ban 중인지 — True 면 caller 는 이 strategy/cycle skip.

    redis_client 생략 시 자동 획득 (실패해도 False — fail-open).
    """
    try:
        client = redis_client
        if client is None:
            from app.core.redis_client import get_redis_client
            client = get_redis_client()
        banned, _ = check_api_ban(client, account_id)
        return banned
    except Exception as e:  # pragma: no cover — redis 장애 시 거래 막지 않음
        logger.warning("is_account_banned check failed (fail-open): %s", e)
        return False


def maybe_record_ban_from_exc(
    exc: Exception,
    account_id: int,
    *,
    redis_client=None,
    notification_service=None,
) -> bool:
    """Exception 이 rate limit/ban 이면 Redis 마킹 + Telegram 1회.

    Returns:
        True  — rate limit 으로 판단해 ban 기록함 (caller 는 이번 cycle 의
                해당 account strategy 들을 모두 skip 권장)
        False — rate limit 아님 (다른 에러 — caller 가 평소대로 처리)
    """
    try:
        ban_until = parse_rate_limit_error(exc)
        if ban_until is None:
            return False
        client = redis_client
        if client is None:
            from app.core.redis_client import get_redis_client
            client = get_redis_client()
        record_api_ban(
            client, account_id, ban_until,
            notification_service=notification_service,
            error_message=str(exc),
        )
        return True
    except Exception as e:  # pragma: no cover
        logger.warning("maybe_record_ban_from_exc failed: %s", e)
        return False


__all__ = [
    "check_api_ban",
    "parse_rate_limit_error",
    "record_api_ban",
    "reset_api_ban",
    "is_account_banned",
    "maybe_record_ban_from_exc",
]
