"""📌 PriorityManager = 우선순위 관리 담당!

Team: Planning
역할:
- CRITICAL / HIGH / MEDIUM / LOW 분류!
- 즉시 vs 다음 세션 결정!
- Roadmap 관리!
- 진행 상태 tracking!
- 스택 관리 (BLOCKED / IN_PROGRESS / DONE)!

원칙:
- 사장님 실 손실 = CRITICAL 즉시!
- 사장님 요구 = HIGH!
- 자동화 = MEDIUM!
- 리팩토링 = LOW!
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class PriorityManager(BaseAgent):
    TEAM = "planning"
    AGENT_NAME = "priority_manager"

    PRIORITY_MATRIX = {
        "CRITICAL": [
            "실자금 손실 발생 → 즉시 fix!",
            "silent bug 발견 → 즉시!",
            "헌법 위반 → 즉시!",
        ],
        "HIGH": [
            "사장님 직접 요구!",
            "실 매매 관련 기능!",
            "사장님 대시보드 UX!",
        ],
        "MEDIUM": [
            "자동화 확장!",
            "학습 시스템!",
            "성능 최적화!",
        ],
        "LOW": [
            "리팩토링!",
            "문서화!",
            "테스트 커버리지 확장!",
        ],
    }

    def get_capabilities(self) -> dict[str, Any]:
        return {"priority_matrix": self.PRIORITY_MATRIX}
