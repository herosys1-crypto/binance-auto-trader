"""⚔️ StageTriggerAgent = 단계별 자동 진입!

Team: Entry Team
Mission: 사장님 세팅 → 가격 도달 → 자동 진입!

관련 헌법:
- C01 (메인넷 = 실 자금!)
- C02 (사장님 사상 우선!)
- C07 (capital = margin!)
- C09 (retry ON = 순차 진입!)

기존 워커: app/workers/stage_trigger_worker.py
= 이 에이전트 = wrapper (기존 워커 호출!)
= 점진적 마이그레이션 = 안전!

다음 단계 (미래!):
1. 기존 워커 = 이 파일 안으로 이동!
2. BaseAgent 상속 = 자동 헌법 검증!
3. 팀 협업 = Alert Team, Capital Team과 통신!
"""
from __future__ import annotations

import logging

from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class StageTriggerAgent(BaseAgent):
    """단계별 자동 진입 에이전트.

    v132 = Phase D MVP = wrapper (기존 워커 호출!)
    다음 세션 = 실 로직 이동!
    """
    TEAM = "entry"
    AGENT_NAME = "stage_trigger_agent"

    def execute(self, decrypt_text) -> dict:
        """실행 = 기존 워커 호출 + 자동 헌법 검증!

        Args:
            decrypt_text: crypto 함수 (기존 워커 필요!)

        Returns:
            실행 결과 dict
        """
        # 1. 헌법 자동 검증!
        try:
            self.validate("STAGE_ENTRY")
        except Exception as e:
            logger.error("[%s] 헌법 위반! %s", self.AGENT_NAME, e)
            raise

        # 2. 신 default 참조 (예!)
        _lev_default = self.get_default("leverage_2x")
        if _lev_default:
            logger.debug("[%s] 레버리지 default 참조: 2x", self.AGENT_NAME)

        # 3. 기존 워커 호출 (실 로직!)
        from app.workers.stage_trigger_worker import run_stage_trigger_once
        result = run_stage_trigger_once(decrypt_text)

        logger.info("[%s] 실행 완료: %s", self.AGENT_NAME, result)
        return {"agent": self.AGENT_NAME, "result": result}
