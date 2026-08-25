"""Fix 29 v228 (2026-08-23): 저항 반전 SHORT 2단계 자동 진입 워커!

사장님 verbatim:
"전고점 13354가 최대 저항 = 돌파 후 하락 시점에 2단계 진입"
"0.013354 아니면 돌파전에 하락하는 시점에 2단계 진입"
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from statistics import mean

from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_LIKE
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_suggestion import StrategySuggestion

logger = logging.getLogger(__name__)

SPEC_VERSION = "resistance_reversal_v2_fix72_2026-08-25"
RESISTANCE_PROXIMITY_RATIO = Decimal("0.01")
RESISTANCE_AUTO_LOOKBACK_KLINES = 672
RESISTANCE_AUTO_TTL_HOURS = 24
MARTINGALE_STAGE2_USDT = Decimal("600")
REDIS_KEY_LOCK = "resistance_reversal:lock:{sid}"
REDIS_KEY_TRIGGERED = "resistance_reversal:triggered:{sid}"
RSI_DROP_MIN = 3.0
UPPER_WICK_RATIO = 1.5
MAX_STRATEGIES_PER_CYCLE = 50


def _calc_rsi(closes, period=6):
    if not closes or len(closes) < period + 1: return None
    try:
        gains = losses = 0.0
        for i in range(1, period + 1):
            d = float(closes[i]) - float(closes[i - 1])
            if d > 0: gains += d
            else: losses += -d
        avg_g = gains / period
        avg_l = losses / period
        for i in range(period + 1, len(closes)):
            d = float(closes[i]) - float(closes[i - 1])
            g = d if d > 0 else 0.0
            l = -d if d < 0 else 0.0
            avg_g = (avg_g * (period - 1) + g) / period
            avg_l = (avg_l * (period - 1) + l) / period
        if avg_l == 0: return 100.0
        return round(100 - (100 / (1 + avg_g / avg_l)), 4)
    except Exception:
        return None


def _calc_ema(vals, period):
    if not vals or len(vals) < period: return []
    k = 2 / (period + 1)
    ema = [sum(float(v) for v in vals[:period]) / period]
    for i in range(period, len(vals)):
        ema.append(float(vals[i]) * k + ema[-1] * (1 - k))
    return ema


def _calc_macd_hist(closes):
    if not closes or len(closes) < 35: return []
    try:
        e12 = _calc_ema(closes, 12)
        e26 = _calc_ema(closes, 26)
        if not e12 or not e26: return []
        off = 26 - 12
        macd = [e12[i + off] - e26[i] for i in range(len(e26))]
        sig = _calc_ema(macd, 9)
        if not sig: return []
        off2 = len(macd) - len(sig)
        return [macd[i + off2] - sig[i] for i in range(len(sig))]
    except Exception:
        return []


def _calc_cci(klines, period=9):
    if not klines or len(klines) < period: return []
    try:
        tp = [(float(k[2]) + float(k[3]) + float(k[4])) / 3 for k in klines]
        out = []
        for i in range(len(tp)):
            if i < period - 1:
                out.append(0.0); continue
            w = tp[i - period + 1:i + 1]
            sma = sum(w) / period
            md = sum(abs(v - sma) for v in w) / period
            out.append(0.0 if md == 0 else (tp[i] - sma) / (0.015 * md))
        return out
    except Exception:
        return []


def _redis():
    try:
        from app.core.redis_client import get_redis_client
        return get_redis_client()
    except Exception:
        return None


def _acquire_lock(sid):
    r = _redis()
    if r is None: return True
    try:
        return bool(r.set(REDIS_KEY_LOCK.format(sid=sid), b"1", nx=True, ex=30))
    except Exception:
        return True


def _release_lock(sid):
    r = _redis()
    if r is None: return
    try: r.delete(REDIS_KEY_LOCK.format(sid=sid))
    except Exception: pass


def _detect_auto_resistance(bc, symbol):
    try:
        kl = bc.get_klines(symbol=symbol, interval="15m", limit=RESISTANCE_AUTO_LOOKBACK_KLINES)
        if not kl: return None
        return Decimal(str(max(float(k[2]) for k in kl)))
    except Exception as e:
        logger.warning(f"[Fix29] auto_resistance failed {symbol}: {e}")
        return None


def _resolve_resistance(db, bc, s):
    now = datetime.now(timezone.utc)
    if s.resistance_source == "user" and s.resistance_price:
        return (Decimal(str(s.resistance_price)), "user")
    if (s.resistance_price and s.resistance_detected_at
        and (now - s.resistance_detected_at) < timedelta(hours=RESISTANCE_AUTO_TTL_HOURS)):
        return (Decimal(str(s.resistance_price)), "auto_7d_15m")
    d = _detect_auto_resistance(bc, s.symbol)
    if d is None: return None
    s.resistance_price = d
    s.resistance_source = "auto_7d_15m"
    s.resistance_detected_at = now
    db.commit()
    return (d, "auto_7d_15m")


def _is_approaching(current, resistance):
    try:
        cur = Decimal(str(current)); res = Decimal(str(resistance))
        return abs(res - cur) / res <= RESISTANCE_PROXIMITY_RATIO
    except Exception:
        return False


def _detect_reversal(bc, symbol):
    try:
        kl = bc.get_klines(symbol=symbol, interval="15m", limit=50)
        if not kl or len(kl) < 30:
            return (False, {"reason": "insufficient"})
        opens = [float(k[1]) for k in kl]
        highs = [float(k[2]) for k in kl]
        closes = [float(k[4]) for k in kl]
        volumes = [float(k[5]) for k in kl]
        o, h, c = opens[-2], highs[-2], closes[-2]
        bearish = c < o
        body = abs(o - c)
        wick = h - max(o, c)
        wick_ok = bearish and body > 0 and wick >= body * UPPER_WICK_RATIO
        rsi_now = _calc_rsi(closes, 6)
        rsi_prev = _calc_rsi(closes[:-1], 6)
        rsi_ok = (rsi_now is not None and rsi_prev is not None
                  and rsi_now < rsi_prev - RSI_DROP_MIN)
        hist = _calc_macd_hist(closes)
        macd_ok = len(hist) >= 2 and hist[-1] < hist[-2]
        cci = _calc_cci(kl, 9)
        cci_ok = len(cci) >= 2 and cci[-1] < cci[-2]
        vol_last = volumes[-1]
        vol_avg = mean(volumes[-6:-1]) if len(volumes) >= 6 else vol_last
        vol_ok = vol_last < vol_avg
        all_ok = all([wick_ok, rsi_ok, macd_ok, cci_ok, vol_ok])
        snap = {"wick": wick_ok, "rsi": rsi_ok, "macd": macd_ok, "cci": cci_ok, "vol": vol_ok,
                "rsi_now": rsi_now, "rsi_prev": rsi_prev, "spec": SPEC_VERSION}
        return (all_ok, snap)
    except Exception as e:
        logger.warning(f"[Fix29] reversal failed {symbol}: {e}")
        return (False, {"err": str(e)})


def _mark_triggered(db, sid):
    s = db.get(StrategyInstance, sid)
    if s:
        s.resistance_reversal_triggered_at = datetime.now(timezone.utc)
        db.commit()
    r = _redis()
    if r is not None:
        try: r.setex(REDIS_KEY_TRIGGERED.format(sid=sid), 24*3600, b"1")
        except Exception: pass


def _notify(title, body):
    try:
        from app.services.notification_service import NotificationService
        db2 = SessionLocal()
        try: NotificationService(db2).send_system_alert(title=title, body=body)
        finally: db2.close()
    except Exception as e:
        logger.warning(f"[Fix29] notify: {e}")


def _get_current_price(bc, symbol):
    r = _redis()
    if r is not None:
        try:
            v = r.get(f"mark_price:{symbol}")
            if v: return Decimal(str(v.decode() if isinstance(v, bytes) else v))
        except Exception: pass
    try:
        kl = bc.get_klines(symbol=symbol, interval="1m", limit=1)
        if kl: return Decimal(str(kl[-1][4]))
    except Exception: pass
    return None


def _save_entry_snapshot_suggestion(db, s, snap, resistance, source, cur):
    """Fix 72 (2026-08-25): stage-2 마틴게일 트리거 지표 학습 데이터 확보!

    사장님 신 사상: resistance_reversal 발동 시점의 저항선/RSI/MACD/CCI/OBV/volume/wick
    상태를 StrategySuggestion.strategy_config.entry_snapshot에 박제 →
    pattern_learning_worker가 이후 성공/실패 분석에 활용.

    fail-open: INSERT 실패 = 진입 자체는 성공! (학습 데이터 유실 < 마틴게일 실패)
    """
    try:
        # break_type = 돌파 후 하락 (fake_breakdown) vs 돌파 전 하락 (rejection)
        break_type = "unknown"
        try:
            if cur is not None and resistance is not None:
                break_type = "fake_breakdown" if Decimal(str(cur)) > Decimal(str(resistance)) else "rejection"
        except Exception:
            pass

        _kst_hour = (datetime.now(timezone.utc).hour + 9) % 24
        entry_snapshot = {
            "source": "RESISTANCE_REVERSAL",
            "spec_version": SPEC_VERSION,
            "resistance_price": str(resistance) if resistance is not None else None,
            "resistance_source": source,
            "current_price": str(cur) if cur is not None else None,
            "break_type": break_type,
            "wick_ok": snap.get("wick") if isinstance(snap, dict) else None,
            "rsi_ok": snap.get("rsi") if isinstance(snap, dict) else None,
            "macd_ok": snap.get("macd") if isinstance(snap, dict) else None,
            "cci_ok": snap.get("cci") if isinstance(snap, dict) else None,
            "vol_ok": snap.get("vol") if isinstance(snap, dict) else None,
            "rsi_now": snap.get("rsi_now") if isinstance(snap, dict) else None,
            "rsi_prev": snap.get("rsi_prev") if isinstance(snap, dict) else None,
            "regime": "RESISTANCE_REVERSAL_SHORT",
            "kst_hour": _kst_hour,
            "parent_strategy_id": s.id,
            "stage_num": 2,
            "entered_at": datetime.now(timezone.utc).isoformat(),
        }
        sugg = StrategySuggestion(
            symbol=s.symbol,
            side="SHORT",
            suggestion_type="resistance_reversal_short",
            strategy_config={
                "capitals": [float(MARTINGALE_STAGE2_USDT)],
                "symbol": s.symbol,
                "side": "SHORT",
                "resistance_reversal": True,
                "stage_num": 2,
                "parent_strategy_id": s.id,
                "resistance_price": str(resistance) if resistance is not None else None,
                "resistance_source": source,
                "break_type": break_type,
                "entry_snapshot": entry_snapshot,
            },
            reason=(
                f"🎯 저항 반전 SHORT 2단계 (Fix 29 v228)! "
                f"저항={resistance} ({source}) break={break_type} "
                f"5지표 통과 (wick/rsi/macd/cci/vol)"
            ),
            status="EXECUTED",
            execution_mode="AUTO",
            executed_at=datetime.now(timezone.utc),
            executed_strategy_id=s.id,
            outcome_status="PENDING",
        )
        db.add(sugg)
        db.commit()
        logger.info("[Fix29+72] StrategySuggestion 저장 #%s stage=2 break=%s", s.id, break_type)
    except Exception as e:
        logger.warning("[Fix29+72] snapshot save 실패 #%s: %s (진입은 성공 유지)", s.id, e)
        try:
            db.rollback()
        except Exception:
            pass


def _enter_stage2(db, s, snap, resistance, source, cur=None):
    try:
        from app.models.strategy_template import StrategyTemplate
        tpl = db.get(StrategyTemplate, s.strategy_template_id)
        if tpl and hasattr(tpl, 'stages') and tpl.stages and len(tpl.stages) >= 2:
            tpl.stages[1].capital_usdt = MARTINGALE_STAGE2_USDT
            tpl.stages[1].trigger_price = None
            db.commit()
        from app.services.execution_service import ExecutionService
        svc = ExecutionService(db)
        order = None
        for fn_name in ('enter_stage_at_market', 'start_stage', 'add_stage', 'trigger_stage'):
            fn = getattr(svc, fn_name, None)
            if fn is None: continue
            try:
                order = fn(strategy_id=s.id, stage_no=2)
                if order: break
            except TypeError:
                try:
                    order = fn(s.id, 2)
                    if order: break
                except Exception: continue
            except Exception as e:
                logger.warning(f"[Fix29] {fn_name}: {e}"); continue
        if order is None:
            logger.error(f"[Fix29] Stage2 FAILED #{s.id}")
            return False
        # Fix 52 = 사장님 -5% 짧은 손절 방침 (모든 진입 워커 통일!)
        try:
            s.force_sl_enabled_override = True
            s.force_sl_roi_override = Decimal("5")
            db.commit()
            logger.info("[Fix29+52] 🛡️ %s SL -5%% 적용 (strategy_id=%s)", s.symbol, s.id)
        except Exception as _sl_exc:
            logger.warning("[Fix29+52] ⚠️ %s SL override 실패: %s (진입 유지)", s.symbol, _sl_exc)
            db.rollback()
        _mark_triggered(db, s.id)
        # Fix 72 (2026-08-25): 학습용 StrategySuggestion INSERT (fail-open!)
        _save_entry_snapshot_suggestion(db, s, snap, resistance, source, cur)
        _notify(f"[저항 반전 2단계 SHORT 진입] {s.symbol}",
                f"{s.symbol} SHORT #{s.id}\n자본: {MARTINGALE_STAGE2_USDT} USDT\n저항: {resistance} ({source})")
        logger.warning(f"[Fix29] ENTERED #{s.id} {s.symbol}")
        return True
    except Exception as e:
        logger.error(f"[Fix29] enter_stage2 #{s.id}: {e}", exc_info=True)
        _release_lock(s.id)
        return False


def _query_candidates(db):
    return (db.query(StrategyInstance)
            .filter(StrategyInstance.side == 'SHORT',
                    StrategyInstance.current_stage == 1,
                    StrategyInstance.resistance_reversal_triggered_at.is_(None),
                    StrategyInstance.status.in_(list(ACTIVE_LIKE)))
            .limit(MAX_STRATEGIES_PER_CYCLE).all())


def run_resistance_reversal_once():
    result = {"scanned": 0, "approached": 0, "reversed": 0, "entered": 0,
              "errors": 0, "spec": SPEC_VERSION}
    db = SessionLocal()
    try:
        acc = db.query(ExchangeAccount).filter(ExchangeAccount.is_testnet == False).first()
        if acc is None:
            logger.warning("[Fix29] no mainnet"); return result
        try:
            from app.core.api_backoff import is_account_banned
            if is_account_banned(acc.id):
                logger.info("[Fix29] banned"); return result
        except Exception: pass
        try:
            from app.core.crypto import decrypt_text
            from app.integrations.binance.client import BinanceClient
            bc = BinanceClient(api_key=decrypt_text(acc.api_key_enc),
                               api_secret=decrypt_text(acc.api_secret_enc))
        except Exception as e:
            logger.error(f"[Fix29] BC init: {e}"); return result
        cands = _query_candidates(db)
        result["scanned"] = len(cands)
        if not cands:
            logger.info("[Fix29] no candidates"); return result
        logger.info(f"[Fix29] scanned={len(cands)}")
        for s in cands:
            try:
                if not _acquire_lock(s.id): continue
                rr = _resolve_resistance(db, bc, s)
                if rr is None: _release_lock(s.id); continue
                resistance, source = rr
                cur = _get_current_price(bc, s.symbol)
                if cur is None: _release_lock(s.id); continue
                if not _is_approaching(cur, resistance):
                    _release_lock(s.id); continue
                result["approached"] += 1
                logger.info(f"[Fix29] APPROACH #{s.id} {s.symbol} cur={cur} res={resistance}")
                ok, snap = _detect_reversal(bc, s.symbol)
                if not ok:
                    logger.info(f"[Fix29] no reversal #{s.id}: {snap}")
                    _release_lock(s.id); continue
                result["reversed"] += 1
                _notify(f"[저항 반전 감지] {s.symbol} SHORT",
                        f"{s.symbol}\n저항: {resistance}\n현재: {cur}\n5지표: {snap}")
                if _enter_stage2(db, s, snap, resistance, source, cur=cur):
                    result["entered"] += 1
            except Exception as e:
                result["errors"] += 1
                logger.error(f"[Fix29] #{s.id}: {e}", exc_info=True)
                _release_lock(s.id)
        logger.warning(f"[Fix29] DONE: {result}")
        return result
    finally:
        db.close()
