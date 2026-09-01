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
from app.core.strategy_status import ACTIVE_LIKE, SPLIT_ENTRY_MODE
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_suggestion import StrategySuggestion

logger = logging.getLogger(__name__)

SPEC_VERSION = "peak_break_reversal_v2_fix72_2026-08-25"
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
    # 🚨 Fix 159: 옛 배수(base×[1,2,6])는 사다리 10/300/600 을 표현할 수 없다.
    #   같은 「단계 자본」에 읽는 경로가 둘이면 어긋난다 (헌법 101).
    #   → 사다리 단일 진실(get_stage_capital)로 통일.
    if stage < 1: return None
    try:
        from app.services.sajangnim_capital import get_stage_capital
        return get_stage_capital(db, stage)
    except Exception as e:
        logger.warning("[Fix159] 사다리 조회 실패 → None (진입 보류): %s", e)
        return None


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


def _get_24h_change(bc, symbol):
    """Fix 55: 24h 변동률 (%) 조회 — 실패 시 0.0 (fail-open)."""
    for fn_name in ("get_24hr_ticker", "get_ticker_24hr", "get_ticker"):
        fn = getattr(bc, fn_name, None)
        if fn is None:
            continue
        try:
            ticker = fn(symbol=symbol)
        except TypeError:
            try:
                ticker = fn(symbol)
            except Exception as e:
                logger.warning(f"[Fix55] 24h {symbol} {fn_name}: {e}")
                continue
        except Exception as e:
            logger.warning(f"[Fix55] 24h {symbol} {fn_name}: {e}")
            continue
        try:
            if isinstance(ticker, list) and ticker:
                ticker = ticker[0]
            if isinstance(ticker, dict):
                return float(ticker.get("priceChangePercent", 0) or 0)
        except Exception:
            pass
    return 0.0


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
        # Fix 72 (2026-08-25): 학습용 raw 값 추가! (하위 호환 = 기존 boolean 유지!)
        snap = {"wick": wick_ok, "rsi": rsi_ok, "macd": macd_ok, "cci": cci_ok,
                "obv": obv_ok, "vol": vol_ok, "all_ok": all_ok,
                "rsi_now": rsi_now, "rsi_prev": rsi_prev,
                "macd_hist_now": (hist[-1] if hist else None),
                "macd_hist_prev": (hist[-2] if len(hist) >= 2 else None),
                "cci_now": (cci[-1] if cci else None),
                "cci_prev": (cci[-2] if len(cci) >= 2 else None),
                "obv_now": (obv[-1] if obv else None),
                "obv_prev": (obv[-2] if len(obv) >= 2 else None),
                "volume_last": vol_last, "volume_avg": vol_avg,
                "volume_mult": (float(vol_last / vol_avg) if vol_avg else None),
                "close_now": (closes[-1] if closes else None)}
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


