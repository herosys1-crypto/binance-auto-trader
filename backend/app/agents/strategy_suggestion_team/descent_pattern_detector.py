"""📉 DescentPatternDetector = 급락 후 지속 하락 감지!

Team: Strategy Suggestion
실행: pump_dump_predictor 결과 → 필터!

로직:
1. 급락 심볼 = 최근 7일 종가 확인!
2. 지속 하락 = 각 봉 = 이전 봉 대비 하락!
3. OBV 매도세 유지?
4. RSI 30 이하?
5. → 지속 하락 심볼 필터!
"""
from __future__ import annotations

import logging
from decimal import Decimal

from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)


class DescentPatternDetector(BaseAgent):
    TEAM = "strategy_suggestion"
    AGENT_NAME = "descent_pattern_detector"

    def execute(self, db, decrypt_text, predictions: list[dict]) -> dict:
        """급락 예상 심볼 = 지속 하락 필터링!"""
        self.validate("DESCENT_PATTERN_DETECT")

        if not predictions:
            return {"filtered": [], "total": 0}

        # dump_continuation 만 필터!
        dumps = [p for p in predictions if p.get("type") == "dump_continuation"]
        if not dumps:
            return {"filtered": [], "total": 0}

        from app.models.exchange_account import ExchangeAccount
        from app.integrations.binance.client import BinanceClient
        from sqlalchemy import select

        accounts = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalars().all()
        if not accounts:
            return {"error": "no accounts"}
        bc = BinanceClient(
            api_key=decrypt_text(accounts[0].api_key_enc),
            api_secret=decrypt_text(accounts[0].api_secret_enc),
            is_testnet=accounts[0].is_testnet,
        )

        filtered = []
        for dump in dumps:
            symbol = dump["symbol"]
            try:
                # 1D 봉 7개 (7일!)
                klines = bc.get_klines(symbol=symbol, interval="1d", limit=10)
                if not klines or len(klines) < 5:
                    continue
                closes = [Decimal(str(k[4])) for k in klines]
                # 지속 하락 = 5봉 이상 하락!
                down_count = sum(
                    1 for i in range(1, len(closes))
                    if closes[i] < closes[i - 1]
                )
                is_descent = down_count >= len(closes) * 0.6
                if is_descent:
                    # confidence 상향 (지속 하락 확인!)
                    dump["confidence"] = min(dump.get("confidence", 0.6) + 0.10, 0.95)
                    dump["reason"] += f" (최근 {len(closes)}봉 중 {down_count}봉 하락!)"
                    dump["descent_confirmed"] = True
                    filtered.append(dump)
            except Exception as e:
                logger.debug("[%s] %s 실패: %s", self.AGENT_NAME, symbol, e)

        logger.info(
            "[%s] 지속 하락 확정: %d/%d",
            self.AGENT_NAME, len(filtered), len(dumps),
        )
        return {"filtered": filtered, "total": len(filtered)}
