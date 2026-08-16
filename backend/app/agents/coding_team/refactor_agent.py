"""♻ RefactorAgent = 리팩토링 제안 담당!

Team: Coding
역할:
- 중복 코드 발견!
- 함수 분리 제안!
- 명명 개선 제안!
- 성능 최적화!
- 헌법 위반 발견!

원칙:
- 「기능 유지 + 코드 개선」!
- 사장님 승인 없이 = 배포 X!
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class RefactorAgent(BaseAgent):
    TEAM = "coding"
    AGENT_NAME = "refactor_agent"

    RESPONSIBILITIES = [
        "Duplicate code detection",
        "Function extraction",
        "Naming improvement",
        "Performance optimization",
        "Constitution violation detection",
    ]

    def get_capabilities(self) -> dict[str, Any]:
        return {"responsibilities": self.RESPONSIBILITIES}
