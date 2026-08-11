"""🎯 StrategySuggestionGenerator = 신 전략 draft 자동 생성! ⭐ 핵심!

Team: Strategy Suggestion Team
Mission: 예측 심볼 = 전략 draft = 사장님 검토용!

관련 헌법:
- C02 (사장님 사상 우선!) = 기본 수동!
- 신 default (2x, TP 10/15/20/25, 강제 SL -15%!)

v132 = Phase MVP = 실 구현 = 다음 세션!
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class StrategySuggestionGenerator(BaseAgent):
    """신 전략 draft 자동 생성!"""
    TEAM = "strategy_suggestion"
    AGENT_NAME = "strategy_suggestion_generator"

    def execute(self, predicted_symbols: list[dict]) -> dict:
        """실행 = 예측 심볼 리스트 → 전략 draft 생성!

        Args:
            predicted_symbols: pump_dump_predictor 결과!
                [{"symbol": "BTCUSDT", "type": "dump_continuation",
                  "confidence": 0.87, "reason": "OBV..."}, ...]

        Returns:
            {"suggestions": [...], "total": N}
        """
        # 1. 헌법 자동 검증!
        try:
            self.validate("STRATEGY_SUGGESTION_GENERATE")
        except Exception as e:
            logger.error("[%s] 헌법 위반! %s", self.AGENT_NAME, e)
            raise

        suggestions = []
        for p in predicted_symbols or []:
            _config = self._build_default_config(
                side=self._infer_side(p["type"]),
                symbol=p["symbol"],
            )
            _suggestion = {
                "symbol": p["symbol"],
                "side": _config["side"],
                "suggestion_type": p["type"],
                "strategy_config": _config,
                "confidence_score": p.get("confidence", 0.5),
                "reason": p.get("reason", ""),
                "status": "PENDING",
                "execution_mode": "MANUAL",  # ⭐ 기본 수동!
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            suggestions.append(_suggestion)
            # TODO: DB 저장 (다음 세션!)

        logger.info("[%s] 생성 완료: %d 제안", self.AGENT_NAME, len(suggestions))
        return {"suggestions": suggestions, "total": len(suggestions)}

    def _infer_side(self, suggestion_type: str) -> str:
        """제안 타입 → side 자동!"""
        if suggestion_type in ("dump_continuation", "pump_end"):
            return "SHORT"
        elif suggestion_type in ("pump_expected", "reversal_up"):
            return "LONG"
        return "SHORT"  # default

    def _build_default_config(self, side: str, symbol: str) -> dict:
        """사장님 신 default 전략 config!

        기본 = safer 세팅 (사장님 검토용!):
        - 레버리지 2x
        - 자본 500 USDT (1단계)
        - TP 10/15/20/25
        - TP qty 10/15/20/25
        - TP1_override 25%
        - 강제 SL -15%
        - 시작가 = MARKET (즉시!)
        """
        return {
            "symbol": symbol,
            "side": side,
            "leverage": 2,  # 신 default (v132!)
            "start_price": None,  # MARKET!
            "capitals": [500, 500, 500, 500],  # 4단계
            "trigger_percents": [None, 10, 20, 20],
            "tp1_percent": 10,
            "tp2_percent": 15,
            "tp3_percent": 20,
            "tp4_percent": 25,
            "tp1_qty_ratio": 10,
            "tp2_qty_ratio": 15,
            "tp3_qty_ratio": 20,
            "tp4_qty_ratio": 25,
            "tp1_pct_override": 25,
            "force_sl_enabled_override": True,
            "force_sl_roi_override": 15,  # -15%
            "stop_loss_percent_of_capital": 90,
            "retry_after_liquidation_enabled": False,  # 기본 OFF (사장님 자율!)
            "retry_trigger_pct": 10,
        }
