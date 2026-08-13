"""📚 MemoryAgent = 모든 학습 데이터 수집 + 정리!

역할:
- trade_learning_records 로드!
- strategy_suggestions (outcomes) 로드!
- market_observations 로드!
- 통합 = AnalysisAgent에 전달!
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class MemoryAgent(BaseAgent):
    TEAM = "learning"
    AGENT_NAME = "memory_agent"

    def execute(self, db: Session, days: int = 30) -> dict[str, Any]:
        """모든 학습 데이터 수집!"""
        from app.models.trade_learning_record import TradeLearningRecord
        from app.models.strategy_suggestion import StrategySuggestion
        from app.models.market_observation import MarketObservation

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # 1. 거래 기록!
        trades = db.execute(
            select(TradeLearningRecord)
            .where(TradeLearningRecord.updated_at >= cutoff)
        ).scalars().all()

        # 2. 예측 결과!
        suggestions = db.execute(
            select(StrategySuggestion)
            .where(StrategySuggestion.created_at >= cutoff)
        ).scalars().all()

        # 3. 시장 관찰!
        observations = db.execute(
            select(MarketObservation)
            .where(MarketObservation.observed_at >= cutoff)
        ).scalars().all()

        logger.info(
            "[MemoryAgent] 수집: trades=%d suggestions=%d observations=%d",
            len(trades), len(suggestions), len(observations),
        )

        return {
            "days": days,
            "trades": trades,
            "suggestions": suggestions,
            "observations": observations,
            "counts": {
                "trades": len(trades),
                "suggestions": len(suggestions),
                "observations": len(observations),
            }
        }
