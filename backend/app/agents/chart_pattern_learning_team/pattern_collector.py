"""📊 PatternCollector = 심볼 1달 4H 캔들 수집!

Team: Chart Pattern Learning
1달 = 4H × 180 봉!
"""
from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class PatternCollector(BaseAgent):
    TEAM = "chart_pattern_learning"
    AGENT_NAME = "pattern_collector"

    KLINE_LIMIT = 200  # 1달치 = 4H × 180 봉 + 여유!

    def collect(self, bc, symbol: str) -> list | None:
        """심볼 = 1달치 4H 캔들 조회!"""
        try:
            kl = bc.get_klines(
                symbol=symbol, interval="4h", limit=self.KLINE_LIMIT,
            )
            if isinstance(kl, list) and len(kl) >= 60:
                return kl
        except Exception as e:
            logger.debug("[%s] %s 캔들 조회 실패: %s", self.AGENT_NAME, symbol, e)
        return None

    def top_symbols(self, bc, n: int = 100) -> list[str]:
        """스캔 대상 = 거래량 상위 N!"""
        try:
            tickers = bc.get_24hr_ticker()
            if not isinstance(tickers, list):
                return []
            usdt = [t for t in tickers if str(t.get("symbol", "")).endswith("USDT")]
            usdt.sort(key=lambda x: float(x.get("quoteVolume", 0) or 0), reverse=True)
            return [str(t["symbol"]) for t in usdt[:n]]
        except Exception as e:
            logger.warning("[%s] 심볼 조회 실패: %s", self.AGENT_NAME, e)
            return []
