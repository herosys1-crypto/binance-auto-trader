"""🏗 Architect = 아키텍처 설계 담당!

Team: Planning
역할:
- 신 기능 = 어느 layer에?
   * 신 API? 신 Model? 신 Service? 신 Worker? 신 Team?
- 기존 시스템과 통합!
- 확장성 고려!
- 성능 영향 평가!
- 데이터 흐름 설계!

원칙:
- 사장님 자율 = 최상위!
- 헌법 준수!
- 대칭성!
- Single source of truth!
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class Architect(BaseAgent):
    TEAM = "planning"
    AGENT_NAME = "architect"

    LAYERS = [
        "API (backend/app/api/v1/)",
        "Model (backend/app/models/)",
        "Service (backend/app/services/)",
        "Worker (backend/app/workers/)",
        "Agent Team (backend/app/agents/)",
        "Alembic (backend/alembic/versions/)",
        "Frontend (backend/app/static/)",
    ]

    PATTERNS = [
        "🎯 신 기능 = 신 API + 신 JS + 신 카드!",
        "📊 신 학습 = 신 Model + 신 Worker + 신 Team!",
        "🔔 신 알림 = Alert Team + Telegram!",
        "🎓 신 학습 사이클 = Learning Team 확장!",
        "🐛 Bug fix = 기존 파일 최소 변경!",
    ]

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "layers": self.LAYERS,
            "patterns": self.PATTERNS,
        }
