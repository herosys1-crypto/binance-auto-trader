"""📡 EventBus — 팀 사이 pub/sub 채널 (스레드 안전, 구독자 하나가 실패해도 나머지는 받는다).

    bus = get_event_bus()
    bus.subscribe("order.created", handler)      # handler(event_name: str, data: dict) -> None
    bus.subscribe("*", audit_handler)            # 모든 이벤트 (감사·로그용)
    bus.publish("order.created", {"id": 1})      # → 처리한 구독자 수
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from enum import Enum
from typing import Any, Callable

from orchestra.events import event_name

logger = logging.getLogger(__name__)

Handler = Callable[[str, dict], None]
WILDCARD = "*"


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)
        self._lock = threading.RLock()
        self._published: dict[str, int] = defaultdict(int)
        self._failures: dict[str, int] = defaultdict(int)

    def subscribe(self, event: str | Enum, handler: Handler) -> None:
        if not callable(handler):
            raise TypeError("handler must be callable")
        name = event_name(event)
        with self._lock:
            if handler not in self._subs[name]:
                self._subs[name].append(handler)

    def unsubscribe(self, event: str | Enum, handler: Handler) -> None:
        name = event_name(event)
        with self._lock:
            if handler in self._subs.get(name, []):
                self._subs[name].remove(handler)

    def publish(self, event: str | Enum, data: dict[str, Any] | None = None) -> int:
        """구독자(이름 일치 + "*")에게 전달. 예외는 삼키고 세기만 한다 — 한 팀 실패가 다른 팀을 막지 않게."""
        name = event_name(event)
        payload = dict(data or {})
        with self._lock:
            # "*" 구독자(감사·로그)를 먼저 — 핸들러 안에서 다음 이벤트를 보내도 기록이 원인 → 결과 순서가 된다
            handlers = [h for h in self._subs.get(WILDCARD, []) if name != WILDCARD] + list(self._subs.get(name, []))
            self._published[name] += 1
        ok = 0
        for h in handlers:
            try:
                h(name, payload)
                ok += 1
            except Exception as e:  # noqa: BLE001
                with self._lock:
                    self._failures[name] += 1
                logger.error("[EventBus] %s → %s 실패: %s", name, getattr(h, "__qualname__", h), e)
        logger.debug("[EventBus] %s → %d/%d", name, ok, len(handlers))   # INFO 로 두면 로그가 이벤트 수만큼 쌓인다
        return ok

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "subscriptions": sum(len(v) for v in self._subs.values()),
                "published": dict(self._published),
                "failures": dict(self._failures),
                "subscribers": {k: len(v) for k, v in self._subs.items() if v},
            }

    def clear(self) -> None:
        with self._lock:
            self._subs.clear()
            self._published.clear()
            self._failures.clear()


_bus: EventBus | None = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """프로세스 전역 버스 (싱글톤)."""
    global _bus
    if _bus is None:
        with _bus_lock:
            if _bus is None:
                _bus = EventBus()
    return _bus


def reset_event_bus() -> EventBus:
    """테스트용 — 새 버스로 바꾼다."""
    global _bus
    with _bus_lock:
        _bus = EventBus()
    return _bus
