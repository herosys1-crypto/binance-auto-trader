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

SPEC_VERSION = "pump_dump_early_detector_v3_fix72_2026-08-25"
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
    """15m 지표 5중 감지 (사장님 verbatim = 6중 통과 = SHORT!)

    Fix 72 (2026-08-25): raw_values 반환 추가 = entry_snapshot 학습 데이터 확보!
    반환: (signals_dict, passed_count, raw_values_dict) or (None, "error_str", None)
    """
    try:
        # 15m klines
        klines = bc.get_klines(symbol=symbol, interval="15m", limit=60)
        if not klines or len(klines) < 30:
            return None, "insufficient_klines", None

        # ChartAnalyzer로 지표 계산
        from app.services.chart_analyzer import ChartAnalyzer
        result = ChartAnalyzer.analyze_timeframe(bc, symbol, "15m")
        if not result:
            return None, "no_analysis", None

        # ═══════════════════════════════════════════════════════════════
        # 🚨 Fix 229 (2026-08-30): **키 이름이 전부 틀려 이 워커는 산출이 0 이었다.**
        #
        #   ChartAnalyzer.analyze_timeframe 이 실제로 주는 키는 12개다:
        #     closes / volumes / obv / rsi_now / rsi_prev / macd_hist /
        #     cci_now / cci_prev / bb_up_last / bb_mid_last / bb_lo_last / kl_count
        #
        #   그런데 옛 코드는 bb_up / bb_mb / bb_lo / close_now / macd_hist_now /
        #   obv_slope 를 읽었다 — **전부 없는 키**라 항상 None → 신호 4개가 영구 False.
        #   살아 있는 신호는 rsi / cci / vol **3개뿐인데 MIN_PASSED = 5** 였다.
        #   = 5분마다 API weight 를 쓰면서 **알람을 한 건도 낼 수 없었다.**
        #   (raw_values 로 학습 스냅샷에도 None 이 박혔다)
        # ═══════════════════════════════════════════════════════════════
        # 6중 지표
        signals = {}

        _closes = result.get("closes") or []
        _hist = result.get("macd_hist") or []

        # 1. BB 상단 밀림 or MB 하회
        bb_up = result.get("bb_up_last")
        bb_mb = result.get("bb_mid_last")
        bb_lo = result.get("bb_lo_last")
        close_now = float(_closes[-1]) if _closes else None
        signals["bb_dump"] = bool(close_now and bb_mb and close_now < bb_mb)

        # 2. RSI(6) 급락
        rsi6 = result.get("rsi_now")
        signals["rsi_dump"] = bool(rsi6 is not None and rsi6 < RSI_DUMP_THRESHOLD)

        # 3. MACD Hist 음전환
        macd_hist = float(_hist[-1]) if _hist else None
        signals["macd_dump"] = bool(macd_hist is not None and macd_hist < 0)

        # 4. CCI 극단
        cci = result.get("cci_now")
        signals["cci_dump"] = bool(cci is not None and cci < CCI_DUMP_THRESHOLD)

        # 5. OBV 감소 시작
        #   Fix 228 공통 함수(-1~+1). 워커마다 산식이 갈리면 단위가 또 섞인다.
        from app.services.obv_metrics import obv_direction_ratio
        obv_slope = obv_direction_ratio(result.get("obv"), result.get("volumes"))
        signals["obv_dump"] = bool(obv_slope is not None and obv_slope < 0)

        # 6. 볼륨 감소
        volumes = [float(k[5]) for k in klines[-6:]]
        recent = sum(volumes[-3:]) / 3
        prior = sum(volumes[:3]) / 3
        signals["vol_dump"] = bool(recent < prior * 0.7)

        passed = sum(1 for v in signals.values() if v)

        # Fix 72: raw indicator values (학습 entry_snapshot용!)
        raw_values = {
            "rsi": rsi6,
            "cci": cci,
            "macd_hist": macd_hist,
            "obv_slope": obv_slope,
            "bb_up": bb_up,
            "bb_mb": bb_mb,
            "bb_lo": bb_lo,
            "close_now": close_now,
            "volume_recent": recent,
            "volume_prior": prior,
        }

        return signals, passed, raw_values
    except Exception as e:
        logger.warning("[Fix62/signals] %s: %s", symbol, e)
        return None, "error", None


