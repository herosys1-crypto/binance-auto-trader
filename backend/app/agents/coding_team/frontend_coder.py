"""🎨 FrontendCoder = HTML/CSS/JS 프론트엔드 담당!

Team: Coding
역할:
- 대시보드 UI (index.html!)
- 팝업 페이지 (analysis.html, pump-ranking.html, bb-*!)
- JS 모듈 (strategy-suggestions.js, live-pump-dump-alerts.js 등!)
- API 호출 (api.js 활용!)
- 반응형 (모바일 최적화!)

원칙:
- 사장님 UX 우선!
- 심플하고 직관적!
- 캐시 버전 필수! (?v=20260816v163a!)
- postMessage/localStorage = 안전장치! (v134f/v160!)
- 3중 안전장치 (직접→postMessage→localStorage!)

기술 스택:
- Vanilla JS (no framework!)
- CSS variables (--color-*)
- Tailwind (className)
- No build step (직접 서빙!)
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class FrontendCoder(BaseAgent):
    TEAM = "coding"
    AGENT_NAME = "frontend_coder"

    RESPONSIBILITIES = [
        "Dashboard (index.html)",
        "Popup pages (analysis, pump-ranking, bb-breakdown)",
        "JS modules (per-card managers)",
        "API integration via api.js",
        "Cache busting (?v=YYYYMMDDvNNN)",
    ]

    UX_PRINCIPLES = [
        "사장님이 결정! 시스템 = 도우미!",
        "심플하고 직관적!",
        "위험 액션 = confirm dialog!",
        "성공/실패 = toast!",
        "3중 안전장치 (심볼 자동 fill!)",
        "60초 이내 자동 새로고침!",
    ]

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "responsibilities": self.RESPONSIBILITIES,
            "ux_principles": self.UX_PRINCIPLES,
            "notes": "실제 UI 작업 = Claude Code 세션에서 사장님과 함께!",
        }
