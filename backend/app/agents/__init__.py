"""🤖 서버 에이전트 시스템 (v132 신!)

사장님 사상 = 「10개 팀 + 40+ 에이전트 + 4계층 메모리」!

모든 에이전트 = BaseAgent 상속:
1. MemoryReader = 헌법/spec/default 자동 로드!
2. ConstitutionValidator = 헌법 자동 검증!
3. 실행 시 = 사장님 사상 100% 준수!

관련:
- docs/ARCHITECTURE_TEAM_AGENT_SPEC_v132.html = 종합 기획서
- backend/memory/README.md = 메모리 시스템 안내
"""
from app.agents.base import BaseAgent
from app.agents.memory_reader import MemoryReader
from app.agents.constitution_validator import (
    ConstitutionValidator,
    ConstitutionViolationError,
)

__all__ = [
    "BaseAgent",
    "MemoryReader",
    "ConstitutionValidator",
    "ConstitutionViolationError",
]
