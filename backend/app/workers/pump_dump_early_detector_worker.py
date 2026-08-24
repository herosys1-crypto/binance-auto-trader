from __future__ import annotations
import json, logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.exchange_account import ExchangeAccount

logger = logging.getLogger(__name__)

SPEC_VERSION = "pump_dump_early_detector_v2_fix62_fix65_2026-08-25"
INTERVAL_SEC = 300  # 5분
MAX_SYMBOLS = 50
MIN_24H_CHANGE = 15.0  # 급등 심볼만!
MIN_PASSED = 5  # 5/7 지표 통과!
ALERT_TTL_SEC = 1800  # 30분
MIN_CONFIDENCE = 0.85

# 지표 임계값 (사장님 사상!)
RSI_DUMP_THRESHOLD = 50.0  # RSI(6) < 50 = 급락!
CCI_DUMP_THRESHOLD = -100.0  # CCI < -100!
OBV_DECLINE_MIN_PCT = 2.0  # OBV 2%+ 감소 = 하락 시작!


def _check_15m_dump_signals(bc, symbol):
    """15m 지표 5중 감지 (사장님 verbatim = 6중 통과 = SHORT!)"""
    try:
        # 15m klines
        klines = bc.get_klines(symbol=symbol, interval="15m", limit=60)
        if not klines or len(klines) < 30:
            return None, "insufficient_klines"

        # ChartAnalyzer로 지표 계산
        from app.services.chart_analyzer import ChartAnalyzer
        result = ChartAnalyzer.analyze_timeframe(bc, symbol, "15m")
        if not result:
            return None, "no_analysis"

        # 6중 지표
        signals = {}

        # 1. BB 상단 밀림 or MB 하회
        bb_up = result.get("bb_up")
        bb_mb = result.get("bb_mb")
        close_now = result.get("close_now")
        signals["bb_dump"] = bool(close_now and bb_mb and close_now < bb_mb)

        # 2. RSI(6) 급락
        rsi6 = result.get("rsi_now")
        signals["rsi_dump"] = bool(rsi6 is not None and rsi6 < RSI_DUMP_THRESHOLD)

        # 3. MACD Hist 음전환
        macd_hist = result.get("macd_hist_now")
        signals["macd_dump"] = bool(macd_hist is not None and macd_hist < 0)

        # 4. CCI 극단
        cci = result.get("cci_now")
        signals["cci_dump"] = bool(cci is not None and cci < CCI_DUMP_THRESHOLD)

        # 5. OBV 감소 시작 (2봉 이상!)
        obv_slope = result.get("obv_slope")
        signals["obv_dump"] = bool(obv_slope is not None and obv_slope < 0)

        # 6. 볼륨 감소
        volumes = [float(k[5]) for k in klines[-6:]]
        recent = sum(volumes[-3:]) / 3
        prior = sum(volumes[:3]) / 3
        signals["vol_dump"] = bool(recent < prior * 0.7)

        passed = sum(1 for v in signals.values() if v)

        return signals, passed
    except Exception as e:
        logger.warning("[Fix62/signals] %s: %s", symbol, e)
        return None, "error"


def _check_multi_tf_obv_consistency(bc, symbol):
    """1h + 4h OBV 방향 확인 (사장님 사상 = 혼란 skip!)
    반환: ('consistent_down', 'consistent_up', 'mixed')
    """
    try:
        from app.services.chart_analyzer import ChartAnalyzer
        r1h = ChartAnalyzer.analyze_timeframe(bc, symbol, "1h")
        r4h = ChartAnalyzer.analyze_timeframe(bc, symbol, "4h")

        obv_1h = r1h.get("obv_slope") if r1h else None
        obv_4h = r4h.get("obv_slope") if r4h else None

        if obv_1h is None or obv_4h is None:
            return "unknown"

        if obv_1h < 0 and obv_4h < 0:
            return "consistent_down"
        if obv_1h > 0 and obv_4h > 0:
            return "consistent_up"
        return "mixed"
    except Exception:
        return "unknown"


def _save_alert_redis(r, symbol, signals, passed, confidence, chg_24h):
    """Redis 알람 = auto_short_at_top이 처리!

    ⚠️ CRITICAL fix (Fix 67 발견 silent bug!): auto_short_at_top ALERT_PATTERN = "pump_top:alert:*" 만 스캔!
    → 옛 "sajangnim:top_short:{symbol}" = 진입 0건 (silent bug!)
    → 신 "pump_top:alert:{symbol}:SHORT" = pump_top_detector 동일 패턴!
    """
    try:
        alert_key = f"pump_top:alert:{symbol}:SHORT"  # auto_short_at_top ALERT_PATTERN 일치!
        alert_data = {
            "symbol": symbol,
            "side": "SHORT",
            "confidence": confidence,
            "chg_24h": chg_24h,
            "signals": signals,
            "passed": passed,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "source": "pump_dump_early",
            "spec_version": SPEC_VERSION,
        }
        r.setex(alert_key, 1800, json.dumps(alert_data, default=str))
        return True
    except Exception as e:
        logger.warning("[Fix62/alert] %s: %s", symbol, e)
        return False


