"""우리 시스템의 외부 Binance 의존성 자동 health check worker.

배경 (2026-06-01 사장님 mainnet 첫날 사고 후속):
user-stream WebSocket 연결은 성공 (Websocket connected) 했지만 ORDER_TRADE_UPDATE
이벤트가 33시간 동안 0건 수신 — silent failure. Binance 측 마이그레이션 영향이지만
우리 시스템이 즉시 감지 못 해 사장님이 직접 알아챔. 같은 silent failure 자동 감지.

동작:
- 매 30분 주기
- 3가지 health check:
  (1) WebSocket 연결 heartbeat 확인 (Redis health:user_stream:connected)
  (2) ORDER 이벤트 수신 빈도 (활성 strategy 있는데 12h 0건 → critical)
  (3) Binance REST API ping (fapi.binance.com 도달 가능)
- 이상 감지 시 Telegram 「🚨 [Endpoint Health 경고]」 알림 (1회 dedup)
"""
from __future__ import annotations

import logging
import time

import requests

from app.core.redis_client import get_redis_client
from app.observability.sentry import capture_strategy_event

logger = logging.getLogger(__name__)

# 알림 dedup TTL (같은 알림 6시간에 1회만)
_ALERT_DEDUP_TTL_SEC = 6 * 3600
_ALERT_DEDUP_KEY_TPL = "endpoint_health:alert_dedup:{kind}"

# user-stream 이벤트 카운터 (binance_user_stream_consumer 가 증가)
# 12시간 동안 0건이면 critical (활성 strategy 있을 때)
_ORDER_EVENT_COUNTER_KEY = "metrics:user_stream:order_events_total"
_ORDER_EVENT_COUNTER_SNAPSHOT_KEY = "endpoint_health:order_events_snapshot"
_ORDER_EVENT_SNAPSHOT_TTL_SEC = 13 * 3600  # snapshot 자체는 13시간 (12시간 비교 + 여유)
_ORDER_EVENT_NO_RECV_THRESHOLD_HOURS = 12


def _alert_once(redis_client, kind: str, title: str, body: str) -> None:
    """같은 kind 의 알림은 dedup TTL 내 1회만 발송."""
    key = _ALERT_DEDUP_KEY_TPL.format(kind=kind)
    try:
        if redis_client.get(key):
            logger.info("[endpoint-health] alert dedup skip kind=%s", kind)
            return
        redis_client.setex(key, _ALERT_DEDUP_TTL_SEC, "1")
    except Exception:
        pass

    try:
        from app.core.database import SessionLocal
        from app.services.notification_service import NotificationService
        db = SessionLocal()
        try:
            NotificationService(db).send_system_alert(title=title, body=body)
        finally:
            db.close()
        logger.warning("[endpoint-health] alert sent kind=%s", kind)
    except Exception as e:
        logger.exception("[endpoint-health] alert send failed: %s", e)
        try:
            capture_strategy_event(
                f"Endpoint health alert send failed: {e}",
                level="error",
                tags={"event_type": "ENDPOINT_HEALTH_ALERT_FAIL", "kind": kind},
            )
        except Exception:
            pass


def _check_user_stream_websocket(redis_client) -> None:
    """user-stream WebSocket 연결 heartbeat 확인.

    binance_user_stream_consumer 가 매 메시지 수신 + 30s heartbeat thread 가
    Redis 'health:user_stream:connected' 갱신 (TTL 60s). key 없으면 60s+ 끊김 의미.
    """
    try:
        connected = redis_client.get("health:user_stream:connected")
    except Exception as e:
        logger.warning("[endpoint-health] ws heartbeat redis read failed: %s", e)
        return

    if connected:
        return  # 정상

    _alert_once(
        redis_client,
        kind="ws_disconnect",
        title="🚨 [Endpoint Health] user-stream WebSocket 연결 끊김",
        body=(
            "user-stream WebSocket 의 heartbeat (60s TTL) 가 만료됨.\n\n"
            "**원인 후보:**\n"
            "• listenKey 만료 (60분 TTL — keepalive 워커 확인)\n"
            "• Binance WebSocket endpoint 변경 (Binance 공지 확인)\n"
            "• 네트워크 일시 단절 (Sentry 로그 확인)\n\n"
            "**조치:** docker compose logs --tail 30 user-stream + restart 시도"
        ),
    )


