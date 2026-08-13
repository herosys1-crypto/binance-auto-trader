"""🎓 LearningAgent = 학습 결과 → 다음 예측 반영!

역할:
- AnalysisAgent 인사이트 → 예측 시스템 조정!
- 심볼별 confidence 배율 (system_settings에!)
- 향후 predictor가 참조!
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)


LEARNING_KEY = "learning_agent_insights"


class LearningAgent(BaseAgent):
    TEAM = "learning"
    AGENT_NAME = "learning_agent"

    def execute(self, db: Session, analysis: dict[str, Any]) -> dict[str, Any]:
        """분석 결과 저장 + 조정!"""
        from app.models.system_setting import SystemSetting

        # 인사이트 = system_settings에 저장!
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "insights": analysis.get("insights", []),
            "top_trade_symbols": analysis.get("top_trade_symbols", []),
            "top_pred_symbols": analysis.get("top_pred_symbols", []),
            "big_moves_missed": analysis.get("big_moves_missed", []),
            "trail_late_count": analysis.get("trail_late_count", 0),
        }

        row = db.get(SystemSetting, LEARNING_KEY)
        if row:
            row.value = json.dumps(payload, ensure_ascii=False)
        else:
            db.add(SystemSetting(
                key=LEARNING_KEY,
                value=json.dumps(payload, ensure_ascii=False),
                description="Learning Agent = 인사이트 자동 저장 (v136!)",
            ))
        db.commit()

        logger.info(
            "[LearningAgent] 저장 완료: insights=%d top_trade=%d top_pred=%d",
            len(payload["insights"]),
            len(payload["top_trade_symbols"]),
            len(payload["top_pred_symbols"]),
        )
        return payload