def run_pump_dump_early_detector() -> dict:
    """Fix 62: 급등 후 하락 초기 감지 (5분 주기!)"""
    from app.core.redis_client import get_redis_client
    from app.integrations.binance.client import BinanceClient
    from app.core.crypto import decrypt_text
    from app.core.api_backoff import is_account_banned
    from app.services.notification_service import NotificationService

    db: Session = SessionLocal()
    try:
        acc = db.execute(
            select(ExchangeAccount)
            .where(ExchangeAccount.is_testnet == False)
            .where(ExchangeAccount.is_active == True)
            .limit(1)
        ).scalar_one_or_none()
        if not acc:
            return {"error": "no mainnet account", "detected": 0}

        if is_account_banned(acc.id):
            return {"error": "account banned", "detected": 0}

        bc = BinanceClient(
            api_key=decrypt_text(acc.api_key_enc),
            api_secret=decrypt_text(acc.api_secret_enc),
        )

        r = get_redis_client()

        # 24h ticker
        tickers = bc.get_24hr_ticker()
        if not isinstance(tickers, list):
            return {"error": "ticker failed", "detected": 0}

        # 급등 심볼만!
        candidates = []
        for t in tickers:
            sym = str(t.get("symbol", ""))
            if not sym.endswith("USDT"):
                continue
            try:
                chg = float(t.get("priceChangePercent", 0) or 0)
                if chg >= MIN_24H_CHANGE:
                    candidates.append((sym, chg, t))
            except Exception:
                continue

        # 급등 순 정렬
        candidates.sort(key=lambda x: x[1], reverse=True)
        candidates = candidates[:MAX_SYMBOLS]

        detected = 0
        skipped_mixed = 0

        for symbol, chg, _t in candidates:
            try:
                # 1. 15m 지표 확인
                signals_result = _check_15m_dump_signals(bc, symbol)
                if signals_result is None:
                    continue
                signals, passed = signals_result
                if not isinstance(passed, int):
                    continue
                if passed < MIN_PASSED:
                    continue

                # 2. 다중 시간대 OBV (사장님 사상!)
                obv_direction = _check_multi_tf_obv_consistency(bc, symbol)
                if obv_direction == "consistent_up":
                    logger.info("[Fix62/skip] %s: 1h+4h OBV 상승 = SHORT skip", symbol)
                    continue
                if obv_direction == "mixed":
                    logger.info("[Fix62/skip] %s: OBV 혼란 = 기다리기 (사장님 사상!)", symbol)
                    skipped_mixed += 1
                    continue
                # consistent_down = 강력! or unknown = 통과!

                # Fix 65: OBV 절대값 검증 (사장님 사상!)
                try:
                    from app.services.obv_gate import check_obv_gate
                    obv_pass, obv_reason = check_obv_gate(bc, symbol, "SHORT")
                    if not obv_pass:
                        logger.info("[Fix62+Fix65] %s skip: %s", symbol, obv_reason)
                        continue
                except Exception as _obv_exc:
                    logger.warning("[Fix62+Fix65] %s obv_gate error: %s", symbol, _obv_exc)

                # Fix 66 P1 + P2!
                try:
                    from app.services.bidirectional_blocklist import is_bidirectional_blocked
                    from app.services.pump_dump_regime import is_regime_blocked_for_short
                    from app.core.database import SessionLocal as _SL
                    db_bl = _SL()
                    try:
                        blocked, block_reason = is_bidirectional_blocked(db_bl, symbol)
                        if blocked:
                            logger.info("[Fix62+Fix66] %s skip: %s", symbol, block_reason)
                            continue
                    finally:
                        db_bl.close()
                    regime_blocked, regime_reason = is_regime_blocked_for_short(bc, symbol)
                    if regime_blocked:
                        logger.info("[Fix62+Fix66] %s skip: %s", symbol, regime_reason)
                        continue
                except Exception as _f66_exc:
                    logger.warning("[Fix62+Fix66] error: %s", _f66_exc)

                # 3. confidence 계산
                confidence = 0.85 + 0.02 * (passed - MIN_PASSED)
                confidence = min(confidence, 0.94)
                if obv_direction == "consistent_down":
                    confidence = min(confidence + 0.02, 0.94)

                # 4. Redis 알람 저장
                if _save_alert_redis(r, symbol, signals, passed, confidence, chg):
                    detected += 1
                    logger.warning(
                        "[Fix62/detected] %s: chg=%.2f%% passed=%d/6 conf=%.2f obv_dir=%s",
                        symbol, chg, passed, confidence, obv_direction,
                    )
                    # 텔레그램 알림
                    db_n = SessionLocal()
                    try:
                        NotificationService(db_n).send_system_alert(
                            title=f"📉 Fix 62 급락 초기 감지: {symbol}",
                            body=f"24h +{chg:.1f}% / 6중 {passed}/6 / conf {confidence:.2f} / 1h+4h OBV {obv_direction}",
                            severity="INFO",
                        )
                    finally:
                        db_n.close()
            except Exception as e:
                logger.warning("[Fix62] %s error: %s", symbol, e)
                continue

        logger.warning(
            "[Fix62] 완료: scanned=%d detected=%d skipped_mixed=%d spec=%s",
            len(candidates), detected, skipped_mixed, SPEC_VERSION,
        )
        return {
            "scanned": len(candidates),
            "detected": detected,
            "skipped_mixed": skipped_mixed,
            "spec_version": SPEC_VERSION,
        }
    finally:
        db.close()
