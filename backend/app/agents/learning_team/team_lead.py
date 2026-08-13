"""🎓 LearningTeamLead = 사장님의 학습 팀 리더!

= 메모리 → 분석 → 학습 오케스트레이션!
= 매 4시간 자동 실행!
"""
from __future__ import annotations

import logging

from app.agents.orchestrator import BaseTeamLead, EventType

from app.agents.learning_team.memory_agent import MemoryAgent
from app.agents.learning_team.analysis_agent import AnalysisAgent
from app.agents.learning_team.learning_agent import LearningAgent

logger = logging.getLogger(__name__)


class LearningTeamLead(BaseTeamLead):
    """Learning Team!"""
    TEAM = "learning"
    AGENT_NAME = "learning_team_lead"
    AGENTS = [MemoryAgent, AnalysisAgent, LearningAgent]
    HANDLED_EVENTS = [
        EventType.EMERGENCY_STOP_ALL,
    ]

    def handle_event(self, event, data):
        if event == EventType.EMERGENCY_STOP_ALL:
            logger.warning("[Learning] STOP: %s", data.get("reason", ""))

    def run_learning_cycle(self, db, days: int = 30) -> dict:
        """전체 학습 사이클! (매 4시간 or 사장님 요청!)

        1. MemoryAgent = 데이터 수집!
        2. AnalysisAgent = 패턴 발견!
        3. LearningAgent = 저장 + 조정!
        """
        logger.info("[LearningTeam] cycle 시작 (days=%d)", days)

        try:
            # 1. Memory!
            memory = self.get_agent(MemoryAgent)
            memory_data = memory.execute(db, days=days)

            # 2. Analysis!
            analyzer = self.get_agent(AnalysisAgent)
            analysis = analyzer.execute(memory_data)

            # 3. Learning!
            learner = self.get_agent(LearningAgent)
            saved = learner.execute(db, analysis)

            # 팀 이벤트!
            self.publish(EventType.DAILY_LEARNING_DONE, {
                "insights_count": len(analysis.get("insights", [])),
            })

            return {
                "counts": memory_data.get("counts", {}),
                "insights_count": len(analysis.get("insights", [])),
                "saved_at": saved.get("generated_at"),
            }
        except Exception as e:
            logger.warning("[LearningTeam] cycle 실패: %s", e)
            return {"error": str(e)}
