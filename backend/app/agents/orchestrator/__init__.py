"""🎩 Orchestrator Layer = 55+ 에이전트 총괄 지휘!

사장님 요구 (2026-08-11):
1. "현재 개별 에이전트를 총괄지휘하는 지휘자가 있는지?"
2. "전체 에이젼트들을 통제할 수 있는 버스(메시지 공유 채널)도 구성해줘"

Components:
- GrandOrchestrator: 최상위 총괄 지휘자!
- TeamLeadBase: 각 팀 리더 base 클래스!
- EventBus: 팀 간 pub/sub 메시지 채널!
- EventTypes: 이벤트 상수 (single source!)

관련:
- spec: docs/ORCHESTRATOR_LAYER_SPEC_v132.html
- 헌법 C05 (대칭성!), C06 (단일 진실!)
"""
from app.agents.orchestrator.event_bus import EventBus, get_event_bus
from app.agents.orchestrator.event_types import EventType
from app.agents.orchestrator.team_lead_base import BaseTeamLead
from app.agents.orchestrator.grand_orchestrator import GrandOrchestrator

__all__ = [
    "EventBus",
    "get_event_bus",
    "EventType",
    "BaseTeamLead",
    "GrandOrchestrator",
]
