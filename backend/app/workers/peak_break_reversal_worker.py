"""Fix 41 (2026-08-23 사장님 신 사상!): 전고점 돌파 후 반전 마틴게일!

사장님 verbatim:
"2단계 진입가를 15분차트 최고가에서 밀려서 내려오다가 다시 상승해서 전고점을 돌파하면 
 대기 모니터링하고 최고가에서 다시 밀려 내려오면 그때 2단계를 실행"
"확실하게 하락하는 차트와 보조지표여야 해"
"3단계도 그후 4단계 이상도 그렇게 해줘"

상태 머신:
  INITIAL → TRACKING_PEAK_A → LOW_FORMED → 
  BREAK_A_CONFIRMED → TRACKING_PEAK_B → REVERSAL_DETECTED → ENTERED

Spec: docs/PEAK_BREAK_REVERSAL_SPEC_v1.md
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from statistics import mean

from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_LIKE
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance

logger = logging.getLogger(__name__)

SPEC_VERSION = "peak_break_reversal_v1_2026-08-23"
KLINE_INTERVAL = "15m"
KLINE_LIMIT = 60
PULLBACK_PCT = Decimal("0.01")
STATE_TTL = 24 * 3600
RSI_DROP_MIN = 3.0
VOL_MULT = 1.2

STATES = ["INITIAL", "TRACKING_PEAK_A", "LOW_FORMED", "BREAK_A_CONFIRMED",
          "TRACKING_PEAK_B", "REVERSAL_DETECTED", "ENTERED"]


def _redis():
    try:
        from app.core.redis_client import get_redis_client
        return get_redis_client()
    except Exception: return None


def _get(sid, stage, key):
    r = _redis()
    if r is None: return None
    try:
        v = r.get(f"pbr:{key}:{sid}:{stage}")
        return v.decode() if isinstance(v, bytes) else v
    except Exception: return None


def _set(sid, stage, key, val):
    r = _redis()
    if r is None: return
    try: r.setex(f"pbr:{key}:{sid}:{stage}", STATE_TTL, str(val))
    except Exception: pass


def _clear(sid, stage):
    r = _redis()
    if r is None: return
    try:
        for k in ["state", "peak_A", "low", "peak_B", "last_high"]:
            r.delete(f"pbr:{k}:{sid}:{stage}")
    except Exception: pass


def _get_state(sid, stage): return _get(sid, stage, "state") or "INITIAL"
def _set_state(sid, stage, s): _set(sid, stage, "state", s)


def _get_stage_capital(db, stage):
    """마틴게일: base × 2 × 3^(stage-2) → 300, 600, 1800, 5400..."""
    if stage < 1: return None
    try:
        from app.models.system_setting import SystemSetting
        cap_row = db.get(SystemSetting, "sajangnim_default_capital")
        max_row = db.get(SystemSetting, "sajangnim_max_stage")
        base = Decimal(str(cap_row.value)) if cap_row and cap_row.value else Decimal("300")
        max_stage = int(max_row.value) if max_row and max_row.value else 3
        if stage > max_stage: return None
        if stage == 1: return base
        if stage == 2: return base * Decimal("2")
        if stage == 3: return base * Decimal("6")
        if stage >= 4: return base * Decimal("2") * (Decimal("3") ** (stage - 2))
        return None
    except Exception: return None


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
    except Exception: return None


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
    except Exception: return []


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
    except Exception: return []


def _calc_obv(klines):
    if not klines or len(klines) < 2: return []
    try:
        obv = [0.0]
        for i in range(1, len(klines)):
            c = float(klines[i][4])
            pc = float(klines[i-1][4])
            v = float(klines[i][5])
            if c > pc: obv.append(obv[-1] + v)
            elif c < pc: obv.append(obv[-1] - v)
            else: obv.append(obv[-1])
        return obv
    except Exception: return []


def _check_reversal_signals(bc, symbol):
    """확실한 하락 6개 지표 AND!"""
    try:
        kl = bc.get_klines(symbol=symbol, interval=KLINE_INTERVAL, limit=KLINE_LIMIT)
        if not kl or len(kl) < 30: return (False, {"reason": "insufficient"})
        opens = [float(k[1]) for k in kl]
        highs = [float(k[2]) for k in kl]
        closes = [float(k[4]) for k in kl]
        volumes = [float(k[5]) for k in kl]
        o, h, c = opens[-2], highs[-2], closes[-2]
        # 1. 위꼬리 음봉
        bearish = c < o
        body = abs(o - c)
        wick = h - max(o, c)
        wick_ok = bearish and body > 0 and wick >= body * 1.5
        # 2. RSI(6) 하락
        rsi_now = _calc_rsi(closes, 6)
        rsi_prev = _calc_rsi(closes[:-1], 6)
        rsi_ok = rsi_now is not None and rsi_prev is not None and rsi_now < rsi_prev - RSI_DROP_MIN
        # 3. MACD Hist 감소
        hist = _calc_macd_hist(closes)
        macd_ok = len(hist) >= 2 and hist[-1] < hist[-2]
        # 4. CCI(9) 하락
        cci = _calc_cci(kl, 9)
        cci_ok = len(cci) >= 2 and cci[-1] < cci[-2]
        # 5. OBV 감소
        obv = _calc_obv(kl)
        obv_ok = len(obv) >= 2 and obv[-1] < obv[-2]
        # 6. 볼륨 매도 우세
        vol_last = volumes[-1]
        vol_avg = mean(volumes[-6:-1]) if len(volumes) >= 6 else vol_last
        vol_ok = vol_last < vol_avg * VOL_MULT
        all_ok = all([wick_ok, rsi_ok, macd_ok, cci_ok, obv_ok, vol_ok])
        snap = {"wick": wick_ok, "rsi": rsi_ok, "macd": macd_ok, "cci": cci_ok,
                "obv": obv_ok, "vol": vol_ok, "all_ok": all_ok}
        return (all_ok, snap)
    except Exception as e:
        logger.warning(f"[Fix41] reversal {symbol}: {e}")
        return (False, {"err": str(e)})


def _get_15m_high(bc, symbol):
    try:
        kl = bc.get_klines(symbol=symbol, interval=KLINE_INTERVAL, limit=2)
        if not kl: return None
        return Decimal(str(kl[-1][2]))
    except Exception as e:
        logger.warning(f"[Fix41] high {symbol}: {e}")
        return None


def _process_strategy(db, bc, s, next_stage):
    """상태 머신 처리! 진입 조건 만족 시 True"""
    sid = s.id
    high = _get_15m_high(bc, s.symbol)
    if high is None: return False
    state = _get_state(sid, next_stage)
    
    if state == "INITIAL":
        _set(sid, next_stage, "peak_A", high)
        _set_state(sid, next_stage, "TRACKING_PEAK_A")
        return False
    
    if state == "TRACKING_PEAK_A":
        peak_a = Decimal(_get(sid, next_stage, "peak_A") or "0")
        if high > peak_a:
            _set(sid, next_stage, "peak_A", high)
        elif high < peak_a * (Decimal("1") - PULLBACK_PCT):
            _set(sid, next_stage, "low", high)
            _set_state(sid, next_stage, "LOW_FORMED")
        return False
    
    if state == "LOW_FORMED":
        low = Decimal(_get(sid, next_stage, "low") or "0")
        peak_a = Decimal(_get(sid, next_stage, "peak_A") or "0")
        if high < low:
            _set(sid, next_stage, "low", high)
        elif high > peak_a:
            _set(sid, next_stage, "peak_B", high)
            _set_state(sid, next_stage, "TRACKING_PEAK_B")
        return False
    
    if state == "TRACKING_PEAK_B":
        peak_b = Decimal(_get(sid, next_stage, "peak_B") or "0")
        if high > peak_b:
            _set(sid, next_stage, "peak_B", high)
        elif high < peak_b * (Decimal("1") - PULLBACK_PCT):
            _set_state(sid, next_stage, "REVERSAL_DETECTED")
            return True  # 진입 조건 체크!
        return False
    
    return False


def _enter_next_stage(db, s, next_stage, snap):
    """다음 단계 진입!"""
    try:
        capital = _get_stage_capital(db, next_stage)
        if capital is None:
            logger.warning(f"[Fix41] max_stage 초과 #{s.id} stage={next_stage}")
            return False
        
        # ExecutionService 사용!
        from app.services.execution_service import ExecutionService
        svc = ExecutionService(db)
        
        # template stages 자본 override!
        from app.models.strategy_template import StrategyTemplate
        tpl = db.get(StrategyTemplate, s.strategy_template_id)
        if tpl and hasattr(tpl, 'stages') and tpl.stages and len(tpl.stages) >= next_stage:
            tpl.stages[next_stage - 1].capital_usdt = capital
            tpl.stages[next_stage - 1].trigger_price = None
            db.commit()

        # Fix 52 = 사장님 -5% 짧은 손절 방침 (모든 진입 워커 통일!)
        try:
            s.force_sl_enabled_override = True
            s.force_sl_roi_override = Decimal("5")
            db.commit()
            logger.info("[Fix41+52] 🛡️ %s SL -5%% 적용 (stage=%s)", s.symbol, next_stage)
        except Exception as _sl_exc:
            logger.warning("[Fix41+52] ⚠️ %s SL override 실패: %s", s.symbol, _sl_exc)
            db.rollback()

        order = None
        for fn_name in ('enter_stage_at_market', 'start_stage', 'add_stage'):
            fn = getattr(svc, fn_name, None)
            if fn is None: continue
            try:
                order = fn(strategy_id=s.id, stage_no=next_stage)
                if order: break
            except TypeError:
                try:
                    order = fn(s.id, next_stage)
                    if order: break
                except Exception: continue
            except Exception as e:
                logger.warning(f"[Fix41] {fn_name}: {e}"); continue
        
        if order is None:
            logger.error(f"[Fix41] entry FAILED #{s.id}")
            return False
        
        _set_state(s.id, next_stage, "ENTERED")
        # 다음 단계 위한 클리어!
        _clear(s.id, next_stage + 1)
        
        # 텔레그램 알림!
        try:
            from app.services.notification_service import NotificationService
            db2 = SessionLocal()
            try:
                NotificationService(db2).send_system_alert(
                    title=f"[Fix41 신 마틴게일] {s.symbol} stage {next_stage} 진입!",
                    body=f"{s.symbol} SHORT #{s.id}\n자본: {capital} USDT\n"
                         f"6지표 AND 통과: {snap}\nspec: {SPEC_VERSION}"
                )
            finally: db2.close()
        except Exception: pass
        
        logger.warning(f"[Fix41] ✅ ENTERED #{s.id} {s.symbol} stage={next_stage} cap={capital}")
        return True
    except Exception as e:
        logger.error(f"[Fix41] enter #{s.id}: {e}", exc_info=True)
        return False


def _get_active_short_strategies(db):
    return db.query(StrategyInstance).filter(
        StrategyInstance.side == "SHORT",
        StrategyInstance.status.in_(list(ACTIVE_LIKE)),
        StrategyInstance.current_stage >= 1
    ).all()


def run_peak_break_reversal_once():
    """scheduler_runner 진입점 (매 30초!)"""
    result = {"scanned": 0, "processed": 0, "entered": 0, "errors": 0,
              "spec_version": SPEC_VERSION}
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
            logger.error(f"[Fix41] BC init: {e}")
            return result
        
        candidates = _get_active_short_strategies(db)
        result["scanned"] = len(candidates)
        if not candidates: return result
        
        for s in candidates:
            try:
                next_stage = s.current_stage + 1
                result["processed"] += 1
                
                # 상태 머신 처리!
                reversal_ready = _process_strategy(db, bc, s, next_stage)
                
                if not reversal_ready: continue
                
                # REVERSAL_DETECTED = 확실한 하락 신호 체크!
                ok, snap = _check_reversal_signals(bc, s.symbol)
                if not ok:
                    logger.info(f"[Fix41] no reversal #{s.id}: {snap}")
                    # 신호 실패 = TRACKING_PEAK_B로 복귀!
                    _set_state(s.id, next_stage, "TRACKING_PEAK_B")
                    continue
                
                # 진입!
                if _enter_next_stage(db, s, next_stage, snap):
                    result["entered"] += 1
                
            except Exception as e:
                result["errors"] += 1
                logger.error(f"[Fix41] #{s.id}: {e}", exc_info=True)
        
        logger.warning(f"[Fix41] DONE: {result}")
        return result
    finally:
        db.close()
