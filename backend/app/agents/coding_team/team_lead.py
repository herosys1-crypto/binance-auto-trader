"""💻 CodingTeamLead = 코딩 팀 리더!

사장님 지시 2026-08-16:
"코딩 에이전트 그리고 기획 에이전트 이렇게 2개 팀 에이전트를 만들어서 역할 분할!"

4 Agents:
- BackendCoder: FastAPI/SQLAlchemy/Python!
- FrontendCoder: HTML/CSS/JS!
- TestWriter: pytest 테스트!
- RefactorAgent: 리팩토링!

협업:
Planning Team → Coding Team → Audit Team → 배포!
"""
from __future__ import annotations

import logging

from app.agents.orchestrator import BaseTeamLead, EventType

from app.agents.coding_team.backend_coder import BackendCoder
from app.agents.coding_team.frontend_coder import FrontendCoder
from app.agents.coding_team.test_writer import TestWriter
from app.agents.coding_team.refactor_agent import RefactorAgent

logger = logging.getLogger(__name__)


class CodingTeamLead(BaseTeamLead):
    """Coding Team Lead!"""
    TEAM = "coding"
    AGENT_NAME = "coding_team_lead"
    AGENTS = [BackendCoder, FrontendCoder, TestWriter, RefactorAgent]
    HANDLED_EVENTS = [
        EventType.EMERGENCY_STOP_ALL,
    ]

    # 사장님 세션에서 사용하는 코딩 스타일!
    CODING_PRINCIPLES = [
        "1. 사장님 사상 우선 (헌법 C02!)",
        "2. Silent bug 금지 (헌법 C03!)",
        "3. 검증 없는 코드 X (헌법 C04!)",
        "4. 대칭성 (LONG/SHORT 대칭!)",
        "5. 단일 진실 (Redis > DB!)",
        "6. 자동 검증 (agents!)",
        "7. Silent 차단 알림!",
    ]

    def handle_event(self, event, data):
        if event == EventType.EMERGENCY_STOP_ALL:
            logger.warning("[coding] STOP: %s", data.get("reason", ""))

    def get_team_summary(self) -> dict:
        """팀 요약!"""
        return {
            "team": self.TEAM,
            "agents_count": len(self.AGENTS),
            "agents": [a.AGENT_NAME for a in self.AGENTS],
            "principles": self.CODING_PRINCIPLES,
            "workflow": (
                "Planning Team = 명세 →\n"
                "Coding Team = 구현 →\n"
                "Audit Team = 검증 →\n"
                "사장님 승인 →\n"
                "실 배포!"
            ),
        }
