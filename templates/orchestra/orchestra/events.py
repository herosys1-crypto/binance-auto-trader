"""📡 이벤트 이름.

이벤트는 문자열이다. 시스템 공용 이벤트만 여기 두고, 프로젝트 이벤트는 프로젝트에서 따로 정의한다:

    from enum import Enum

    class AppEvent(str, Enum):              # 프로젝트 쪽 (한 파일에만 = 단일 진실)
        ORDER_CREATED = "order.created"
        REPORT_READY = "report.ready"

버스는 `str` 과 `str` Enum 을 모두 받아 같은 이름으로 다룬다 (`event_name`).
"""
from __future__ import annotations

from enum import Enum


class SystemEvent(str, Enum):
    SYSTEM_STARTED = "system.started"
    SYSTEM_STOPPING = "system.stopping"
    EMERGENCY_STOP_ALL = "emergency.stop_all"      # 최우선 — 모든 팀 정지
    HEALTH_CHECK = "system.health_check"           # 지휘자 자체 진단 결과
    RULE_VIOLATED = "rule.violated"                # 규칙집 위반 (감사 팀이 받아 기록)
    AGENT_FAILED = "agent.failed"                  # 에이전트 실행 실패


def event_name(event: str | Enum) -> str:
    """str Enum 이면 값, 문자열이면 그대로. 빈 이름은 거부."""
    name = event.value if isinstance(event, Enum) else event
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"event name must be a non-empty string, got {event!r}")
    return name
