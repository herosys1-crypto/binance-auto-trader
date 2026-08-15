"""📊 ChartPatternLearningTeamLead = 팀 오케스트레이션!

사장님 지시 2026-08-16:
"심볼들의 1달 차트를 분석해서 이런 패턴을 학습해서 메모리해줘
 차트분석 에이전트가 없으면 차트분석 에이전트팀을 만들어줘"

= 매일 자동 실행!
= 모든 심볼 4H 캔들 스캔 → 패턴 감지 → 저장!
= outcome 자동 tracking!
"""
from __future__ import annotations

import logging

from app.agents.orchestrator import BaseTeamLead, EventType

from app.agents.chart_pattern_learning_team.pattern_collector import PatternCollector
from app.agents.chart_pattern_learning_team.pattern_detector import PatternDetector
from app.agents.chart_pattern_learning_team.pattern_memory import PatternMemory

logger = logging.getLogger(__name__)


class ChartPatternLearningTeamLead(BaseTeamLead):
    """Chart Pattern Learning Team!"""
    TEAM = "chart_pattern_learning"
    AGENT_NAME = "chart_pattern_learning_team_lead"
    AGENTS = [PatternCollector, PatternDetector, PatternMemory]
    HANDLED_EVENTS = [EventType.EMERGENCY_STOP_ALL]

    def handle_event(self, event, data):
        if event == EventType.EMERGENCY_STOP_ALL:
            logger.warning("[chart_pattern_learning] STOP: %s", data.get("reason", ""))

    def run_full_scan(self, db, decrypt_text, top_n: int = 100) -> dict:
        """전체 사이클: 심볼 조회 → 각 심볼 스캔 → 저장 → outcome update!"""
        logger.info("[chart_pattern_learning] cycle 시작 (top_n=%d)", top_n)

        from sqlalchemy import select
        from app.integrations.binance.client import BinanceClient
        from app.models.exchange_account import ExchangeAccount

        account = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if not account:
            return {"error": "no mainnet account"}

        bc = BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=False,
        )

        try:
            collector = self.get_agent(PatternCollector)
            detector = self.get_agent(PatternDetector)
            memory = self.get_agent(PatternMemory)

            # 1. 상위 심볼!
            symbols = collector.top_symbols(bc, n=top_n)
            if not symbols:
                return {"error": "no symbols"}

            # 2. 각 심볼 스캔!
            total_detected = 0
            total_stored = 0
            for sym in symbols:
                kl = collector.collect(bc, sym)
                if not kl:
                    continue
                detected = detector.scan(sym, kl)
                if not detected:
                    continue
                total_detected += len(detected)
                stored = memory.store(db, detected)
                total_stored += stored

            # 3. Outcome tracking!
            outcome = memory.track_outcomes(db, bc, hours_max=168)

            # 팀 이벤트!
            self.publish(EventType.DAILY_LEARNING_DONE, {
                "team": self.TEAM,
                "detected": total_detected,
                "stored": total_stored,
                "outcome": outcome,
            })

            logger.info(
                "[chart_pattern_learning] 완료: symbols=%d detected=%d stored=%d outcome=%s",
                len(symbols), total_detected, total_stored, outcome,
            )
            return {
                "scanned_symbols": len(symbols),
                "detected": total_detected,
                "stored": total_stored,
                "outcome": outcome,
            }
        except Exception as e:
            logger.warning("[chart_pattern_learning] 실행 실패: %s", e)
            return {"error": str(e)}