def _check_order_event_reception(redis_client) -> None:
    """ORDER_TRADE_UPDATE 이벤트 수신 빈도 모니터링.

    binance_user_stream_consumer 가 매 ORDER 이벤트마다 카운터 증가
    (metrics:user_stream:order_events_total).
    snapshot 과 비교해 12시간 동안 증가 0 + 활성 strategy >0 이면 critical.
    """
    try:
        cur_counter_raw = redis_client.get(_ORDER_EVENT_COUNTER_KEY)
    except Exception:
        return
    cur_counter = int(cur_counter_raw) if cur_counter_raw else 0

    try:
        snapshot_raw = redis_client.get(_ORDER_EVENT_COUNTER_SNAPSHOT_KEY)
    except Exception:
        return

    now_ts = int(time.time())

    if not snapshot_raw:
        # 첫 실행 — snapshot 저장
        redis_client.setex(
            _ORDER_EVENT_COUNTER_SNAPSHOT_KEY,
            _ORDER_EVENT_SNAPSHOT_TTL_SEC,
            f"{cur_counter}:{now_ts}",
        )
        return

    try:
        snapshot_counter_str, snapshot_ts_str = snapshot_raw.decode().split(":")
        snapshot_counter = int(snapshot_counter_str)
        snapshot_ts = int(snapshot_ts_str)
    except Exception:
        # 형식 깨짐 — 다시 저장
        redis_client.setex(
            _ORDER_EVENT_COUNTER_SNAPSHOT_KEY,
            _ORDER_EVENT_SNAPSHOT_TTL_SEC,
            f"{cur_counter}:{now_ts}",
        )
        return

    elapsed_hours = (now_ts - snapshot_ts) / 3600
    if elapsed_hours < _ORDER_EVENT_NO_RECV_THRESHOLD_HOURS:
        return  # 아직 12시간 미만 — 평가 X

    if cur_counter > snapshot_counter:
        # 정상 — snapshot 업데이트
        redis_client.setex(
            _ORDER_EVENT_COUNTER_SNAPSHOT_KEY,
            _ORDER_EVENT_SNAPSHOT_TTL_SEC,
            f"{cur_counter}:{now_ts}",
        )
        return

    # 12h 동안 ORDER 이벤트 0건. 활성 strategy 확인.
    try:
        from app.core.database import SessionLocal
        from app.core.strategy_status import ACTIVE_WITH_POSITION
        from app.models.strategy_instance import StrategyInstance
        from sqlalchemy import select, func

        db = SessionLocal()
        try:
            active_count = db.execute(
                select(func.count(StrategyInstance.id))
                .where(StrategyInstance.is_archived.is_(False))
                .where(StrategyInstance.status.in_(ACTIVE_WITH_POSITION))
            ).scalar() or 0
        finally:
            db.close()
    except Exception as e:
        logger.warning("[endpoint-health] active strategy count failed: %s", e)
        return

    if active_count == 0:
        # 활성 strategy 없으면 ORDER 이벤트 0건 정상 — snapshot refresh
        redis_client.setex(
            _ORDER_EVENT_COUNTER_SNAPSHOT_KEY,
            _ORDER_EVENT_SNAPSHOT_TTL_SEC,
            f"{cur_counter}:{now_ts}",
        )
        return

    _alert_once(
        redis_client,
        kind="order_event_silent",
        title="🚨 [Endpoint Health] user-stream ORDER 이벤트 12h 0건 (활성 strategy 있음)",
        body=(
            f"활성 strategy {active_count}건이 있지만 12시간 동안 ORDER_TRADE_UPDATE "
            f"이벤트가 단 한 건도 수신되지 않음.\n\n"
            "**의심 원인 (2026-06-01 사례):**\n"
            "• Binance WebSocket endpoint 마이그레이션 (legacy /ws/ 차단 등)\n"
            "• Sub-account listenKey 권한 변경\n"
            "• 네트워크 또는 방화벽 차단\n\n"
            "**조치:**\n"
            "1. docker compose logs --tail 50 user-stream\n"
            "2. https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams 확인\n"
            "3. binance_user_stream_consumer.py 의 ws_url 검토"
        ),
    )


def _check_binance_rest_ping() -> bool:
    """Binance REST API ping (인증 불필요, 5초 timeout)."""
    try:
        r = requests.get("https://fapi.binance.com/fapi/v1/ping", timeout=5)
        return r.status_code == 200
    except Exception as e:
        logger.warning("[endpoint-health] REST ping failed: %s", e)
        return False


def run_endpoint_health_monitor_once() -> None:
    """1회 실행 — 3가지 health check 후 이상 시 알림.

    scheduler 가 매 30분 호출.
    """
    try:
        redis = get_redis_client()
    except Exception as e:
        logger.warning("[endpoint-health] redis unavailable: %s", e)
        return

    # 1. WebSocket heartbeat
    _check_user_stream_websocket(redis)

    # 2. ORDER 이벤트 수신 빈도
    _check_order_event_reception(redis)

    # 3. REST ping
    if not _check_binance_rest_ping():
        _alert_once(
            redis,
            kind="rest_ping_fail",
            title="🚨 [Endpoint Health] Binance REST API ping 실패",
            body=(
                "fapi.binance.com/fapi/v1/ping 호출 실패 (5초 timeout).\n\n"
                "원인: 네트워크 단절, Binance 측 장애, DNS 이슈 등.\n"
                "조치: VPS 에서 직접 curl 시도 → 외부 네트워크 점검."
            ),
        )


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    run_endpoint_health_monitor_once()
    sys.exit(0)