def _save_entry_snapshot_suggestion(db, s, next_stage, snap, capital):
    """Fix 72 (2026-08-25): stage-N 마틴게일 트리거 지표 학습 데이터 확보!

    사장님 신 사상 (Fix 41 v1 spec verbatim):
    "2단계 진입가를 15분차트 최고가에서 밀려서 내려오다가 다시 상승해서 전고점을
     돌파하면 대기 모니터링하고 최고가에서 다시 밀려 내려오면 그때 2단계를 실행"

    peak_A → low → break_A → peak_B → reversal 상태 머신의 트리거 시점 지표(
    peak_A/low/peak_B, RSI drop, volume mult, break_ratio, wick, MACD/CCI/OBV 방향)를
    StrategySuggestion.strategy_config.entry_snapshot에 박제 →
    pattern_learning_worker가 이후 성공/실패 분석에 활용.

    fail-open: INSERT 실패 = 진입 자체는 성공! (학습 데이터 유실 < 마틴게일 실패)
    """
    try:
        # Redis 상태 머신 값들 (peak_A / low / peak_B)
        peak_a = _get(s.id, next_stage, "peak_A")
        low = _get(s.id, next_stage, "low")
        peak_b = _get(s.id, next_stage, "peak_B")

        # RSI drop 계산 (snap.rsi_now / rsi_prev 활용!)
        rsi_now = snap.get("rsi_now") if isinstance(snap, dict) else None
        rsi_prev = snap.get("rsi_prev") if isinstance(snap, dict) else None
        rsi_drop_pct = None
        try:
            if rsi_now is not None and rsi_prev is not None and rsi_prev != 0:
                rsi_drop_pct = float(((rsi_prev - rsi_now) / rsi_prev) * 100)
        except Exception:
            rsi_drop_pct = None

        # break_ratio = peak_B / peak_A (돌파 강도!)
        break_ratio = None
        try:
            if peak_a and peak_b:
                pa = Decimal(str(peak_a))
                pb = Decimal(str(peak_b))
                if pa > 0:
                    break_ratio = float(pb / pa)
        except Exception:
            break_ratio = None

        _kst_hour = (datetime.now(timezone.utc).hour + 9) % 24
        entry_snapshot = {
            "source": "PEAK_BREAK_REVERSAL",
            "spec_version": SPEC_VERSION,
            "peak_A": str(peak_a) if peak_a else None,
            "low_between": str(low) if low else None,
            "peak_B": str(peak_b) if peak_b else None,
            "break_ratio": break_ratio,
            "rsi_drop_pct": rsi_drop_pct,
            "rsi_now": rsi_now,
            "rsi_prev": rsi_prev,
            "macd_hist_now": snap.get("macd_hist_now") if isinstance(snap, dict) else None,
            "macd_hist_prev": snap.get("macd_hist_prev") if isinstance(snap, dict) else None,
            "cci_now": snap.get("cci_now") if isinstance(snap, dict) else None,
            "cci_prev": snap.get("cci_prev") if isinstance(snap, dict) else None,
            "obv_now": snap.get("obv_now") if isinstance(snap, dict) else None,
            "obv_prev": snap.get("obv_prev") if isinstance(snap, dict) else None,
            "volume_last": snap.get("volume_last") if isinstance(snap, dict) else None,
            "volume_avg": snap.get("volume_avg") if isinstance(snap, dict) else None,
            "volume_mult": snap.get("volume_mult") if isinstance(snap, dict) else None,
            "close_now": snap.get("close_now") if isinstance(snap, dict) else None,
            "wick_ok": snap.get("wick") if isinstance(snap, dict) else None,
            "rsi_ok": snap.get("rsi") if isinstance(snap, dict) else None,
            "macd_ok": snap.get("macd") if isinstance(snap, dict) else None,
            "cci_ok": snap.get("cci") if isinstance(snap, dict) else None,
            "obv_ok": snap.get("obv") if isinstance(snap, dict) else None,
            "vol_ok": snap.get("vol") if isinstance(snap, dict) else None,
            "regime": "PEAK_BREAK_REVERSAL_SHORT",
            "kst_hour": _kst_hour,
            "parent_strategy_id": s.id,
            "stage_num": next_stage,
            "entered_at": datetime.now(timezone.utc).isoformat(),
        }
        sugg = StrategySuggestion(
            symbol=s.symbol,
            side="SHORT",
            suggestion_type="peak_break_reversal_short",
            strategy_config={
                "capitals": [float(capital) if capital is not None else None],
                "symbol": s.symbol,
                "side": "SHORT",
                "peak_break_reversal": True,
                "stage_num": next_stage,
                "parent_strategy_id": s.id,
                "entry_snapshot": entry_snapshot,
            },
            reason=(
                f"🎯 전고점 돌파 후 반전 SHORT stage-{next_stage} (Fix 41)! "
                f"peak_A={peak_a} low={low} peak_B={peak_b} "
                f"break_ratio={break_ratio} rsi_drop={rsi_drop_pct}"
            ),
            status="EXECUTED",
            execution_mode="AUTO",
            executed_at=datetime.now(timezone.utc),
            executed_strategy_id=s.id,
            outcome_status="PENDING",
        )
        db.add(sugg)
        db.commit()
        logger.info("[Fix41+72] StrategySuggestion 저장 #%s stage=%s", s.id, next_stage)
    except Exception as e:
        logger.warning("[Fix41+72] snapshot save 실패 #%s stage=%s: %s (진입은 성공 유지)",
                       s.id, next_stage, e)
        try:
            db.rollback()
        except Exception:
            pass


