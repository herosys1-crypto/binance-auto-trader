"""📝 RequirementAnalyzer = 사장님 요구 분석 담당!

Team: Planning
역할:
- 사장님 자연어 요구 → 명확한 요구사항!
- 모호함 감지 → 사장님 재확인!
- 유사 기능 발견 → 통합 제안!
- 우선순위 힌트 (긴급/중요/장기!)
- 제약조건 파악 (mainnet/실자금!)

원칙:
- 사장님 사상 = 절대 우선!
- 모호하면 = 명확히 물음!
- 기존 시스템과 충돌 = 경고!
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class RequirementAnalyzer(BaseAgent):
    TEAM = "planning"
    AGENT_NAME = "requirement_analyzer"

    ANALYSIS_STEPS = [
        "1. 사장님 요구 텍스트 파싱!",
        "2. 명시적 요구 추출 (예: 'X 만들어줘')",
        "3. 암묵적 요구 추론 (예: '자동으로' = 옵션 필요!)",
        "4. 유사 기능 검색 (기존 시스템과 중복?)",
        "5. 제약조건 확인 (mainnet? 실자금? 헌법?)",
        "6. 명확 요구사항 문서 생성!",
    ]

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "responsibilities": self.ANALYSIS_STEPS,
            "output": "RequirementDocument (SpecWriter에 전달!)",
        }
