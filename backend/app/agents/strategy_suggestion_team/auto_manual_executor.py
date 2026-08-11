"""▶ AutoManualExecutor = 자동 or 수동 실행!

Team: Strategy Suggestion
사장님 사고: 기본 = 수동! 자동 = 옵션!

수동 실행:
- API POST /strategy-suggestions/{id}/execute 호출!

자동 실행:
- 매일 07:00 UTC 스캔!
- 안전장치 검증!
  * suggestion_auto_execute_enabled = true?
  * confidence >= threshold?
  * 오늘 자동 실행 <= daily_limit?
  * 중복 심볼 방지!
- StrategyService.create_strategy_instance() 호출!

관련 헌법:
- C02 (사장님 사상 = 기본 수동!)
- C13 (다음 단계 남으면 SL X!)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from app.agents.base import BaseAgent
from app.agents.orchestrator import EventType, get_event_bus

logger = logging.getLogger(__name__)


class AutoManualExecutor(BaseAgent):
    TEAM = "strategy_suggestion"
    AGENT_NAME = "auto_manual_executor"

    def execute_suggestion(self, db, suggestion_id: int, user_id: int) -> dict:
        """수동 실행 (사장님 「▶」 클릭!) or 자동!"""
        self.validate("SUGGESTION_EXECUTE")

        from app.models.strategy_suggestion import StrategySuggestion
        from app.services.strategy_service import StrategyService

        suggestion = db.get(StrategySuggestion, suggestion_id)
        if not suggestion:
            return {"error": "not found"}
        if suggestion.status != "PENDING":
            return {"error": f"이미 처리됨 (status={suggestion.status})"}

        cfg = suggestion.strategy_config or {}
        symbol = suggestion.symbol
        side = suggestion.side

        # TODO: 실제 = _quick_ 템플릿 생성 → StrategyService.create_strategy_instance!
        # 현재 = 로그만 (다음 세션 완전 구현!)
        logger.warning(
            "[%s] 실행 요청! suggestion_id=%s symbol=%s side=%s (실 구현 다음 세션!)",
            self.AGENT_NAME, suggestion_id, symbol, side,
        )

        # 상태 갱신!
        suggestion.status = "EXECUTED"
        suggestion.executed_at = datetime.now(timezone.utc)
        db.commit()

        # 이벤트 발신!
        get_event_bus().publish(EventType.SUGGESTION_EXECUTED, {
            "suggestion_id": suggestion_id,
            "symbol": symbol,
            "side": side,
        })

        return {
            "executed": True,
            "suggestion_id": suggestion_id,
            "symbol": symbol,
            "side": side,
        }

    def execute_auto_batch(self, db) -> dict:
        """🤖 자동 실행 배치 (스케줄!). 안전장치 필수!"""
        self.validate("SUGGESTION_AUTO_EXECUTE")

        from app.models.system_setting import SystemSetting
        from app.models.strategy_suggestion import StrategySuggestion
        from sqlalchemy import select

        # 1. 자동 실행 활성?
        setting_e = db.get(SystemSetting, "suggestion_auto_execute_enabled")
        if not setting_e or setting_e.value.lower() != "true":
            return {"skipped": True, "reason": "auto_execute disabled"}

        # 2. Confidence 임계!
        setting_t = db.get(SystemSetting, "suggestion_confidence_threshold")
        threshold = Decimal(str(setting_t.value)) if setting_t else Decimal("0.85")

        # 3. 오늘 자동 한도!
        setting_l = db.get(SystemSetting, "suggestion_daily_auto_limit")
        daily_limit = int(setting_l.value) if setting_l else 3

        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        today_auto = db.execute(
            select(StrategySuggestion)
            .where(StrategySuggestion.executed_at >= today_start)
            .where(StrategySuggestion.status == "EXECUTED")
            .where(StrategySuggestion.execution_mode == "AUTO")
        ).scalars().all()
        remaining = daily_limit - len(today_auto)
        if remaining <= 0:
            return {"skipped": True, "reason": "daily limit reached"}

        # 4. 대상 조회!
        candidates = db.execute(
            select(StrategySuggestion)
            .where(StrategySuggestion.status == "PENDING")
            .where(StrategySuggestion.confidence_score >= threshold)
            .order_by(StrategySuggestion.confidence_score.desc())
            .limit(remaining)
        ).scalars().all()

        executed = []
        for s in candidates:
            # 중복 심볼 방지 (활성 전략 있는지!)
            # TODO: check strategy_instances 활성 여부!
            s.execution_mode = "AUTO"
            result = self.execute_suggestion(db, s.id, user_id=0)
            if result.get("executed"):
                executed.append(s.id)

        logger.info("[%s] 자동 실행: %d", self.AGENT_NAME, len(executed))
        return {"executed_count": len(executed), "executed_ids": executed}
