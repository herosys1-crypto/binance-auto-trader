"""Binance 공식 API CHANGELOG / 공지 자동 모니터링 worker.

배경 (2026-06-01 사장님 mainnet 첫날 사고 후속):
Binance 가 2026-04-23 에 WebSocket private endpoint 를 /ws/ → /private/ws/ 로
마이그레이션. 우리가 testnet 운영 중 이 공지를 인지 못 함 → mainnet 진입 시
모든 user-stream 문제 한꺼번에 가시화 (PENDING 머무름, realized_pnl=0, 통계 부정확
등 chain). 같은 사고 재발 방지를 위한 자동 모니터링.

동작 (v2 — 2026-06-05 사장님 부담 감소):
- 매 6시간 주기로 Binance 공식 changelog 페이지 GET 호출
- 본문 hash 와 Redis 에 저장된 이전 hash 비교
- 변경 감지 시:
  • Dedup 24h: 같은 페이지 이미 알림 보냈으면 skip (사장님 동일 알림 반복 부담 X)
  • Diff 추출: 이전 본문 vs 신규 본문의 변경된 라인 (추가/제거, 최대 15줄씩)
  • 영향 자동 평가: 핵심 키워드 매칭 → "⚠️ 영향 가능" vs "✓ 영향 없음 추정"
  • Telegram 알림에 모든 detail 포함 → 사장님이 URL 안 가도 즉시 판단

폴링 부담 최소화:
- 6시간 = 하루 4회 (Binance 측 부담 없음)
- HTTP GET 만 (인증 불필요)
- 30일 hash + body 캐시 TTL
"""
from __future__ import annotations

import hashlib
import logging
from typing import Iterable

import requests

from app.core.redis_client import get_redis_client
from app.core.sentry import capture_strategy_event
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
_BODY_KEY_TPL = "binance_changelog:body:{name}"
_ALERT_SENT_KEY_TPL = "binance_changelog:alert_sent:{name}"
_HASH_TTL_SEC = 86400 * 30  # 30일
_ALERT_DEDUP_SEC = 86400    # 24h — 같은 페이지 알림 dedup 기간

# 2026-06-05 v2: 영향 자동 평가용 키워드 (소문자 매칭).
# diff 에 이 단어가 포함되면 = "⚠️ 영향 가능" 평가.
# 사장님이 alert 받자마자 우선순위 판단 가능 (URL 안 가도).
_IMPACT_KEYWORDS = (
    "endpoint", "deprecat", "listenkey", "breaking",
    "migration", "removed", "deleted", "discontinu", "blocked",
    "2026", "april 23", "no longer", "shutdown", "websocket",
    "userdatastream", "userstream",
)


def _fetch_page(url: str) -> tuple[str | None, str | None]:
    """페이지 GET → (sha256 hash, 본문 text) 반환. 실패 시 (None, None)."""
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "binance-auto-trader/1.0"})
        r.raise_for_status()
        body = r.text
        h = hashlib.sha256(body.encode("utf-8")).hexdigest()
        return h, body
    except Exception as e:
        logger.warning("[binance-monitor] fetch failed url=%s err=%s", url, e)
        return None, None


def _extract_diff(prev_text: str | None, cur_text: str) -> str:
    """이전 vs 신규 본문의 라인 단위 간단 diff (추가/제거된 줄). 최대 15줄씩."""
    if not prev_text:
        return "(이전 본문 없음 — 첫 비교)"

    # 라인 단위 set 차집합 (순서 무관 — set 기반)
    prev_lines = set(line.strip() for line in prev_text.splitlines() if line.strip())
    cur_lines = set(line.strip() for line in cur_text.splitlines() if line.strip())

    added = sorted(cur_lines - prev_lines)
    removed = sorted(prev_lines - cur_lines)

    diff_parts = []
    if added:
        diff_parts.append(f"**+ 추가됨 ({len(added)}줄):**")
        for line in added[:15]:
            # 너무 긴 줄은 잘림 (Telegram 메시지 크기 제한 대비)
            diff_parts.append(f"  + {line[:180]}")
        if len(added) > 15:
            diff_parts.append(f"  ... 외 {len(added) - 15}줄")
    if removed:
        diff_parts.append(f"**- 제거됨 ({len(removed)}줄):**")
        for line in removed[:15]:
            diff_parts.append(f"  - {line[:180]}")
        if len(removed) > 15:
            diff_parts.append(f"  ... 외 {len(removed) - 15}줄")

    return "\n".join(diff_parts) if diff_parts else "(라인 단위 변경 없음 — HTML 메타 변경 가능성)"


def _assess_impact(diff_text: str) -> tuple[bool, list[str]]:
    """diff 에 영향 키워드 매칭 → (영향 가능 여부, 매칭 키워드 list)."""
    diff_lower = diff_text.lower()
    matched = sorted(set(kw for kw in _IMPACT_KEYWORDS if kw in diff_lower))
    return bool(matched), matched


