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

from app.agents.strategy_suggestion_team.bb_4h_scanner import BB4HScanner
from app.agents.strategy_suggestion_team.pump_dump_predictor import PumpDumpPredictor
from app.agents.strategy_suggestion_team.descent_pattern_detector import DescentPatternDetector
from app.agents.strategy_suggestion_team.strategy_suggestion_generator import StrategySuggestionGenerator
from app.agents.strategy_suggestion_team.suggestion_manager import SuggestionManager
from app.agents.strategy_suggestion_team.auto_manual_executor import AutoManualExecutor
from app.agents.strategy_suggestion_team.daily_briefing_agent import DailyBriefingAgent

logger = logging.getLogger(__name__)


class StrategySuggestionTeamLead(BaseTeamLead):
    """Strategy Suggestion 팀 리더!"""
    TEAM = "strategy_suggestion"
    AGENT_NAME = "strategy_suggestion_team_lead"
    AGENTS = [
        PumpDumpPredictor,
        BB4HScanner,
        DescentPatternDetector,
        StrategySuggestionGenerator,
        SuggestionManager,
        AutoManualExecutor,
        DailyBriefingAgent,  # 🌅 매일 아침 브리핑!
    ]
    HANDLED_EVENTS = [
        EventType.EMERGENCY_STOP_ALL,
    ]

    def handle_event(self, event: EventType, data: dict) -> None:
        """이벤트 처리!"""
        if event == EventType.EMERGENCY_STOP_ALL:
            self.emergency_stop(data.get("reason", ""))

    def run_daily_prediction(self, db, decrypt_text, force: bool = False) -> dict:
        """매일 06:30 UTC 스케줄!

        Args:
            force: True 시 = 오늘 PENDING 자동 dismiss 후 재생성!
                   (사장님 「지금 실행」 재실행 편의!)

        v143a 이후 흐름:
        1. **BB4HScanner** → 4H 볼밴 신호 스캔 (옛 PumpDumpPredictor 대체)
        2. (필터 없음 — 4H BB 신호는 이미 실측 기대값 기반)
        3. StrategySuggestionGenerator → DB 저장!

        ⚠️ PumpDumpPredictor / DescentPatternDetector 는 **더 이상 호출되지 않습니다**.
           (import·AGENTS 등록은 롤백 대비로 남겨둠 — 되돌리려면 scanner 호출부만 교체)
        """
        logger.info("[%s Lead] 🎯 매일 예측 시작! (force=%s)", self.TEAM, force)

        # 🎯 v143a 사장님 최종 결정 (2026-08-14):
        #   "자동전략 제안은 4시간봉이 볼밴 중단과 하단 깨는 경우로 해줘 롱과 숏을"
        #   → 제안 소스를 **4H 볼밴 스캐너**로 전환합니다.
        #     기존 PumpDumpPredictor(24h 급등락 순위)는 근거가 실측되지 않았고,
        #     v139 백테스트에서 추천 성공률이 40.5%에 그쳤습니다.
        #     4H BB 는 표본 13,053건 / 도달률 82~87% / 기대값 +0.42~0.44% 로
        #     이번 세션에서 검증한 신호 중 가장 견고합니다.
        scanner = self.get_agent(BB4HScanner)
        scan_result = scanner.execute(db, decrypt_text)
        predictions = scan_result.get("predictions", [])
        if not predictions:
            logger.info("[%s Lead] 4H BB 신호 없음 = 제안 생성 안 함", self.TEAM)
            return {"error": "no bb4h signals", "step": "scan",
                    "scanned": scan_result.get("scanned", 0)}

        # v143a: 4H BB 신호는 이미 실측 기대값 기반이라 별도 필터를 걸지 않습니다.
        #        (급락 지속 필터는 24h 순위 기반 제안용이었음)
        filtered: list = []

        # v143a: 4가지 4H BB 트리거 = 롱·숏 대칭 (사장님 지시!)
        #   bb4h_mid_down    (SHORT) = 중단 하향 이탈 → 하단 목표   기대값 +0.42%
        #   bb4h_mid_up      (LONG)  = 중단 상향 돌파 → 상단 목표   기대값 +0.44%
        #   bb4h_lower_break (SHORT) = 하단 이탈 후 추세 지속        기대값 +0.14%
        #   bb4h_upper_break (LONG)  = 상단 돌파 후 추세 지속        기대값 +0.27%
        non_dump_continuation = [
            p for p in predictions
            if str(p.get("type", "")).startswith("bb4h_")
        ]
        final = non_dump_continuation + filtered

        # 3. DB 저장!
        generator = self.get_agent(StrategySuggestionGenerator)
        gen_result = generator.execute(db, final, force=force)

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

    def run_daily_briefing(self, db) -> dict:
        """🌅 매일 아침 브리핑! (KST 07:30 = UTC 22:30!)"""
        briefer = self.get_agent(DailyBriefingAgent)
        return briefer.execute(db)

    def emergency_stop(self, reason: str) -> None:
        """🚨 팀 정지!"""
        logger.warning("[%s Lead] 🚨 STOP! %s", self.TEAM, reason)
        # 스케줄 스킵 로직 (다음 세션!)
