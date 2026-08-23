"""Fix 47 (2026-08-24 사장님!): LONG 저점/급등 초기 감지 (v219 대응!)"""
from __future__ import annotations
import json, logging
from datetime import datetime, timezone
from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_LIKE
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance

logger = logging.getLogger(__name__)
SPEC_VERSION = "long_bottom_detector_v1_2026-08-24"
LOOKBACK = 20
MAX_SYMBOLS = 40
ALERT_TTL_SEC = 1800
MIN_CONFIDENCE = 0.85


def _redis():
    try:
        from app.core.redis_client import get_redis_client
        return get_redis_client()
    except Exception:
        return None


def check_bottom_signals(bc, symbol, ticker_24h):
    """7중 저점 감지!"""
    try:
        kl_4h = bc.get_klines(symbol=symbol, interval="4h", limit=50)
        if not kl_4h or len(kl_4h) < 30:
            return None
        
        from app.services.bb_4h_band_analyzer import BB4HBandAnalyzer
        from app.services.chart_analyzer import ChartAnalyzer
        
        closes = [float(k[4]) for k in kl_4h]
        volumes = [float(k[5]) for k in kl_4h]
        lows = [float(k[3]) for k in kl_4h]
        
        # 1. BB 하단 근처 or 이탈 후 회복
        mid, up, lo = BB4HBandAnalyzer.bollinger(closes)
        c1 = False
        if lo and lo[-1]:
            lower = float(lo[-1])
            c1 = closes[-1] <= lower * 1.02  # 하단 근접!
        
        # 2. OBV 저점 후 상승 반전! ⭐
        obv = list(ChartAnalyzer.compute_obv(kl_4h) or [])
        c2 = False
        if len(obv) >= 5:
            recent_min = min(float(o) for o in obv[-5:])
            c2 = float(obv[-1]) > recent_min and float(obv[-1]) > float(obv[-2])
        
        # 3. MACD 상승 반전
        try:
            analysis = ChartAnalyzer.analyze_timeframe(bc, symbol=symbol, interval="4h", limit=50)
            hist = analysis.get('macd_hist', [])
            c3 = len(hist) >= 3 and hist[-1] > hist[-2]
        except Exception:
            c3 = False
        
        # 4. RSI 과매도 회복
        rsi_now = BB4HBandAnalyzer._calc_rsi(closes)
        rsi_prev = BB4HBandAnalyzer._calc_rsi(closes[:-1])
        c4 = (rsi_now is not None and rsi_prev is not None 
              and rsi_prev <= 35 and rsi_now > rsi_prev)
        
        # 5. CCI 과매도 회복
        cci = list(ChartAnalyzer.compute_cci(kl_4h) or [])
        c5 = (len(cci) >= 2 and cci[-2] <= -100 and cci[-1] > cci[-2])
        
        # 6. all_bottom
        c6 = c2 and c3 and c4 and c5
        
        # 7. 24h 변동 -10% ~ +10%
        chg24 = float(ticker_24h.get("priceChangePercent", 0) or 0)
        c7 = -10 <= chg24 <= 10
        
        passed = sum([c1, c2, c3, c4, c5, c6, c7])
        confidence = 0.85 + 0.02 * (passed - 5) if passed >= 5 else 0.0
        
        return {
            "detected": passed >= 6,  # 7개 중 6개 이상!
            "passed": passed,
            "confidence": round(confidence, 4),
            "close": closes[-1],
            "change_24h": chg24,
            "obv_bottom": c2,
            "signals": [c1, c2, c3, c4, c5, c6, c7],
        }
    except Exception as e:
        logger.warning(f"[long_bottom] {symbol}: {e}")
        return None


def run_long_bottom_detector():
    """scheduler_runner 진입점 (매 5분!)"""
    result = {"scanned": 0, "detected": 0, "symbols": [], "spec": SPEC_VERSION}
    db = SessionLocal()
    try:
        acc = db.query(ExchangeAccount).filter(ExchangeAccount.is_testnet == False).first()
        if acc is None: return result
        try:
            from app.core.api_backoff import is_account_banned
            if is_account_banned(acc.id): return result
        except Exception: pass
        try:
            from app.core.crypto import decrypt_text
            from app.integrations.binance.client import BinanceClient
            bc = BinanceClient(api_key=decrypt_text(acc.api_key_enc),
                              api_secret=decrypt_text(acc.api_secret_enc))
        except Exception as e:
            logger.error(f"[long_bottom] BC: {e}")
            return result
        
        # 활성 심볼 skip
        active_syms = set()
        try:
            active = db.query(StrategyInstance).filter(
                StrategyInstance.status.in_(list(ACTIVE_LIKE))
            ).all()
            active_syms = {s.symbol for s in active}
        except Exception: pass
        
        # 24h ticker
        try:
            tickers = bc.get_24hr_ticker()
            usdt = [t for t in (tickers or []) if str(t.get("symbol", "")).endswith("USDT")]
            usdt.sort(key=lambda t: float(t.get("quoteVolume", 0) or 0), reverse=True)
            candidates = usdt[:MAX_SYMBOLS]
        except Exception as e:
            logger.error(f"[long_bottom] ticker: {e}")
            return result
        
        r = _redis()
        for t in candidates:
            symbol = str(t.get("symbol", ""))
            if not symbol or symbol in active_syms: continue
            try:
                result["scanned"] += 1
                sig = check_bottom_signals(bc, symbol, t)
                if not sig or not sig.get("detected"): continue
                if sig["confidence"] < MIN_CONFIDENCE: continue
                
                # Redis alert 저장!
                if r:
                    try:
                        r.setex(f"long_bottom:alert:{symbol}:LONG", ALERT_TTL_SEC,
                                json.dumps({"symbol": symbol, "side": "LONG",
                                          "confidence": sig["confidence"],
                                          "change_24h": sig["change_24h"],
                                          "close": sig["close"],
                                          "detected_at": datetime.now(timezone.utc).isoformat()}))
                    except Exception: pass
                
                result["detected"] += 1
                result["symbols"].append(symbol)
                logger.warning(f"[long_bottom] ✅ DETECTED {symbol} conf={sig['confidence']} chg24={sig['change_24h']}")
            except Exception as e:
                logger.warning(f"[long_bottom] {symbol}: {e}")
        
        logger.info(f"[long_bottom] scanned={result['scanned']} detected={result['detected']}")
        return result
    finally:
        db.close()
