"""💻 BackendCoder = FastAPI/SQLAlchemy/Python 백엔드 담당!

Team: Coding
역할:
- API endpoint 작성 (FastAPI!)
- 모델 정의 (SQLAlchemy!)
- 서비스 로직 (Python!)
- Worker 작성 (APScheduler!)
- Alembic 마이그레이션!

원칙 (헌법 v139!):
- Silent bug 금지! (실패 = warning 아닌 error!)
- 사장님 사상 우선!
- 검증 없는 코드 X!
- 대칭성!

기술 스택:
- Python 3.12
- FastAPI + SQLAlchemy 2.0
- PostgreSQL (Neon)
- Redis (mark price cache)
- APScheduler (workers)
- Binance Futures API
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class BackendCoder(BaseAgent):
    TEAM = "coding"
    AGENT_NAME = "backend_coder"

    RESPONSIBILITIES = [
        "FastAPI endpoint",
        "SQLAlchemy model + alembic migration",
        "Service logic (Python)",
        "Worker + Scheduler",
        "Binance API integration",
    ]

    STYLE_GUIDE = {
        "language": "Python 3.12",
        "async": "async/await for I/O",
        "types": "Type hints (mypy-friendly)",
        "logging": "logger.info/warning/error (Silent bug 금지!)",
        "errors": "명시적 raise + 사장님 안내 메시지!",
        "tests": "pytest + fixtures (mock Binance!)",
    }

    def get_capabilities(self) -> dict[str, Any]:
        """이 에이전트가 할 수 있는 일!"""
        return {
            "responsibilities": self.RESPONSIBILITIES,
            "style_guide": self.STYLE_GUIDE,
            "notes": "실제 코드 작성은 = Claude Code 세션에서 사장님과 함께!",
        }