def _check_multi_tf_obv_consistency(bc, symbol):
    """1h + 4h OBV 방향 확인 (사장님 사상 = 혼란 skip!)
    반환: ('consistent_down', 'consistent_up', 'mixed')
    """
    try:
        from app.services.chart_analyzer import ChartAnalyzer
        r1h = ChartAnalyzer.analyze_timeframe(bc, symbol, "1h")
        r4h = ChartAnalyzer.analyze_timeframe(bc, symbol, "4h")

        # 🚨 Fix 229: 여기도 없는 키였다 — 항상 None → 항상 "unknown" 을 반환했다.
        #   즉 「1h+4h OBV 방향 일치 확인」이라는 이 함수 전체가 무의미했다.
        #   Fix 228 공통 함수로 -1~+1 방향을 실제로 계산한다.
        from app.services.obv_metrics import obv_direction_ratio
        obv_1h = obv_direction_ratio(r1h.get("obv"), r1h.get("volumes")) if r1h else None
        obv_4h = obv_direction_ratio(r4h.get("obv"), r4h.get("volumes")) if r4h else None

        if obv_1h is None or obv_4h is None:
            return "unknown"

        if obv_1h < 0 and obv_4h < 0:
            return "consistent_down"
        if obv_1h > 0 and obv_4h > 0:
            return "consistent_up"
        return "mixed"
    except Exception:
        return "unknown"


def _save_alert_redis(r, symbol, signals, passed, confidence, chg_24h, raw_values=None, obv_direction=None):
    """Redis 알람 = auto_short_at_top이 처리!

    ⚠️ CRITICAL fix (Fix 67 발견 silent bug!): auto_short_at_top ALERT_PATTERN = "pump_top:alert:*" 만 스캔!
    → 옛 "sajangnim:top_short:{symbol}" = 진입 0건 (silent bug!)
    → 신 "pump_top:alert:{symbol}:SHORT" = pump_top_detector 동일 패턴!

    Fix 72 (2026-08-25): entry_snapshot 저장 = 학습 데이터 완전 확보!
    - raw_values (rsi/cci/macd/obv/bb) → alert.entry_snapshot 딕셔너리
    - 하위 호환 = alert.rsi/cci_last top-level 유지 (auto_short_at_top 옛 fallback!)
    """
    try:
        alert_key = f"pump_top:alert:{symbol}:SHORT"  # auto_short_at_top ALERT_PATTERN 일치!
        rv = raw_values or {}
        # Fix 72: rich entry_snapshot (auto_short_at_top이 우선 사용!)
        entry_snapshot = {
            "rsi": rv.get("rsi"),
            "cci": rv.get("cci"),
            "macd_hist": rv.get("macd_hist"),
            "obv_slope": rv.get("obv_slope"),
            "obv_slope_pct": rv.get("obv_slope"),  # legacy 필드명 호환
            "bb_up": rv.get("bb_up"),
            "bb_mb": rv.get("bb_mb"),
            "bb_lo": rv.get("bb_lo"),
            "close_now": rv.get("close_now"),
            "volume_recent": rv.get("volume_recent"),
            "volume_prior": rv.get("volume_prior"),
            "regime": "DUMP_EARLY",
            "obv_direction_multi_tf": obv_direction,
            "signals_passed": signals,
            "signals_passed_count": passed,
            "confidence": confidence,
            "change_24h": chg_24h,
            "source": "pump_dump_early",
            "spec_version": SPEC_VERSION,
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }
        alert_data = {
            "symbol": symbol,
            "side": "SHORT",
            "confidence": confidence,
            "chg_24h": chg_24h,
            "change_24h": chg_24h,  # 하위 호환 (auto_short_at_top이 change_24h로 읽음!)
            "signals": signals,
            "passed": passed,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "source": "pump_dump_early",
            "spec_version": SPEC_VERSION,
            # Fix 72: 하위 호환 = auto_short_at_top의 옛 fallback 경로 유지!
            "rsi": rv.get("rsi"),
            "cci_last": rv.get("cci"),
            # Fix 72: rich snapshot (다운스트림 우선 소비!)
            "entry_snapshot": entry_snapshot,
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
                # 1. 15m 지표 확인 (Fix 72: raw_values 반환!)
                signals_result = _check_15m_dump_signals(bc, symbol)
                if signals_result is None:
                    continue
                # Fix 72: 3-tuple (signals, passed, raw_values)
                if not isinstance(signals_result, tuple) or len(signals_result) < 2:
                    continue
                if len(signals_result) == 3:
                    signals, passed, raw_values = signals_result
                else:
                    # 하위 호환 (2-tuple 반환)
                    signals, passed = signals_result
                    raw_values = None
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

                # 4. Redis 알람 저장 (Fix 72: raw_values + obv_direction 전달!)
                if _save_alert_redis(r, symbol, signals, passed, confidence, chg,
                                     raw_values=raw_values, obv_direction=obv_direction):
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