def run_binance_changelog_monitor_once() -> None:
    """1회 실행: 모든 모니터 대상 URL 의 hash 비교 + 변경 감지 시 Telegram 알림.

    scheduler 가 매 6시간 호출. 첫 실행은 hash 만 저장하고 알림 X (false alarm 방지).

    v2 보강:
    - 본문도 Redis 에 저장 (diff 계산용)
    - Dedup 24h: 같은 페이지 알림 반복 방지
    - 알림 메시지에 diff + 영향 평가 포함
    """
    try:
        redis = get_redis_client()
    except Exception as e:
        logger.warning("[binance-monitor] redis unavailable: %s", e)
        return

    # 변경 detail 모음: (name, url, diff, has_impact, matched_keywords)
    changes_detected: list[tuple[str, str, str, bool, list[str]]] = []

    for name, url in _MONITORED_URLS:
        cur_hash, cur_body = _fetch_page(url)
        if cur_hash is None or cur_body is None:
            continue  # fetch 실패 → 다음 cycle 재시도

        hash_key = _HASH_KEY_TPL.format(name=name)
        body_key = _BODY_KEY_TPL.format(name=name)
        alert_sent_key = _ALERT_SENT_KEY_TPL.format(name=name)

        try:
            prev_hash_raw = redis.get(hash_key)
            prev_body_raw = redis.get(body_key)
        except Exception as e:
            logger.warning("[binance-monitor] redis get failed: %s", e)
            continue

        prev_hash = prev_hash_raw.decode() if isinstance(prev_hash_raw, bytes) else prev_hash_raw
        prev_body = prev_body_raw.decode() if isinstance(prev_body_raw, bytes) else prev_body_raw

        if prev_hash is None:
            # 첫 실행 — hash + body 저장만, 알림 X
            redis.set(hash_key, cur_hash, ex=_HASH_TTL_SEC)
            redis.set(body_key, cur_body, ex=_HASH_TTL_SEC)
            logger.info("[binance-monitor] first run, hash+body stored name=%s", name)
            continue

        if prev_hash != cur_hash:
            # 변경 감지!
            # Dedup 24h: 같은 페이지 이미 알림 보냈으면 skip (사장님 부담 감소)
            try:
                alert_sent = redis.get(alert_sent_key)
            except Exception:
                alert_sent = None

            if alert_sent:
                # 24h 내 이미 알림 발송 → hash + body 만 갱신, 알림 skip
                logger.info(
                    "[binance-monitor] CHANGE DETECTED but dedup'd (24h) name=%s — skip alert",
                    name,
                )
                redis.set(hash_key, cur_hash, ex=_HASH_TTL_SEC)
                redis.set(body_key, cur_body, ex=_HASH_TTL_SEC)
                continue

            # Diff 계산 + 영향 평가
            diff = _extract_diff(prev_body, cur_body)
            has_impact, matched_keywords = _assess_impact(diff)

            changes_detected.append((name, url, diff, has_impact, matched_keywords))

            # hash + body 갱신 + dedup 마커 설정 (24h TTL)
            redis.set(hash_key, cur_hash, ex=_HASH_TTL_SEC)
            redis.set(body_key, cur_body, ex=_HASH_TTL_SEC)
            redis.set(alert_sent_key, "1", ex=_ALERT_DEDUP_SEC)

            logger.warning(
                "[binance-monitor] CHANGE DETECTED name=%s url=%s impact=%s keywords=%s",
                name, url, has_impact, matched_keywords,
            )
        else:
            # 변경 없음 — TTL refresh (30일 유지)
            redis.expire(hash_key, _HASH_TTL_SEC)
            redis.expire(body_key, _HASH_TTL_SEC)

    if changes_detected:
        _notify_changes(changes_detected)


def _notify_changes(changes: Iterable[tuple[str, str, str, bool, list[str]]]) -> None:
    """변경 감지된 페이지 목록 → Telegram 알림 1건 (diff + 영향 평가 포함)."""
    items = list(changes)
    if not items:
        return

    # 영향 평가 — 하나라도 영향 가능 = 전체 알림 헤더에 ⚠️
    any_impact = any(has_impact for _, _, _, has_impact, _ in items)
    icon = "⚠️" if any_impact else "ℹ️"
    title = f"{icon} [Binance API 변경 감지] {len(items)}건"

    body_lines = [
        "Binance 공식 문서 변경 감지 (자동 모니터링 v2 — dedup 24h + diff 분석).",
        "",
    ]

    for name, url, diff, has_impact, matched_keywords in items:
        impact_label = (
            f"⚠️ **영향 가능** (키워드: {', '.join(matched_keywords[:5])})"
            if has_impact
            else "✓ 영향 없음 추정 (핵심 키워드 매칭 0)"
        )
        body_lines.extend([
            f"━━━━━━━━━━━━━━━━━━━━━━",
            f"📄 **{name}**",
            f"   {url}",
            f"   {impact_label}",
            "",
            "**변경 내용:**",
            diff[:1500],  # Telegram 메시지 크기 제한 (페이지당 1500자)
            "",
        ])

    body_lines.extend([
        "━━━━━━━━━━━━━━━━━━━━━━",
        "**확인 절차:**",
        "1. 위 「변경 내용」 검토 — endpoint/listenKey/deprecation 단어 주목",
        "2. ⚠️ 영향 가능 표시 → URL 직접 방문 + breaking change 확인 + 코드 변경",
        "3. ✓ 영향 없음 추정 → 단순 텍스트 정리/오타 가능성 (지나가도 OK)",
        "",
        "💡 같은 페이지 = 24h 안에 1번만 알림 (반복 부담 X).",
        "💡 2026-04-23 같은 사고 재발 방지용 자동 모니터링.",
    ])

    body = "\n".join(body_lines)

    try:
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            NotificationService(db).send_system_alert(title=title, body=body)
        finally:
            db.close()
        logger.info(
            "[binance-monitor] alert sent: %d page(s), any_impact=%s",
            len(items), any_impact,
        )
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
