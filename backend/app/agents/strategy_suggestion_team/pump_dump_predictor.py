"""📊 PumpDumpPredictor = 매일 급등/급락 예상 심볼!

Team: Strategy Suggestion
실행: 매일 06:30 UTC (스케줄!)

로직:
1. Binance 24h ticker 조회!
2. 급등 top 20 + 급락 top 20!
3. 각 심볼 = 지표 분석!
4. confidence_score 계산!
5. 결과 → EventBus publish!

관련 헌법:
- C01 (메인넷!)
- C02 (사장님 사상!)
"""
from __future__ import annotations

import logging
from decimal import Decimal

from app.agents.base import BaseAgent
from app.agents.orchestrator import EventType, get_event_bus

logger = logging.getLogger(__name__)


class PumpDumpPredictor(BaseAgent):
    TEAM = "strategy_suggestion"
    AGENT_NAME = "pump_dump_predictor"

    TOP_N = 20  # 급등/급락 각 20개

    def execute(self, db, decrypt_text) -> dict:
        """예상 심볼 분석 → EventBus publish!"""
        self.validate("PUMP_DUMP_PREDICT")

        from app.models.exchange_account import ExchangeAccount
        from app.integrations.binance.client import BinanceClient
        from sqlalchemy import select

        accounts = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalars().all()
        if not accounts:
            return {"error": "no mainnet accounts"}

        account = accounts[0]
        bc = BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=account.is_testnet,
        )

        # Binance 24h ticker!
        try:
            tickers = bc.get_24hr_ticker()
            if not isinstance(tickers, list):
                return {"error": "invalid ticker response"}
        except Exception as e:
            logger.warning("[%s] ticker 실패: %s", self.AGENT_NAME, e)
            return {"error": str(e)}

        # USDT 선물만!
        usdt = [t for t in tickers if str(t.get("symbol", "")).endswith("USDT")]
        # 24h 상승률 정렬!
        try:
            sorted_by_pump = sorted(
                usdt,
                key=lambda x: float(x.get("priceChangePercent", 0) or 0),
                reverse=True,
            )
        except Exception:
            return {"error": "sort failed"}

        pumps = sorted_by_pump[:self.TOP_N]
        dumps = sorted_by_pump[-self.TOP_N:][::-1]

        predictions = []
        for t in pumps:
            symbol = str(t.get("symbol"))
            change = float(t.get("priceChangePercent", 0) or 0)
            volume = float(t.get("quoteVolume", 0) or 0)
            # 급등 후 = 조정 예상! (SHORT 기회!)
            confidence = min(0.75 + (change - 20) / 100, 0.95) if change > 20 else 0.6
            predictions.append({
                "symbol": symbol,
                "type": "pump_end",  # 급등 후 반락 예상!
                "confidence": round(confidence, 3),
                "change_pct": round(change, 2),
                "volume": volume,
                "reason": f"24h +{change:.1f}% 급등, 조정 예상!",
            })
        for t in dumps:
            symbol = str(t.get("symbol"))
            change = float(t.get("priceChangePercent", 0) or 0)
            volume = float(t.get("quoteVolume", 0) or 0)
            # 급락 = 지속 하락 or 반등!
            confidence = min(0.70 + abs(change - 20) / 100, 0.90) if change < -20 else 0.6
            predictions.append({
                "symbol": symbol,
                "type": "dump_continuation",  # 급락 지속!
                "confidence": round(confidence, 3),
                "change_pct": round(change, 2),
                "volume": volume,
                "reason": f"24h {change:.1f}% 급락, 지속 하락 예상!",
            })

        logger.info(
            "[%s] 예측 완료: pumps=%d dumps=%d total=%d",
            self.AGENT_NAME, len(pumps), len(dumps), len(predictions),
        )

        # EventBus publish!
        bus = get_event_bus()
        bus.publish(EventType.DAILY_LEARNING_DONE, {
            "predictions": predictions,
            "pumps": len(pumps),
            "dumps": len(dumps),
        })

        return {"predictions": predictions, "total": len(predictions)}
