"""🗂 SuggestionManager = 유지/삭제 관리!

Team: Strategy Suggestion
실행: 매 1시간 (스케줄!)

로직:
1. system_settings.suggestion_auto_dismiss_hours 확인 (default 24!)
2. 그 시간 초과된 PENDING = EXPIRED 상태!
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class SuggestionManager(BaseAgent):
    TEAM = "strategy_suggestion"
    AGENT_NAME = "suggestion_manager"

    def execute(self, db) -> dict:
        """미실행 = 자동 삭제!"""
        self.validate("SUGGESTION_MANAGE")

        from app.models.strategy_suggestion import StrategySuggestion
        from app.models.system_setting import SystemSetting
        from sqlalchemy import select

        # 자동 삭제 시간 조회!
        setting = db.get(SystemSetting, "suggestion_auto_dismiss_hours")
        hours = 24
        if setting:
            try:
                hours = int(setting.value)
            except Exception:
                hours = 24

        if hours <= 0:
            return {"expired": 0, "reason": "auto_dismiss disabled"}

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        expired = db.execute(
            select(StrategySuggestion)
            .where(StrategySuggestion.status == "PENDING")
            .where(StrategySuggestion.created_at < cutoff)
        ).scalars().all()

        for s in expired:
            s.status = "EXPIRED"
            s.dismissed_at = datetime.now(timezone.utc)
            s.dismissed_reason = f"자동 삭제 ({hours}h 미실행!)"

        db.commit()
        logger.info("[%s] 자동 삭제: %d", self.AGENT_NAME, len(expired))
        return {"expired": len(expired), "hours": hours}
