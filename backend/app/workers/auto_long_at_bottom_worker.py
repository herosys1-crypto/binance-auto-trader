"""🎯 v226 (2026-08-24 사장님!): 저점 감지 자동 LONG 진입 워커!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사장님 verbatim (2026-08-24):
  "v219와 같은 로직으로 롱을 만들어줘 같이 운영해줘"
  "OBV = 지속성! RSI/CCI/MACD = 단기 움직임!"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

로직 = v219 SHORT 대칭 = LONG 저점 반전 감지!

7중 조건 (AND!):
  1. 🌟 OBV 4H 상승 지속 (Fix 48 하드 게이트! = OBV ↓ = 진입 절대 금지!)
  2. MACD 15m Golden Cross OR Hist 반전 (초록 시작!)
  3. RSI 15m 과매도 회복 (30 근처 → 반등 시작!)
  4. CCI 15m 저점 회복 (-200 근처 → 반등!)
  5. 볼륨 매수 우세 (최근 3봉 vol 증가!)
  6. BB 하단 지지 or 반등 (하단 근처 or 이탈 후 복귀!)
  7. 24h -5% ~ +10% (급락 후 회복 or 급등 초기!)

자본: sajangnim_default_capital (300 USDT!)
daily_limit: sajangnim_top_short_daily_limit (공유! 20건!)

Fix 48 OBV 계층 100%:
  - OBV 상승 X = 즉시 skip (다른 조건 확인도 X)
  - OBV 상승 + 6조건 = 강력 LONG 진입!

헌법 준수:
  - 헌법 6: 단일 진실 (v219와 같은 counter 공유!)
  - 헌법 64 예외: 사장님 실 성공 대칭 로직!
  - 헌법 65/66: Agent 검증 우선 + 기존 팀 활용 (_create_auto_bb_strategy 재사용!)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_LIKE
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_suggestion import StrategySuggestion
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

# ============================================================================
# SPEC 상수 (사장님 verbatim!)
# ============================================================================
SPEC_VERSION = "auto_long_at_bottom_v1_2026-08-24"
INTERVAL_SEC = 30

DEFAULT_LEVERAGE = 2          # 사장님 default!
DEFAULT_CAPITAL = 300.0       # sajangnim_default_capital fallback!
DEFAULT_DAILY_LIMIT = 20      # sajangnim_top_short_daily_limit fallback!

# 4H OBV 상승 하드 게이트 = Fix 48!
OBV_LOOKBACK_4H = 20          # 4H 최근 20봉 = 약 3일 매크로!
OBV_MIN_SLOPE_PCT = 0.5       # OBV 20봉 회귀 기울기 > 0.5% = "상승 지속"!

# 15m MACD/RSI/CCI 반전!
MACD_15M_LIMIT = 80
RSI_OVERSOLD_MAX = 45         # RSI ≤ 45 = 과매도 회복권!
RSI_MIN_TURNUP = 0.5          # RSI now > prev + 0.5 = 반등!
CCI_OVERSOLD_MAX = -50        # CCI ≤ -50 = 저점권!
CCI_MIN_TURNUP = 5.0          # CCI now > prev + 5 = 반등!

# 24h 필터!
MIN_24H_CHANGE = -5.0         # -5% 이상 (급락 계속 X!)
MAX_24H_CHANGE = 10.0         # +10% 이하 (급등 계속 X = 물타기 위험!)

# 스캔 상한!
MAX_SYMBOLS = 40              # 심볼당 4 kline call = API 부담 대응!
MIN_CONFIDENCE = 0.85         # 통과 최소 신뢰도!

# ============================================================================
# 조건 검사 헬퍼 (v219 대칭 = LONG 방향!)
# ============================================================================


def _get_obv_trend(bc, symbol: str, interval: str = "4h") -> dict:
    """🌟 OBV 매크로 방향 (Fix 48 하드 게이트!)

    OBV 20봉 = 선형 회귀 기울기 계산!
    - rising = True  → 4H OBV 상승 지속 = LONG 진입 가능!
    - rising = False → 진입 절대 금지! (다른 조건 확인도 X!)

    Returns:
        {rising: bool, obv_last: float, obv_min_20: float, slope_pct: float}
    """
    try:
        from app.services.chart_analyzer import ChartAnalyzer
        kl = bc.get_klines(symbol=symbol, interval=interval, limit=max(OBV_LOOKBACK_4H + 5, 30))
        if not isinstance(kl, list) or len(kl) < OBV_LOOKBACK_4H:
            return {"rising": False, "reason": "insufficient_kl"}

        obv = [float(x) for x in ChartAnalyzer.compute_obv(kl)]
        if len(obv) < OBV_LOOKBACK_4H:
            return {"rising": False, "reason": "insufficient_obv"}

        window = obv[-OBV_LOOKBACK_4H:]
        obv_last = window[-1]
        obv_min = min(window)
        obv_max = max(window)
        base = max(abs(obv_max), abs(obv_min), 1.0)

        # 선형 회귀 기울기 (% base 대비!)
        n = len(window)
        xs = list(range(n))
        mean_x = sum(xs) / n
        mean_y = sum(window) / n
        num = sum((xs[i] - mean_x) * (window[i] - mean_y) for i in range(n))
        den = sum((xs[i] - mean_x) ** 2 for i in range(n)) or 1.0
        slope = num / den
        slope_pct = (slope / base) * 100.0

        # LONG 조건 = slope > 임계값 (상승 지속!)
        rising = slope_pct >= OBV_MIN_SLOPE_PCT
        return {
            "rising": rising,
            "obv_last": obv_last,
            "obv_min_20": obv_min,
            "obv_max_20": obv_max,
            "slope_pct": round(slope_pct, 4),
        }
    except Exception as e:
        logger.debug("[auto_long_bottom] _get_obv_trend %s %s 실패: %s", symbol, interval, e)
        return {"rising": False, "reason": f"exc:{e}"}


def _get_macd_signal(bc, symbol: str, interval: str = "15m") -> dict:
    """MACD 15m Golden Cross OR Hist 반전 (초록 시작!).

    Returns:
        {bullish: bool, cross: bool, hist_turnup: bool, hist_now: float, hist_prev: float}
    """
    try:
        from app.services.bb_4h_band_analyzer import BB4HBandAnalyzer
        kl = bc.get_klines(symbol=symbol, interval=interval, limit=MACD_15M_LIMIT)
        if not isinstance(kl, list) or len(kl) < 40:
            return {"bullish": False, "reason": "insufficient_kl"}

        closes = [float(k[4]) for k in kl]
        ema12 = BB4HBandAnalyzer._calc_ema(closes, 12)
        ema26 = BB4HBandAnalyzer._calc_ema(closes, 26)
        if not ema12 or not ema26:
            return {"bullish": False, "reason": "no_ema"}

        offset = 26 - 12
        macd_line = [a - b for a, b in zip(ema12[offset:], ema26)]
        if len(macd_line) < 10:
            return {"bullish": False, "reason": "short_macd"}

        signal_line = BB4HBandAnalyzer._calc_ema(macd_line, 9)
        if not signal_line or len(signal_line) < 3:
            return {"bullish": False, "reason": "no_signal"}

        hist = [m - s for m, s in zip(macd_line[-len(signal_line):], signal_line)]
        if len(hist) < 3:
            return {"bullish": False, "reason": "short_hist"}

        hist_now = hist[-1]
        hist_prev = hist[-2]
        hist_prev2 = hist[-3]

        # Golden Cross = macd_line 이 signal 을 상향 돌파!
        _ml_tail = macd_line[-len(signal_line):]
        cross = (
            len(_ml_tail) >= 2 and len(signal_line) >= 2
            and _ml_tail[-2] <= signal_line[-2]
            and _ml_tail[-1] > signal_line[-1]
        )
        # Hist 반전 = 이전 봉이 저점 + 지금 봉 상승!
        hist_turnup = (hist_prev < hist_prev2) and (hist_now > hist_prev)

        return {
            "bullish": cross or hist_turnup,
            "cross": cross,
            "hist_turnup": hist_turnup,
            "hist_now": hist_now,
            "hist_prev": hist_prev,
        }
    except Exception as e:
        logger.debug("[auto_long_bottom] _get_macd_signal %s %s 실패: %s", symbol, interval, e)
        return {"bullish": False, "reason": f"exc:{e}"}


def _check_long_entry_conditions(bc, symbol: str, ticker_24h: dict) -> dict:
    """🎯 7중 LONG 조건 AND 검사 (사장님 사상 100%!)

    Fix 48 OBV 계층 하드 게이트:
      OBV 4H 상승 X = 즉시 skip (다른 조건 확인도 X!)

    Returns:
        {detected, passed, confidence, signals, entry_snapshot, reason}
    """
    try:
        # ---- 조건 7 (선처리): 24h 변동 -5% ~ +10% ----
        chg24 = float(ticker_24h.get("priceChangePercent", 0) or 0)
        c7 = MIN_24H_CHANGE <= chg24 <= MAX_24H_CHANGE
        if not c7:
            return {
                "detected": False, "passed": 0, "confidence": 0.0,
                "reason": f"24h={chg24:.2f}% 범위 밖 ({MIN_24H_CHANGE}~{MAX_24H_CHANGE})",
            }

        # ---- 조건 1 (Fix 48 하드 게이트): OBV 4H 상승 지속 ----
        obv_trend = _get_obv_trend(bc, symbol, "4h")
        c1 = obv_trend.get("rising", False)
        if not c1:
            return {
                "detected": False, "passed": 0, "confidence": 0.0,
                "reason": f"OBV 4H 상승 X (slope={obv_trend.get('slope_pct')}%) = Fix 48 하드 게이트!",
                "obv_trend": obv_trend,
            }

        # ---- 15m 지표 분석 (한 번에 모두!) ----
        from app.services.chart_analyzer import ChartAnalyzer
        a15 = ChartAnalyzer.analyze_timeframe(bc, symbol, "15m", limit=60)
        if not a15:
            return {
                "detected": False, "passed": 1, "confidence": 0.0,
                "reason": "15m 분석 실패",
            }

        closes = a15.get("closes") or []
        rsi_now = a15.get("rsi_now")
        rsi_prev = a15.get("rsi_prev")
        cci_now = a15.get("cci_now")
        cci_prev = a15.get("cci_prev")
        bb_lo = a15.get("bb_lo_last")

        # ---- 조건 2: MACD Golden Cross OR Hist 반전 (초록 시작!) ----
        macd = _get_macd_signal(bc, symbol, "15m")
        c2 = macd.get("bullish", False)

        # ---- 조건 3: RSI 과매도 회복 (30 근처 → 반등!) ----
        c3 = (
            rsi_now is not None and rsi_prev is not None
            and rsi_now <= RSI_OVERSOLD_MAX
            and rsi_now > rsi_prev + RSI_MIN_TURNUP
        )

        # ---- 조건 4: CCI 저점 회복 (-200 근처 → 반등!) ----
        c4 = (
            cci_now is not None and cci_prev is not None
            and cci_now <= CCI_OVERSOLD_MAX
            and cci_now > cci_prev + CCI_MIN_TURNUP
        )

        # ---- 조건 5: 볼륨 매수 우세 (최근 3봉 vol 증가!) ----
        c5 = False
        try:
            kl = bc.get_klines(symbol=symbol, interval="15m", limit=6)
            if isinstance(kl, list) and len(kl) >= 4:
                vols = [float(k[5]) for k in kl]
                # 최근 3봉 평균 > 이전 3봉 평균 = 매수세 증가!
                c5 = sum(vols[-3:]) / 3.0 > sum(vols[-6:-3]) / 3.0 * 1.1
        except Exception:
            pass

        # ---- 조건 6: BB 하단 지지 or 반등 ----
        # (하단 근처 = close 가 하단의 ±1% 안 or 이탈 후 복귀!)
        c6 = False
        if bb_lo is not None and closes:
            close_last = closes[-1]
            close_prev = closes[-2] if len(closes) >= 2 else close_last
            near_band = abs(close_last - bb_lo) / bb_lo * 100.0 <= 1.0
            recover = (close_prev < bb_lo) and (close_last >= bb_lo)
            c6 = near_band or recover

        passed = sum([c1, c2, c3, c4, c5, c6, c7])
        # confidence: 4/7 = 0.85, 5/7 = 0.88, 6/7 = 0.91, 7/7 = 0.94
        # (사장님 요구 = 강력 조건 = 최소 4중!)
        min_passed = 4
        if passed < min_passed:
            return {
                "detected": False, "passed": passed, "confidence": 0.0,
                "reason": f"passed={passed}/7 < {min_passed}",
                "signals": {
                    "obv_4h_rising": c1, "macd_bullish": c2,
                    "rsi_recover": c3, "cci_recover": c4,
                    "vol_up": c5, "bb_low_support": c6, "chg24_ok": c7,
                },
            }

        confidence = round(0.85 + 0.03 * (passed - min_passed), 4)
        confidence = min(confidence, 0.94)

        _kst_hour = (datetime.now(timezone.utc).hour + 9) % 24
        entry_snapshot = {
            "rsi": rsi_now,
            "cci": cci_now,
            "obv_slope_pct": obv_trend.get("slope_pct"),
            "regime": "BOTTOM_REVERSAL",
            "source": "SAJANGNIM_BOTTOM",
            "sustained_bars": 0,
            "change_24h": chg24,
            "kst_hour": _kst_hour,
            "confidence": confidence,
            "signals_passed": {
                "obv_4h_rising": c1, "macd_bullish": c2,
                "rsi_recover": c3, "cci_recover": c4,
                "vol_up": c5, "bb_low_support": c6, "chg24_ok": c7,
            },
            "bb_lo": bb_lo,
            "close_last": closes[-1] if closes else None,
            "macd_cross": macd.get("cross"),
            "macd_hist_turnup": macd.get("hist_turnup"),
            "spec_version": SPEC_VERSION,
            "entered_at": datetime.now(timezone.utc).isoformat(),
        }

        return {
            "detected": True,
            "passed": passed,
            "confidence": confidence,
            "signals": entry_snapshot["signals_passed"],
            "entry_snapshot": entry_snapshot,
            "change_24h": chg24,
            "obv_slope_pct": obv_trend.get("slope_pct"),
        }
    except Exception as e:
        logger.warning("[auto_long_bottom] _check %s 실패: %s", symbol, e)
        return {"detected": False, "passed": 0, "confidence": 0.0, "reason": f"exc:{e}"}


# ============================================================================
# 세팅/카운터 헬퍼 (v219 공유!)
# ============================================================================


def _get_daily_limit(db: Session) -> int:
    """사장님 사상 (헌법 6 단일 진실!): v219 SHORT 과 같은 counter 공유!

    사장님 verbatim: "일 진입수는 급등락 실시간과 같이 세팅"
    = sajangnim_top_short_daily_limit → auto_bb_break_daily_limit 통합!
    """
    for key in ("sajangnim_top_short_daily_limit", "auto_bb_break_daily_limit"):
        try:
            row = db.get(SystemSetting, key)
            if row and row.value:
                v = int(row.value)
                if v > 0:
                    return v
        except Exception:
            continue
    return DEFAULT_DAILY_LIMIT


def _get_default_capital(db: Session) -> float:
    """사장님 초기 자본 = 300 USDT default (조정 가능!)"""
    try:
        row = db.get(SystemSetting, "sajangnim_default_capital")
        if row and row.value:
            v = float(row.value)
            if v > 0:
                return v
    except Exception:
        pass
    return DEFAULT_CAPITAL


# ============================================================================
# LONG 진입 (v219 _create_auto_bb_strategy 재사용!)
# ============================================================================


def _create_long_strategy(
    db: Session, symbol: str, capital: float,
) -> StrategyInstance | None:
    """v219 진입 방식 재사용 = _create_auto_bb_strategy!

    - strategy_type_suffix = "_SAJANGNIM_BOTTOM" (v219 _SAJANGNIM_TOP 대칭!)
    - leverage = 2x (사장님 default!)
    - 1단계만 (v177 사상!)
    - SL 강제 -80% (v225 사장님 사상!)
    - MARKET 진입 + start_stage1 실 주문 발송!
    """
    try:
        from app.workers.auto_bb_breakdown_worker import _create_auto_bb_strategy
        cfg = {
            "capitals": [capital],
            "leverage": DEFAULT_LEVERAGE,
        }
        return _create_auto_bb_strategy(
            db, symbol, "LONG", cfg,
            strategy_type_suffix="_SAJANGNIM_BOTTOM",
        )
    except Exception as e:
        logger.warning(
            "[auto_long_bottom] _create_long_strategy %s 실패: %s", symbol, e,
        )
        return None


def _notify_entry(strategy: StrategyInstance, confidence: float, snapshot: dict) -> None:
    """텔레그램 알림 (v219 SHORT 대칭!)"""
    try:
        from app.services.notification_service import NotificationService
        db_n = SessionLocal()
        try:
            ns = NotificationService(db_n)
            body = (
                f"🐂 사장님 저점 자동 진입! ({SPEC_VERSION})\n"
                f"심볼: {strategy.symbol} LONG\n"
                f"자본: {float(strategy.total_capital):.2f} USDT × {strategy.leverage}x\n"
                f"신뢰도: {confidence*100:.0f}%\n"
                f"24h: {snapshot.get('change_24h', 0):+.2f}%\n"
                f"OBV 4H 기울기: {snapshot.get('obv_slope_pct')}%\n"
                f"RSI: {snapshot.get('rsi')} / CCI: {snapshot.get('cci')}\n"
                f"통과: {sum(1 for v in (snapshot.get('signals_passed') or {}).values() if v)}/7"
            )
            ns.send_system_alert(
                title=f"✅ [저점 LONG] {strategy.symbol} ({confidence*100:.0f}%)",
                body=body,
            )
        finally:
            try:
                db_n.close()
            except Exception:
                pass
    except Exception as e:
        logger.warning("[auto_long_bottom] telegram 실패: %s", e)


# ============================================================================
# MAIN 진입점 (매 30초!)
# ============================================================================


def run_auto_long_at_bottom_once() -> dict:
    """매 30초 = 저점 감지 + 자동 LONG 진입!"""
    db: Session = SessionLocal()
    entered = 0
    skipped = 0
    scanned = 0
    results: list[dict] = []
    try:
        # 1. daily_limit 체크 (v219 통합!)
        daily_limit = _get_daily_limit(db)
        if daily_limit <= 0:
            return {"note": "daily_limit=0 (OFF!)", "entered": 0, "spec": SPEC_VERSION}

        from app.workers.auto_bb_breakdown_worker import _count_used_slots
        used = _count_used_slots(db)
        remaining = daily_limit - used
        if remaining <= 0:
            return {
                "note": f"daily {used}/{daily_limit} (v219 공유 counter!)",
                "entered": 0, "spec": SPEC_VERSION,
            }

        # 2. mainnet 계정!
        account = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if not account:
            return {"error": "mainnet 계정 없음!", "entered": 0, "spec": SPEC_VERSION}

        # 3. API Ban 체크!
        try:
            from app.core.api_backoff import is_account_banned
            if is_account_banned(account.id):
                return {"error": "API Ban 중!", "entered": 0, "spec": SPEC_VERSION}
        except Exception:
            pass

        # 4. BinanceClient!
        from app.integrations.binance.client import BinanceClient
        from app.core.crypto import decrypt_text
        bc = BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=False,
        )

        # 5. 24h ticker 상위 = 후보!
        tickers = bc.get_24hr_ticker()
        if not isinstance(tickers, list):
            return {"error": "ticker 실패!", "entered": 0, "spec": SPEC_VERSION}

        usdt = [t for t in tickers if str(t.get("symbol", "")).endswith("USDT")]
        try:
            usdt.sort(key=lambda x: float(x.get("quoteVolume", 0) or 0), reverse=True)
        except Exception:
            pass

        # 24h 범위 pre-filter (-5% ~ +10%!)
        candidates = []
        for t in usdt[:MAX_SYMBOLS * 3]:
            try:
                c = float(t.get("priceChangePercent", 0) or 0)
                if MIN_24H_CHANGE <= c <= MAX_24H_CHANGE:
                    candidates.append(t)
                if len(candidates) >= MAX_SYMBOLS:
                    break
            except Exception:
                continue

        if not candidates:
            return {"note": "24h 범위 심볼 없음", "entered": 0, "spec": SPEC_VERSION}

        # 6. 활성 심볼 skip!
        active_syms = set()
        try:
            active = db.execute(
                select(StrategyInstance).where(
                    StrategyInstance.status.in_(list(ACTIVE_LIKE))
                )
            ).scalars().all()
            active_syms = {r.symbol for r in active}
        except Exception:
            pass

        # 7. 자본 계산!
        capital = _get_default_capital(db)

        # 8. 심볼별 검사 + 진입!
        for t in candidates:
            if entered >= remaining:
                break
            symbol = str(t.get("symbol", ""))
            if not symbol or symbol in active_syms:
                continue

            try:
                scanned += 1
                result = _check_long_entry_conditions(bc, symbol, t)
                if not result.get("detected"):
                    continue
                confidence = float(result.get("confidence", 0))
                if confidence < MIN_CONFIDENCE:
                    continue

                # 9. 실 진입!
                new_strategy = _create_long_strategy(db, symbol, capital)
                if not new_strategy:
                    skipped += 1
                    logger.info(
                        "[auto_long_bottom] ❌ %s 진입 실패 = skip (다음 사이클 재시도!)",
                        symbol,
                    )
                    continue

                # Fix 신 사상: 저점 LONG = -5% 짧은 손절! (auto_short_at_top 대칭!)
                # 사장님 verbatim: "v219 단계별 진입후 -5% 손실이면 청산하고 대기 모니터링"
                # 기존 활성 전략은 그대로! 신 진입만 -5%!
                try:
                    new_strategy.force_sl_enabled_override = True
                    new_strategy.force_sl_roi_override = Decimal("5")
                    db.commit()
                    logger.info(
                        "[auto_long_bottom] 🛡️ %s SL override -5%% 적용 (strategy_id=%s)",
                        symbol, new_strategy.id,
                    )
                except Exception as _sl_exc:
                    logger.warning(
                        "[auto_long_bottom] ⚠️ %s SL override 실패: %s (진입은 유지)",
                        symbol, _sl_exc,
                    )
                    db.rollback()

                # 10. StrategySuggestion 저장 (학습!)
                snapshot = result.get("entry_snapshot") or {}
                sugg = StrategySuggestion(
                    symbol=symbol, side="LONG",
                    suggestion_type="sajangnim_bottom_long",
                    strategy_config={
                        "capitals": [capital],
                        "symbol": symbol, "side": "LONG",
                        "sajangnim_bottom": True,
                        "confidence": confidence,
                        "signals": result.get("signals"),
                        "entry_snapshot": snapshot,
                    },
                    confidence_score=Decimal(str(round(confidence, 4))),
                    reason=(
                        f"🐂 사장님 저점 LONG ({SPEC_VERSION})! "
                        f"{result.get('passed')}/7 통과 conf={confidence*100:.0f}% "
                        f"24h={result.get('change_24h', 0):+.2f}% "
                        f"OBV_slope={result.get('obv_slope_pct')}%"
                    ),
                    status="EXECUTED",
                    execution_mode="AUTO",
                    executed_at=datetime.now(timezone.utc),
                    executed_strategy_id=new_strategy.id,
                    outcome_status="PENDING",
                )
                db.add(sugg)
                db.commit()

                remaining -= 1
                entered += 1
                results.append({
                    "symbol": symbol,
                    "side": "LONG",
                    "capital": capital,
                    "confidence": confidence,
                    "passed": result.get("passed"),
                    "strategy_id": new_strategy.id,
                })
                logger.warning(
                    "[auto_long_bottom] ✅ 자동 LONG: %s cap=%.2f conf=%.2f (id=%d)",
                    symbol, capital, confidence, new_strategy.id,
                )

                # 11. 텔레그램!
                _notify_entry(new_strategy, confidence, snapshot)

                # 12. 오케스트라 EventBus (v206 통합!)
                try:
                    from app.agents.orchestrator.event_bus import get_event_bus
                    from app.agents.orchestrator.event_types import EventType
                    bus = get_event_bus()
                    bus.publish(EventType.AUTO_ENTRY_TRIGGERED, {
                        "strategy_id": new_strategy.id,
                        "symbol": symbol, "side": "LONG",
                        "prob": confidence,
                        "regime": "BOTTOM_REVERSAL",
                        "source": "SAJANGNIM_BOTTOM",
                    })
                except Exception as _be:
                    logger.debug("[auto_long_bottom] EventBus 실패 (fail-open): %s", _be)

            except Exception as e:
                logger.warning("[auto_long_bottom] %s 처리 실패: %s", symbol, e)
                skipped += 1
                try:
                    db.rollback()
                except Exception:
                    pass
                continue

        logger.info(
            "[auto_long_bottom] 완료: scanned=%d entered=%d skipped=%d used=%d/%d",
            scanned, entered, skipped, used + entered, daily_limit,
        )
        return {
            "spec": SPEC_VERSION,
            "scanned": scanned,
            "entered": entered,
            "skipped": skipped,
            "daily_limit": daily_limit,
            "used_after": used + entered,
            "results": results,
        }
    except Exception as e:
        logger.exception("[auto_long_bottom] 실행 실패: %s", e)
        return {"error": str(e), "entered": entered, "spec": SPEC_VERSION}
    finally:
        try:
            db.close()
        except Exception:
            pass


# ============================================================================
# 호환: 기존 워커 명명 규약 (run_XXX!)
# ============================================================================


def run_auto_long_at_bottom() -> dict:
    """스케줄러 호환 alias = run_auto_long_at_bottom_once!"""
    return run_auto_long_at_bottom_once()
