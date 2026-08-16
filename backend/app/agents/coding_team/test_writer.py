"""✅ TestWriter = pytest 테스트 작성 담당!

Team: Coding
역할:
- 단위 테스트 (functions/classes)!
- 통합 테스트 (API endpoints!)
- E2E 테스트 (workflow!)
- Fixture 관리 (mock Binance/DB!)
- 회귀 테스트 (silent bug 방지!)

원칙 (헌법 v127!):
- 검증 없는 코드 X!
- Silent bug 검증!
- Backwards compatibility 보장!
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class TestWriter(BaseAgent):
    TEAM = "coding"
    AGENT_NAME = "test_writer"

    RESPONSIBILITIES = [
        "Unit tests (pytest)",
        "Integration tests (FastAPI TestClient)",
        "E2E tests (full workflow)",
        "Fixtures (mock Binance, mock DB)",
        "Regression tests (silent bug prevention)",
    ]

    def get_capabilities(self) -> dict[str, Any]:
        return {"responsibilities": self.RESPONSIBILITIES}
