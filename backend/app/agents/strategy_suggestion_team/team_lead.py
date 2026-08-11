"""🎯 StrategySuggestionTeamLead = Strategy Suggestion 팀 리더!

역할:
- 5 에이전트 관리!
- EventBus 통해 팀 간 통신!
- 스케줄 실행 (매일 06:30 = 예측!)

Handled Events:
- DAILY_LEARNING_DONE → 예측 (다음 세션 Market Flow 연동!)
- SUGGESTION_CREATED → Alert Team 통보!
- KILL_SWITCH_TRIGGERED → 팀 정지!
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.agents.orchestrator import BaseTeamLead, EventType

from app.agents.strategy_suggestion_team.pump_dump_predictor import PumpDumpPredictor
from app.agents.strategy_suggestion_team.descent_pattern_detector import DescentPatternDetector
from app.agents.strategy_suggestion_team.strategy_suggestion_generator import StrategySuggestionGenerator
from app.agents.strategy_suggestion_team.suggestion_manager import SuggestionManager
from app.agents.strategy_suggestion_team.auto_manual_executor import AutoManualExecutor

logger = logging.getLogger(__name__)


class StrategySuggestionTeamLead(BaseTeamLead):
    """Strategy Suggestion 팀 리더!"""
    TEAM = "strategy_suggestion"
    AGENT_NAME = "strategy_suggestion_team_lead"
    AGENTS = [
        PumpDumpPredictor,
        DescentPatternDetector,
        StrategySuggestionGenerator,
        SuggestionManager,
        AutoManualExecutor,
    ]
    HANDLED_EVENTS = [
        EventType.EMERGENCY_STOP_ALL,
    ]

    def handle_event(self, event: EventType, data: dict) -> None:
        """이벤트 처리!"""
        if event == EventType.EMERGENCY_STOP_ALL:
            self.emergency_stop(data.get("reason", ""))

    def run_daily_prediction(self, db, decrypt_text) -> dict:
        """매일 06:30 UTC 스케줄!

        1. PumpDumpPredictor → 예측!
        2. DescentPatternDetector → 필터!
        3. StrategySuggestionGenerator → DB 저장!
        """
        logger.info("[%s Lead] 🎯 매일 예측 시작!", self.TEAM)

        # 1. 예측!
        predictor = self.get_agent(PumpDumpPredictor)
        pred_result = predictor.execute(db, decrypt_text)
        predictions = pred_result.get("predictions", [])
        if not predictions:
            return {"error": "no predictions", "step": "predict"}

        # 2. 급락 지속 필터! (선택!)
        detector = self.get_agent(DescentPatternDetector)
        detect_result = detector.execute(db, decrypt_text, predictions)
        # 지속 하락 확정 심볼 = confidence 상향된 것!
        # + pump_end 는 그대로 유지!
        filtered = detect_result.get("filtered", [])
        # dump_continuation은 filtered, pump_end는 원본!
        final = [p for p in predictions if p.get("type") == "pump_end"] + filtered

        # 3. DB 저장!
        generator = self.get_agent(StrategySuggestionGenerator)
        gen_result = generator.execute(db, final)

        # 팀 이벤트!
        self.publish(EventType.SUGGESTION_CREATED, {
            "count": gen_result.get("created", 0),
            "total_predictions": len(final),
        })

        return {
            "predictions": len(predictions),
            "detected": len(filtered),
            "created": gen_result.get("created", 0),
        }

    def run_hourly_cleanup(self, db) -> dict:
        """매 1시간 = 자동 삭제!"""
        manager = self.get_agent(SuggestionManager)
        return manager.execute(db)

    def run_auto_execute(self, db) -> dict:
        """매일 07:00 = 자동 실행 배치! (사장님 옵션 ON 시!)."""
        executor = self.get_agent(AutoManualExecutor)
        return executor.execute_auto_batch(db)

    def emergency_stop(self, reason: str) -> None:
        """🚨 팀 정지!"""
        logger.warning("[%s Lead] 🚨 STOP! %s", self.TEAM, reason)
        # 스케줄 스킵 로직 (다음 세션!)
