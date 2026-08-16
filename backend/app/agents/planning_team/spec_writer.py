"""📖 SpecWriter = 명세 (Spec) 작성 담당!

Team: Planning
역할:
- Requirement → 상세 Spec!
- API 스펙 (endpoints, request/response)!
- DB 스펙 (모델, 마이그레이션)!
- UI 스펙 (와이어프레임, 버튼, 흐름)!
- Test 스펙 (시나리오, 예상 결과)!

원칙:
- 사장님이 이해할 수 있는 언어!
- Coding Team이 = 애매함 없이 구현 가능!
- 헌법 반영!

Output: docs/SPEC_v{N}_{feature}.md
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class SpecWriter(BaseAgent):
    TEAM = "planning"
    AGENT_NAME = "spec_writer"

    SPEC_SECTIONS = [
        "1. 배경 (사장님 요구 원문!)",
        "2. 목적 (WHY!)",
        "3. 요구사항 (WHAT!)",
        "4. 아키텍처 (HOW!)",
        "5. API 스펙!",
        "6. DB 스펙!",
        "7. UI 스펙!",
        "8. Test 스펙!",
        "9. 배포 계획!",
        "10. 헌법 준수 확인!",
    ]

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "responsibilities": self.SPEC_SECTIONS,
            "output_dir": "docs/",
            "naming": "SPEC_v{version}_{feature}.md",
        }
