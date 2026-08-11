"""🎯 StrategySuggestionGenerator = 신 전략 draft 실 DB 저장! ⭐

Team: Strategy Suggestion
사장님 요구: 매일 자동 제안 = 사장님 검토용!

로직:
1. 예상 심볼 → 전략 config 생성!
2. 사장님 신 default 자동!
3. DB `strategy_suggestions` 저장!
4. EventBus publish (SUGGESTION_CREATED!)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from app.agents.base import BaseAgent
from app.agents.orchestrator import EventType, get_event_bus

logger = logging.getLogger(__name__)


class StrategySuggestionGenerator(BaseAgent):
    TEAM = "strategy_suggestion"
    AGENT_NAME = "strategy_suggestion_generator"

    def execute(self, db, predictions: list[dict]) -> dict:
        """예상 심볼 → 전략 draft DB 저장!"""
        self.validate("STRATEGY_SUGGESTION_GENERATE")

        if not predictions:
            return {"created": 0, "total": 0}

        from app.models.strategy_suggestion import StrategySuggestion
        from sqlalchemy import select

        # 중복 방지 = 오늘 이미 생성된 심볼 skip!
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        existing_today = db.execute(
            select(StrategySuggestion.symbol)
            .where(StrategySuggestion.created_at >= today_start)
            .where(StrategySuggestion.status == "PENDING")
        ).scalars().all()
        existing_set = set(existing_today)

        created_ids = []
        bus = get_event_bus()
        for p in predictions:
            symbol = p["symbol"]
            if symbol in existing_set:
                continue  # 오늘 이미 있음!

            side = self._infer_side(p["type"])
            config = self._build_config(symbol, side, db=db)  # 프로필 참조!

            suggestion = StrategySuggestion(
                symbol=symbol,
                side=side,
                suggestion_type=p["type"],
                strategy_config=config,
                confidence_score=Decimal(str(p.get("confidence", 0.5))),
                reason=p.get("reason", ""),
                status="PENDING",
                execution_mode="MANUAL",  # ⭐ 기본 수동!
            )
            db.add(suggestion)
            db.flush()
            created_ids.append(suggestion.id)

            # 이벤트 발신!
            bus.publish(EventType.SUGGESTION_CREATED, {
                "suggestion_id": suggestion.id,
                "symbol": symbol,
                "side": side,
                "confidence": p.get("confidence"),
            })

        db.commit()
        logger.info("[%s] 생성 완료: %d", self.AGENT_NAME, len(created_ids))
        return {"created": len(created_ids), "created_ids": created_ids}

    def _infer_side(self, suggestion_type: str) -> str:
        if suggestion_type in ("dump_continuation", "pump_end"):
            return "SHORT"
        return "LONG"

    def _build_config(self, symbol: str, side: str, db=None) -> dict:
        """사장님 default 프로필 참조! (v132 신!)"""
        # 사장님 default 프로필 로드!
        profile_config = self._load_default_profile(db) if db else None
        if not profile_config:
            # fallback = 하드코딩 default!
            profile_config = {
                "leverage": 2,
                "capitals": [500, 500, 500, 500],
                "trigger_percents": [None, 10, 20, 20],
                "tp1_percent": 10, "tp2_percent": 15,
                "tp3_percent": 20, "tp4_percent": 25,
                "tp1_qty_ratio": 10, "tp2_qty_ratio": 15,
                "tp3_qty_ratio": 20, "tp4_qty_ratio": 25,
                "tp1_pct_override": 25,
                "force_sl_enabled_override": True,
                "force_sl_roi_override": 15,
                "stop_loss_percent_of_capital": 90,
                "start_price": None,
                "retry_after_liquidation_enabled": False,
                "retry_trigger_pct": 10,
            }
        # symbol + side 추가!
        return {"symbol": symbol, "side": side, **profile_config}

    def _load_default_profile(self, db) -> dict | None:
        """system_settings에서 default 프로필 config 로드!"""
        import json
        from app.models.system_setting import SystemSetting

        _p_row = db.get(SystemSetting, "suggestion_default_profiles")
        _d_row = db.get(SystemSetting, "suggestion_current_default_profile")
        if not _p_row or not _d_row:
            return None
        try:
            profiles = json.loads(_p_row.value)
            default_name = _d_row.value
            for p in profiles:
                if p.get("name") == default_name:
                    return p.get("config") or {}
        except Exception as e:
            logger.warning("[%s] default profile 로드 실패: %s", self.AGENT_NAME, e)
        return None