def _enter_next_stage(db, s, next_stage, snap, bc=None):
    """다음 단계 진입!"""
    try:
        capital = _get_stage_capital(db, next_stage)
        if capital is None:
            logger.warning(f"[Fix41] max_stage 초과 #{s.id} stage={next_stage}")
            return False

        # Fix 55 P2: 단계별 조건 강화 (사장님 사상 — 3단계 실패 = 말이 안돼!)
        # worker는 SHORT만 처리 (see _get_active_short_strategies)
        if bc is not None and next_stage >= 3:
            chg_24h = _get_24h_change(bc, s.symbol)
            if next_stage == 3:
                # 3단계 강화 = SHORT + 급등 skip (헌법 64!)
                if chg_24h >= 15.0:
                    logger.warning(
                        "[Fix55/stage3] %s SHORT + 24h +%.1f%% = skip (헌법 64!)",
                        s.symbol, chg_24h,
                    )
                    return False
            elif next_stage >= 4:
                # 4단계+ (라스트!) = 매우 엄격 (급등/급락 모두 skip!)
                if abs(chg_24h) >= 15.0:
                    logger.warning(
                        "[Fix55/stage4+] %s 24h %+.1f%% = skip (매우 엄격!)",
                        s.symbol, chg_24h,
                    )
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
        # Fix 72 (2026-08-25): 학습용 StrategySuggestion INSERT (fail-open!)
        _save_entry_snapshot_suggestion(db, s, next_stage, snap, capital)
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
    _rows = db.query(StrategyInstance).filter(
        StrategyInstance.side == "SHORT",
        StrategyInstance.status.in_(list(ACTIVE_LIKE)),
        StrategyInstance.is_archived.is_(False),  # Fix 171: 보관 전략에 발주 금지
        # 🚨 Fix 214 (2026-08-30): 볼밴 분할 제외.
        #   볼밴은 기준선 -3/-5/-7% 라는 **자기 진입 계획**을 갖는다.
        #   여기서 enter_stage_at_market 를 부르면 stage_no 가 채워져
        #   「계획된 단계 진입」처럼 보이지만 실제로는 볼밴 트리거와 무관한
        #   가격에 들어간 것이라, 평단과 손절선이 설계에서 어긋난다.
        #   (Fix 213 과 같은 성격 — 볼밴에 남의 로직을 얹지 않는다)
        StrategyInstance.capital_management_mode != SPLIT_ENTRY_MODE,
        StrategyInstance.current_stage >= 1
    ).all()
    # 🚨 Fix 283 (2026-09-02): 볼밴만 예외였던 것을 「1회 진입 전략」 전체로 넓힌다.
    #   이 워커는 force_sl_roi_override 를 **무조건 5** 로 덮어쓰고(:455) 2단계를
    #   시장가로 얹는다. bb_mid_line(ROI -10% 손절, 1단계 템플릿)에 그게 들어가면
    #   손절선이 반토막 나고 1단계 plan 이 재사용돼 물량이 2배가 된다.
    from app.services.single_entry_guard import drop_single_entry
    return drop_single_entry(_rows, tag="[peak_break_reversal]")


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
                
                # 진입! (Fix 55: bc 전달 = 단계별 24h 필터!)
                if _enter_next_stage(db, s, next_stage, snap, bc=bc):
                    result["entered"] += 1
                
            except Exception as e:
                result["errors"] += 1
                logger.error(f"[Fix41] #{s.id}: {e}", exc_info=True)
        
        logger.warning(f"[Fix41] DONE: {result}")
        return result
    finally:
        db.close()
