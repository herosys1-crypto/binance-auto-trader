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
        # 🌟 v132: 4 시나리오 = LONG + SHORT 균형!

        # 급등 상위 = 2가지 시나리오!
        for i, t in enumerate(pumps):
            symbol = str(t.get("symbol"))
            change = float(t.get("priceChangePercent", 0) or 0)
            volume = float(t.get("quoteVolume", 0) or 0)
            if i < self.TOP_N // 2:
                # 상위 절반 = SHORT (급등 후 반락!)
                confidence = min(0.75 + (change - 20) / 100, 0.95) if change > 20 else 0.6
                predictions.append({
                    "symbol": symbol,
                    "type": "pump_end",  # 급등 후 반락!
                    "side": "SHORT",
                    "confidence": round(confidence, 3),
                    "change_pct": round(change, 2),
                    "volume": volume,
                    "reason": f"24h +{change:.1f}% 급등, 조정 예상 (SHORT!)",
                })
            else:
                # 하위 절반 = LONG (지속 상승 모멘텀!)
                confidence = min(0.65 + (change - 10) / 100, 0.85) if change > 10 else 0.55
                predictions.append({
                    "symbol": symbol,
                    "type": "pump_continuation",  # 상승 지속!
                    "side": "LONG",
                    "confidence": round(confidence, 3),
                    "change_pct": round(change, 2),
                    "volume": volume,
                    "reason": f"24h +{change:.1f}% 상승 모멘텀 지속 예상 (LONG!)",
                })

        # 급락 상위 = 2가지 시나리오!
        for i, t in enumerate(dumps):
            symbol = str(t.get("symbol"))
            change = float(t.get("priceChangePercent", 0) or 0)
            volume = float(t.get("quoteVolume", 0) or 0)
            if i < self.TOP_N // 2:
                # 상위 절반 = SHORT (지속 하락!)
                confidence = min(0.70 + abs(change - 20) / 100, 0.90) if change < -20 else 0.6
                predictions.append({
                    "symbol": symbol,
                    "type": "dump_continuation",  # 급락 지속!
                    "side": "SHORT",
                    "confidence": round(confidence, 3),
                    "change_pct": round(change, 2),
                    "volume": volume,
                    "reason": f"24h {change:.1f}% 급락, 지속 하락 예상 (SHORT!)",
                })
            else:
                # 하위 절반 = LONG (급락 후 반등 기대!)
                confidence = min(0.60 + abs(change - 10) / 100, 0.80) if change < -10 else 0.5
                predictions.append({
                    "symbol": symbol,
                    "type": "dump_reversal",  # 급락 후 반등!
                    "side": "LONG",
                    "confidence": round(confidence, 3),
                    "change_pct": round(change, 2),
                    "volume": volume,
                    "reason": f"24h {change:.1f}% 급락, 반등 기대 (LONG!)",
                })

        # 🌟 v133c (2026-08-13 사장님!): 급등락 진행 중 실시간 진입!
        # = 5분 klines 조회 = 최근 5분 변동 큰 심볼 = 즉시 진입 기회!
        try:
            live_predictions = self._detect_live_pump_dump(bc, pumps + dumps)
            predictions.extend(live_predictions)
            logger.info(
                "[%s] 실시간 급등락 진입: %d건 추가!",
                self.AGENT_NAME, len(live_predictions),
            )
        except Exception as e:
            logger.warning("[%s] 실시간 감지 실패: %s", self.AGENT_NAME, e)

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

    def _detect_live_pump_dump(self, bc, candidates: list) -> list:
        """🌟 v133c: 실시간 급등락 진행 중 감지!

        로직:
        - 상위 20 pump + 20 dump 심볼 = 5분 klines 조회!
        - 최근 5분봉 변동 > 3% = 실시간 급등/급락!
        - LONG (pump_live) = 급등 중 즉시 진입!
        - SHORT (dump_live) = 급락 중 즉시 진입!

        신뢰도 = 5분 변동 크기 기반!
        """
        live_preds = []
        symbols = set()

        # 후보 심볼 수집 (중복 제거!)
        for t in candidates[:40]:
            symbol = str(t.get("symbol", ""))
            if not symbol or not symbol.endswith("USDT"):
                continue
            symbols.add(symbol)

        # 각 심볼 = 5분 klines 조회!
        for symbol in list(symbols)[:30]:  # 최대 30 심볼 (rate limit!)
            try:
                klines = bc.get_klines(symbol=symbol, interval="5m", limit=3)
                if not isinstance(klines, list) or len(klines) < 2:
                    continue
                # 최근 완료 5분봉 = klines[-2] (klines[-1] = 진행 중!)
                last = klines[-2]
                # kline 배열: [open_time, open, high, low, close, volume, ...]
                open_price = float(last[1])
                close_price = float(last[4])
                if open_price <= 0:
                    continue
                change_5m = ((close_price - open_price) / open_price) * 100

                # 5분 변동 > 3% = 실시간 급등/급락!
                if change_5m >= 3.0:
                    # 급등 중 = LONG 즉시 진입!
                    confidence = min(0.65 + (change_5m - 3) / 20, 0.90)
                    live_preds.append({
                        "symbol": symbol,
                        "type": "pump_live",  # 🌟 신 타입!
                        "side": "LONG",
                        "confidence": round(confidence, 3),
                        "change_pct": round(change_5m, 2),
                        "volume": 0,
                        "reason": f"🚀 5분 +{change_5m:.1f}% 실시간 급등! 즉시 LONG 진입!",
                    })
                elif change_5m <= -3.0:
                    # 급락 중 = SHORT 즉시 진입!
                    confidence = min(0.65 + (abs(change_5m) - 3) / 20, 0.90)
                    live_preds.append({
                        "symbol": symbol,
                        "type": "dump_live",  # 🌟 신 타입!
                        "side": "SHORT",
                        "confidence": round(confidence, 3),
                        "change_pct": round(change_5m, 2),
                        "volume": 0,
                        "reason": f"📉 5분 {change_5m:.1f}% 실시간 급락! 즉시 SHORT 진입!",
                    })
            except Exception:
                continue

        return live_preds
