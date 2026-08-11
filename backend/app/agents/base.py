"""🤖 BaseAgent = 모든 서버 에이전트의 기반!

사장님 사상:
- 모든 에이전트 = 메모리 참조!
- 헌법 자동 검증!
- 실행 결과 = 감사 가능!

사용:
    class MyAgent(BaseAgent):
        TEAM = "entry"
        AGENT_NAME = "stage_trigger_agent"

        def execute(self):
            # 1. 헌법 자동 검증!
            self.validate("STAGE_ENTRY")
            # 2. 실행!
            ...
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.memory_reader import MemoryReader
from app.agents.constitution_validator import (
    ConstitutionValidator,
    ConstitutionViolationError,
)

logger = logging.getLogger(__name__)


class BaseAgent:
    """모든 서버 에이전트의 기반 클래스.

    상속 시:
    - TEAM: 소속 팀 (entry/tp/sl/monitoring/alert/capital/analysis/maintenance/ui/audit)
    - AGENT_NAME: 에이전트 이름 (snake_case)
    """
    TEAM: str = "unknown"
    AGENT_NAME: str = "base_agent"

    def __init__(self):
        # 1. 메모리 로드 (헌법 + spec + default!)
        self.memory = MemoryReader(team=self.TEAM)
        self.constitution_dict = self.memory.load_constitution()
        self.specs_dict = self.memory.load_specs()
        self.defaults_dict = self.memory.load_defaults()
        # 2. 헌법 검증기 초기화
        self.validator = ConstitutionValidator(self.constitution_dict)
        # 3. 실행 로그
        logger.info(
            "[%s/%s] 에이전트 초기화! (헌법=%d, spec=%d, default=%d)",
            self.TEAM, self.AGENT_NAME,
            len(self.constitution_dict), len(self.specs_dict), len(self.defaults_dict),
        )

    def validate(self, action: str, context: dict[str, Any] | None = None) -> bool:
        """헌법 자동 검증!

        Raises:
            ConstitutionViolationError: 위반 시!
        """
        try:
            return self.validator.check(action, context)
        except ConstitutionViolationError as e:
            logger.error("[%s/%s] 헌법 위반! %s", self.TEAM, self.AGENT_NAME, e)
            # 위반 시 = 재발 방지 = memory에 기록 (다음 세션!)
            self._record_violation(action, str(e))
            raise

    def _record_violation(self, action: str, error_msg: str) -> None:
        """헌법 위반 = memory/silent_bugs/에 기록 (Audit Team 참조!)."""
        # TODO: 자동 파일 저장 로직 (Audit Team이 다음 세션에 검토!)
        logger.warning(
            "[audit] 헌법 위반 기록! team=%s agent=%s action=%s error=%s",
            self.TEAM, self.AGENT_NAME, action, error_msg,
        )

    def get_default(self, name: str) -> str | None:
        """신 default 참조 (예: 'leverage_2x')."""
        return self.memory.get_default(name)

    def get_spec(self, name: str) -> str | None:
        """spec 참조 (예: 'retry_after_liquidation_v131')."""
        return self.memory.get_spec(name)

    def execute(self):
        """서브클래스에서 구현! (기본 실행 로직)"""
        raise NotImplementedError(
            f"{self.__class__.__name__}.execute() = 서브클래스에서 구현 필수!"
        )
