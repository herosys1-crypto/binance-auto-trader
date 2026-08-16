"""📋 PlanningTeamLead = 기획 팀 리더!

사장님 지시 2026-08-16:
"기획 에이전트 팀 만들어서 역할 분할!"

4 Agents:
- RequirementAnalyzer: 사장님 요구 분석!
- SpecWriter: 명세 작성!
- Architect: 아키텍처 설계!
- PriorityManager: 우선순위 관리!

협업:
사장님 요구 →
  Planning Team = 명세 →
    Coding Team = 구현 →
      Audit Team = 검증 →
        사장님 승인 →
          실 배포!
"""
from __future__ import annotations

import logging

from app.agents.orchestrator import BaseTeamLead, EventType

from app.agents.planning_team.requirement_analyzer import RequirementAnalyzer
from app.agents.planning_team.spec_writer import SpecWriter
from app.agents.planning_team.architect import Architect
from app.agents.planning_team.priority_manager import PriorityManager

logger = logging.getLogger(__name__)


class PlanningTeamLead(BaseTeamLead):
    """Planning Team Lead!"""
    TEAM = "planning"
    AGENT_NAME = "planning_team_lead"
    AGENTS = [RequirementAnalyzer, SpecWriter, Architect, PriorityManager]
    HANDLED_EVENTS = [
        EventType.EMERGENCY_STOP_ALL,
    ]

    PLANNING_PROCESS = [
        "1. RequirementAnalyzer: 사장님 요구 → 명확 요구사항!",
        "2. Architect: 아키텍처 설계 (어느 layer?)",
        "3. PriorityManager: 우선순위 결정 (CRITICAL/HIGH/MEDIUM/LOW)",
        "4. SpecWriter: 상세 명세 (docs/SPEC_v{N}_{feature}.md!)",
        "5. Coding Team에 전달!",
    ]

    def handle_event(self, event, data):
        if event == EventType.EMERGENCY_STOP_ALL:
            logger.warning("[planning] STOP: %s", data.get("reason", ""))

    def get_team_summary(self) -> dict:
        """팀 요약!"""
        return {
            "team": self.TEAM,
            "agents_count": len(self.AGENTS),
            "agents": [a.AGENT_NAME for a in self.AGENTS],
            "process": self.PLANNING_PROCESS,
            "output": "docs/SPEC_v{version}_{feature}.md",
            "next_team": "coding_team",
        }
