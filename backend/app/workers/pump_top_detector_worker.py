"""🎯 v219 (2026-08-22 사장님!): 급등 정점 감지 워커 = 7중 확인!

사장님 verbatim (실 성공 로직!):
"급등하는 심볼 4시간봉 최상단 볼밴 최상단밖 obv 최고점
 macd rsi cci 모든 지표가 최고점일때 포지션 진입 전체자산에 1-2% 진입"

7중 정점 조건:
1. 4H BB 최상단 밖 (closes[-1] > BB upper[-1])
2. OBV 최고점 (LOOKBACK=20)
3. MACD 히스토그램 최고점 + 꺾임
4. RSI ≥70 + 꺾임
5. CCI ≥200 + 꺾임
6. 동시 최고점 (2~5 모두 만족!)
7. 급등 후 정점 (24h ≥+15% + high 최고점!)

= 모두 통과 시 = Redis 알람 → auto_short_at_top_worker가 자동 진입!
= 신뢰도 = 0.85 + 0.02 × (passed - 5) = 최대 0.89
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_LIKE
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.services.bb_4h_band_analyzer import BB4HBandAnalyzer
from app.services.chart_analyzer import ChartAnalyzer

logger = logging.getLogger(__name__)

LOOKBACK = 20        # 최고점 판정 창!
MAX_SYMBOLS = 60     # 스캔 상한 (API 부담!)
# 🎯 v220 사장님 신 사상 (2026-08-22):
# "급등락이 10 20 30 40 등등 상관없어 차트가 하락으로 시작할수 있는 타이핑에!"
# = 크기 무관! but API pre-filter 최소치 5% (완전 제거 X = 하락 종목 필터!)
MIN_24H_CHANGE = 5.0   # 15→5 = 사장님 사상 반영! (7중 지표만 중심!)
ALERT_TTL_SEC = 1800   # 알람 유효 30분!
MIN_CONFIDENCE = 0.85  # 최소 신뢰도 (7/7 통과 = 남발 차단!)


class PumpTopDetector:
    """7중 정점 감지 (사장님 실 성공 로직!)."""

    @classmethod
    def check_7_signals(cls, kl_4h: list, ticker_24h: dict) -> dict:
        """7중 조건 검증!

        Args:
            kl_4h: 4시간봉 klines (Binance format!)
            ticker_24h: 24h ticker dict

        Returns:
            dict: {detected, passed, confidence, signals, close, rsi, cci_last}
        """
        try:
            closes = [float(k[4]) for k in kl_4h]
            highs = [float(k[2]) for k in kl_4h]

            # BB!
            mid, up, lo = BB4HBandAnalyzer.bollinger(closes)

            # 1. BB 최상단 밖!
            c1 = up[-1] is not None and closes[-1] > up[-1]

            # 2. OBV 최고점!
            obv = [float(x) for x in ChartAnalyzer.compute_obv(kl_4h)]
            c2 = len(obv) >= LOOKBACK and obv[-1] >= max(obv[-LOOKBACK:])

            # 3. MACD 히스토그램 최고점 + 꺾임!
            c3 = cls._macd_hist_peak_turned(closes)

            # 4. RSI ≥70 + 꺾임!
            rsi_now = BB4HBandAnalyzer._calc_rsi(closes)
            rsi_prev = BB4HBandAnalyzer._calc_rsi(closes[:-1])
            c4 = (rsi_now is not None and rsi_prev is not None
                  and rsi_now >= 70 and rsi_now < rsi_prev)

            # 5. CCI ≥200 + 꺾임!
            cci = ChartAnalyzer.compute_cci(kl_4h)
            c5 = len(cci) >= 2 and cci[-1] >= 200 and cci[-1] < cci[-2]

            # 6. 동시 최고점 (2~5 모두!)
            c6 = c2 and c3 and c4 and c5

            # 🎯 v220 사장님 사상 (2026-08-22): 크기 무관! 최고점 반전만!
            # 이전: chg24 ≥ 15% 강제 (10/20% 놓침!)
            # 신: high 최고점 = 반전 후보 판정만!
            chg24 = float(ticker_24h.get("priceChangePercent", 0) or 0)
            c7 = (len(highs) >= LOOKBACK
                  and highs[-1] >= max(highs[-LOOKBACK:]))

            passed = sum([c1, c2, c3, c4, c5, c6, c7])
            confidence = 0.85 + 0.02 * (passed - 5) if passed >= 5 else 0.0

            return {
                "detected": passed == 7,
                "passed": passed,
                "confidence": round(confidence, 4),
                "signals": {
                    "bb_upper": c1, "obv_peak": c2, "macd_peak": c3,
                    "rsi_peak": c4, "cci_peak": c5, "all_peak": c6, "pump": c7,
                },
                "close": closes[-1],
                "rsi": rsi_now,
                "cci_last": cci[-1] if cci else None,
                "change_24h": chg24,
            }
        except Exception as e:
            logger.warning("[pump_top_v219] check_7_signals 실패: %s", e)
            return {"detected": False, "passed": 0, "confidence": 0.0}

    @staticmethod
    def _macd_hist_peak_turned(closes: list[float]) -> bool:
        """MACD 히스토그램 최고점 + 꺾임 감지!"""
        if len(closes) < 35:
            return False
        try:
            ema12 = BB4HBandAnalyzer._calc_ema(closes, 12)
            ema26 = BB4HBandAnalyzer._calc_ema(closes, 26)
            offset = 26 - 12
            macd_line = [a - b for a, b in zip(ema12[offset:], ema26)]
            if len(macd_line) < 10:
                return False
            signal_line = BB4HBandAnalyzer._calc_ema(macd_line, 9)
            if not signal_line:
                return False
            # 히스토그램 = macd - signal!
            hist = [m - s for m, s in zip(macd_line[-len(signal_line):], signal_line)]
            if len(hist) < LOOKBACK:
                return False
            # 최고점 (이전 봉이 최근 LOOKBACK 최대)?
            # + 지금 봉 = 이전 봉보다 낮음 (꺾임!)!
            return hist[-2] >= max(hist[-LOOKBACK:]) and hist[-1] < hist[-2]
        except Exception:
            return False


def run_pump_top_detector() -> dict:
    """매 5분 실행 = 7중 정점 감지!"""
    db = SessionLocal()
    detected_symbols: list[dict] = []
    scanned = 0
    try:
        # 1. mainnet 계정!
        account = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if not account:
            return {"error": "mainnet 계정 없음!", "detected": 0}

        # 2. API Ban 체크!
        from app.core.api_backoff import is_account_banned
        if is_account_banned(account.id):
            logger.info("[pump_top_v219] API Ban 중 = skip!")
            return {"error": "API Ban 중!", "detected": 0}

        # 3. BinanceClient!
        from app.integrations.binance.client import BinanceClient
        from app.core.crypto import decrypt_text
        bc = BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=False,
        )

        # 4. 상위 심볼 (거래대금!)
        tickers = bc.get_24hr_ticker()
        if not isinstance(tickers, list):
            return {"error": "ticker 실패!", "detected": 0}

        # USDT + 거래대금 sort!
        usdt = [t for t in tickers if str(t.get("symbol", "")).endswith("USDT")]
        try:
            usdt.sort(key=lambda x: float(x.get("quoteVolume", 0) or 0), reverse=True)
        except Exception:
            pass
        # 24h 급등만 pre-filter!
        candidates = [
            t for t in usdt[:MAX_SYMBOLS * 2]
            if float(t.get("priceChangePercent", 0) or 0) >= MIN_24H_CHANGE
        ][:MAX_SYMBOLS]

        if not candidates:
            logger.info("[pump_top_v219] 급등 심볼 (>=+%.0f%%) 없음!", MIN_24H_CHANGE)
            return {"detected": 0, "scanned": 0}

        # 5. 활성 심볼 skip!
        active_syms = set()
        try:
            active = db.execute(
                select(StrategyInstance).where(StrategyInstance.status.in_(list(ACTIVE_LIKE)))
            ).scalars().all()
            active_syms = {r.symbol for r in active}
        except Exception:
            pass

        # 6. Redis!
        from app.core.redis_client import get_redis_client
        r = get_redis_client()

        # 7. 심볼별 7중 확인!
        for t in candidates:
            symbol = str(t.get("symbol", ""))
            if not symbol or symbol in active_syms:
                continue
            try:
                kl = bc.get_klines(symbol=symbol, interval="4h", limit=120)
                if not isinstance(kl, list) or len(kl) < 60:
                    continue
                scanned += 1

                result = PumpTopDetector.check_7_signals(kl, t)
                if not result.get("detected"):
                    continue
                if result.get("confidence", 0) < MIN_CONFIDENCE:
                    continue

                # 알람 저장!
                alert_key = f"pump_top:alert:{symbol}"
                alert_data = {
                    "symbol": symbol,
                    "side": "SHORT",
                    "confidence": result["confidence"],
                    "signals": result["signals"],
                    "close": result["close"],
                    "rsi": result["rsi"],
                    "cci_last": result["cci_last"],
                    "change_24h": result["change_24h"],
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                    "source": "sajangnim_top_v219",
                }
                r.setex(alert_key, ALERT_TTL_SEC, json.dumps(alert_data))
                detected_symbols.append({
                    "symbol": symbol,
                    "confidence": result["confidence"],
                    "change_24h": result["change_24h"],
                })

                logger.warning(
                    "[pump_top_v219] 🎯 정점 감지! %s SHORT (conf=%.2f, 24h=+%.1f%%)",
                    symbol, result["confidence"], result["change_24h"],
                )

                # 텔레그램 알림! (fix: NotificationService 사용!)
                try:
                    from app.services.notification_service import NotificationService
                    _db_n = SessionLocal()
                    _ns = NotificationService(_db_n)
                    _body = (
                        f"🎯 사장님 정점 감지! (v219)\n"
                        f"심볼: {symbol} SHORT\n"
                        f"신뢰도: {result['confidence']*100:.0f}%\n"
                        f"24h: +{result['change_24h']:.1f}%\n"
                        f"RSI: {result['rsi']:.1f} / CCI: {result['cci_last']:.0f}\n"
                        f"7중 확인 통과! 자동 SHORT 진입 대기!"
                    )
                    _ns.send_system_alert(
                        title=f"🎯 [v219 정점] {symbol} SHORT ({result['confidence']*100:.0f}%)",
                        body=_body,
                    )
                    try:
                        _db_n.close()
                    except Exception:
                        pass
                except Exception as _te:
                    logger.warning("[pump_top_v219] telegram 실패: %s", _te)

            except Exception as e:
                logger.warning("[pump_top_v219] %s 스캔 실패: %s", symbol, e)
                continue

        logger.info(
            "[pump_top_v219] 완료: scanned=%d detected=%d",
            scanned, len(detected_symbols),
        )
        return {
            "scanned": scanned,
            "detected": len(detected_symbols),
            "symbols": detected_symbols,
        }
    except Exception as e:
        logger.exception("[pump_top_v219] 실행 실패: %s", e)
        return {"error": str(e), "detected": 0}
    finally:
        db.close()
