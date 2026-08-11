"""📡 EventBus = 팀 간 메시지 공유 채널! (사장님 요구 2026-08-11!)

사장님 요구:
"전체 에이젼트들을 통제할 수 있는 버스(메시지 공유 채널)도 구성해줘"

구조: pub/sub 패턴!
- publish: 이벤트 발신!
- subscribe: 이벤트 수신 등록!
- unsubscribe: 등록 해제!

싱글톤 = 시스템 전역 하나!
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Any, Callable

from app.agents.orchestrator.event_types import EventType

logger = logging.getLogger(__name__)


class EventBus:
    """전체 에이전트 통신 채널! (pub/sub!)

    Usage:
        bus = get_event_bus()

        # 구독!
        bus.subscribe(EventType.STRATEGY_ENTERED, my_handler)

        # 발신!
        bus.publish(EventType.STRATEGY_ENTERED, {"strategy_id": 838})

        # 구독 해제!
        bus.unsubscribe(EventType.STRATEGY_ENTERED, my_handler)
    """

    def __init__(self):
        self._subscribers: dict[EventType, list[Callable]] = defaultdict(list)
        self._lock = threading.RLock()  # 스레드 안전!
        self._event_count: dict[EventType, int] = defaultdict(int)  # 통계!

    def subscribe(self, event: EventType, handler: Callable) -> None:
        """이벤트 구독!

        Args:
            event: EventType 상수
            handler: def handler(event: EventType, data: dict) -> None
        """
        with self._lock:
            if handler not in self._subscribers[event]:
                self._subscribers[event].append(handler)
                logger.debug("[EventBus] 구독: %s → %s", event.value, handler.__name__)

    def unsubscribe(self, event: EventType, handler: Callable) -> None:
        """구독 해제!"""
        with self._lock:
            if handler in self._subscribers[event]:
                self._subscribers[event].remove(handler)

    def publish(self, event: EventType, data: dict[str, Any] | None = None) -> int:
        """이벤트 발신 = 모든 구독자에게 전달!

        Args:
            event: EventType!
            data: 전달할 데이터!

        Returns:
            처리된 구독자 수!
        """
        data = data or {}
        with self._lock:
            handlers = list(self._subscribers.get(event, []))  # 복사!
            self._event_count[event] += 1

        count = 0
        for handler in handlers:
            try:
                handler(event, data)
                count += 1
            except Exception as e:
                logger.error(
                    "[EventBus] handler 실패 event=%s handler=%s: %s",
                    event.value, getattr(handler, "__name__", "?"), e,
                )

        logger.info(
            "[EventBus] 📡 %s → %d subscribers (data=%s)",
            event.value, count, list(data.keys()),
        )
        return count

    def get_stats(self) -> dict[str, Any]:
        """이벤트 통계 = 감사/모니터링용!"""
        with self._lock:
            return {
                "total_subscriptions": sum(
                    len(handlers) for handlers in self._subscribers.values()
                ),
                "total_events_published": sum(self._event_count.values()),
                "event_counts": {
                    ev.value: cnt for ev, cnt in self._event_count.items()
                },
                "subscribers_per_event": {
                    ev.value: len(handlers)
                    for ev, handlers in self._subscribers.items()
                },
            }

    def clear(self) -> None:
        """모든 구독 해제 (테스트/reset 용!)."""
        with self._lock:
            self._subscribers.clear()
            self._event_count.clear()


# 싱글톤 인스턴스!
_bus_instance: EventBus | None = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """전역 EventBus 인스턴스 반환 (싱글톤!)."""
    global _bus_instance
    if _bus_instance is None:
        with _bus_lock:
            if _bus_instance is None:
                _bus_instance = EventBus()
                logger.info("[EventBus] 🌟 초기화 완료!")
    return _bus_instance
