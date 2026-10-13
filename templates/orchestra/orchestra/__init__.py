"""🎼 orchestra — 지휘자 + 팀 리더 + 에이전트 + 이벤트 버스 (범용 템플릿, 표준 라이브러리만)

binance-auto-trader 의 `backend/app/agents/orchestrator/` (2026-08-11 「총괄지휘하는 지휘자」 + 「메시지 공유 버스」)
에서 매매 전용 부분을 떼어 낸 뼈대. 새 프로젝트에 이 폴더를 복사하고 팀만 새로 만든다.

    from orchestra import Conductor, TeamLead, Agent, SystemEvent, Rulebook, get_event_bus
"""
from orchestra.bus import EventBus, get_event_bus, reset_event_bus
from orchestra.events import SystemEvent, event_name
from orchestra.rules import Rulebook, RuleViolation
from orchestra.agent import Agent
from orchestra.team import TeamLead
from orchestra.conductor import Conductor

__all__ = [
    "EventBus", "get_event_bus", "reset_event_bus",
    "SystemEvent", "event_name",
    "Rulebook", "RuleViolation",
    "Agent", "TeamLead", "Conductor",
]
__version__ = "1.0.0"
