"""Binance 공식 API CHANGELOG / 공지 자동 모니터링 worker.

배경 (2026-06-01 사장님 mainnet 첫날 사고 후속):
Binance 가 2026-04-23 에 WebSocket private endpoint 를 /ws/ → /private/ws/ 로
마이그레이션. 우리가 testnet 운영 중 이 공지를 인지 못 함 → mainnet 진입 시
모든 user-stream 문제 한꺼번에 가시화 (PENDING 머무름, realized_pnl=0, 통계 부정확
등 chain). 같은 사고 재발 방지를 위한 자동 모니터링.

동작:
- 매 6시간 주기로 Binance 공식 changelog 페이지 GET 호출
- 본문 hash 와 Redis 에 저장된 이전 hash 비교
- 변경 감지 시 Telegram 「🚨 [Binance API 변경 감지]」 알림 + URL
- 운영자가 직접 확인 → 필요 시 코드 변경

폴링 부담 최소화:
- 6시간 = 하루 4회 (Binance 측 부담 없음)
- HTTP GET 만 (인증 불필요)
- 30일 hash 캐시 TTL
"""
from __future__ import annotations

import hashlib
import logging
from typing import Iterable

import requests

from app.core.redis_client import get_redis_client
from app.observability.sentry import capture_strategy_event
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


# Binance 공식 changelog / 공지 페이지 (각각 hash 비교).
# 추가 가능: WebSocket Change Notice, REST API endpoints 등 자주 바뀌는 페이지.
_MONITORED_URLS: tuple[tuple[str, str], ...] = (
    (
        "binance_futures_changelog",
        "https://developers.binance.com/docs/derivatives/usds-margined-futures/CHANGELOG",
    ),
    (
        "binance_websocket_change_notice",
        "https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Important-WebSocket-Change-Notice",
    ),
)

_HASH_KEY_TPL = "binance_changelog:hash:{name}"
_HASH_TTL_SEC = 86400 * 30  # 30일


def _fetch_hash(url: str) -> str | None:
    """페이지 GET → 본문 sha256 hash 반환. 실패 시 None."""
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "binance-auto-trader/1.0"})
        r.raise_for_status()
        return hashlib.sha256(r.text.encode("utf-8")).hexdigest()
    except Exception as e:
        logger.warning("[binance-monitor] fetch failed url=%s err=%s", url, e)
        return None


def run_binance_changelog_monitor_once() -> None:
    """1회 실행: 모든 모니터 대상 URL 의 hash 비교 + 변경 감지 시 Telegram 알림.

    scheduler 가 매 6시간 호출. 첫 실행은 hash 만 저장하고 알림 X (false alarm 방지).
    """
    try:
        redis = get_redis_client()
    except Exception as e:
        logger.warning("[binance-monitor] redis unavailable: %s", e)
        return

    changes_detected: list[tuple[str, str]] = []

    for name, url in _MONITORED_URLS:
        cur_hash = _fetch_hash(url)
        if cur_hash is None:
            continue  # fetch 실패 → 다음 cycle 재시도

        key = _HASH_KEY_TPL.format(name=name)
        try:
            prev_hash_raw = redis.get(key)
        except Exception as e:
            logger.warning("[binance-monitor] redis get failed: %s", e)
            continue

        prev_hash = prev_hash_raw.decode() if isinstance(prev_hash_raw, bytes) else prev_hash_raw

        if prev_hash is None:
            # 첫 실행 — hash 저장만, 알림 X
            redis.set(key, cur_hash, ex=_HASH_TTL_SEC)
            logger.info("[binance-monitor] first run, hash stored name=%s", name)
            continue

        if prev_hash != cur_hash:
            # 변경 감지!
            changes_detected.append((name, url))
            redis.set(key, cur_hash, ex=_HASH_TTL_SEC)
            logger.warning("[binance-monitor] CHANGE DETECTED name=%s url=%s", name, url)
        else:
            # 변경 없음 — TTL refresh (30일 유지)
            redis.expire(key, _HASH_TTL_SEC)

    if changes_detected:
        _notify_changes(changes_detected)


def _notify_changes(changes: Iterable[tuple[str, str]]) -> None:
    """변경 감지된 페이지 목록 → Telegram 알림 1건 (dedup 불필요 — 6h 주기라 자연 throttle)."""
    items = list(changes)
    if not items:
        return
    title = f"🚨 [Binance API 변경 감지] {len(items)}건"
    body_lines = [
        "Binance 공식 문서가 변경되었습니다. 우리 시스템에 영향 가능 — 즉시 확인 권장.",
        "",
        "**변경된 페이지:**",
    ]
    for name, url in items:
        body_lines.append(f"  • {name}")
        body_lines.append(f"    {url}")
    body_lines.extend([
        "",
        "**확인 절차:**",
        "1. 위 URL 직접 방문 → 변경 내용 검토",
        "2. WebSocket endpoint, REST path, 권한 등 breaking change 여부 확인",
        "3. 영향 있으면 task 추가 + 코드 변경 + testnet 검증 후 mainnet 적용",
        "",
        "💡 2026-04-23 마이그레이션 같은 사고 재발 방지용 자동 알림입니다.",
    ])
    body = "\n".join(body_lines)
    try:
        # Notification 은 DB session 필요 — 가벼운 alert 전용 경로 사용.
        # session 없이 호출 가능하도록 NotificationService 사용 패턴 확인 필요.
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            NotificationService(db).send_system_alert(title=title, body=body)
        finally:
            db.close()
        logger.info("[binance-monitor] alert sent: %d page(s)", len(items))
    except Exception as e:
        logger.exception("[binance-monitor] alert send failed: %s", e)
        try:
            capture_strategy_event(
                f"Binance changelog alert send failed: {e}",
                level="error",
                tags={"event_type": "BINANCE_MONITOR_ALERT_FAIL"},
            )
        except Exception:
            pass


if __name__ == "__main__":
    # 수동 1회 실행 (디버그)
    import sys
    logging.basicConfig(level=logging.INFO)
    run_binance_changelog_monitor_once()
    sys.exit(0)
