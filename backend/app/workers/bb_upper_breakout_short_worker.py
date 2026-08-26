"""🌟 Fix 67 (2026-08-25 사장님!): 볼밴 상단돌파 마틴게일 SHORT 워커!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사장님 verbatim (헌법 72!):
  "가능하면 급등해서 볼밴 상단돌파 했을때 마틴게일 전략으로 진입해야
   확실한 수익을 만들수 있어"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

로직:
1. 24h +15%+ 급등 심볼 스캔 (거래대금 순 상위 50!)
2. 15m 봉 BB 상단 돌파 감지:
   - close_now > bb_up (BB 상단 돌파!)
   - OR 최근 3봉 중 2봉+ 상단 위!
3. 마틴게일 진입 지표 3중 확인:
   - RSI(6/14) > 70 (과매수!)
   - MACD Hist 최근 상승 지속!
   - 볼륨 급증 (최근 3봉 평균 > 이전 6봉 평균 × 1.5!)
4. Fix 44 트렌드 강도 필터 (extreme_bull skip / strong_bull 감산!)
5. Fix 65 OBV gate + Fix 66 P1 blocklist + Fix 66 P2 regime!
   - 주의: 사장님 사상 = BB 상단 돌파 = 급등 완성!
   - regime "pump_active" 는 OK, "pump_completed_dumping" 만 skip!
6. Redis 알람 저장 (sajangnim:top_short:{symbol}) → auto_short_at_top 자동 진입!
7. 진입 후 마틴게일: 300 → 600 → 1800 (realtime_reentry_worker 담당!)
8. 텔레그램 알림!

파이프라인 흐름:
  이 워커 (감지) → Redis alert
                     ↓
              auto_short_at_top_worker (진입)
                     ↓
              _create_auto_bb_strategy (1단계 300 USDT)
                     ↓
                 -5% SL (Fix 49)
                     ↓
              realtime_reentry_worker (마틴게일 자동!)
                     ↓
              300 → 600 → 1800 → 라스트 챈스 (Fix 53)

SPEC: bb_upper_breakout_short_v1_fix67_2026-08-25
헌법 72 (2026-08-25 사장님 신 사상 v2 SHORT!): 급등+BB상단돌파 = 확실한 수익!
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.exchange_account import ExchangeAccount

logger = logging.getLogger(__name__)

# ─── 스펙 상수 ───────────────────────────────────────────────────────
SPEC_VERSION = "bb_upper_breakout_short_v1_fix67_2026-08-25"
INTERVAL_SEC = 300      # 5분 주기
MAX_SYMBOLS = 50        # 상위 50 심볼 (Fix 64 대칭!)
MIN_24H_CHANGE = 15.0   # 급등 필터 (사장님 verbatim "급등해서"!)
ALERT_TTL_SEC = 1800    # 30분 알람 유효

# ─── 마틴게일 진입 지표 임계값 (사장님 verbatim!) ──────────────────
RSI_OVERBOUGHT = 70.0                # RSI > 70 = 과매수!
BREAKOUT_STRENGTH_MIN_PCT = 0.3      # BB 상단 돌파 최소 강도 (%)
VOLUME_SURGE_RATIO = 1.5             # 최근 3봉 vs 이전 6봉 볼륨 비율!
MIN_CONFIDENCE = 0.85                # auto_short_at_top 통과 최소치 (L159!)

# ─── Fix 44 트렌드 강도 임계값 (재사용 = 헌법 6 단일 진실!) ────────
TREND_CONFIDENCE_PENALTY = 0.05

# ─── Fix 100 (2026-08-26 사장님 신 사상!): 반복 상승 감지! ─────────
# 사장님 verbatim:
#   "한번올랐다 다시 내려오고 이렇게 2-3번 반복하면
#    rsi macd obv cci 등등 고점에 이란 신호를 보고 진입"
# = 단일 급등 상승 초입 오진입 방지! 2회+ 반복 상승 후만 진짜 정점!
PEAK_LOOKBACK_BARS = 20    # 4H 최근 ~3.3일 창
PEAK_MIN_GAP = 3           # pivot 좌우 확인 봉수
MIN_PEAK_COUNT_4H = 2      # 사장님 verbatim = 최소 2회 반복 상승!


def _count_swing_peaks(closes: list, lookback: int = PEAK_LOOKBACK_BARS,
                       min_gap: int = PEAK_MIN_GAP) -> int:
    """🌟 Fix 100 (2026-08-26 사장님!): 최근 lookback 봉에서 swing peak 개수 카운트!

    peak = 좌우 min_gap 봉 대비 최고!

    사장님 사상:
      "한번올랐다 다시 내려오고 이렇게 2-3번 반복하면
       rsi macd obv cci 등등 고점에 이란 신호를 보고 진입"
      = 반복 상승 = 소진 확인 = 진짜 정점!
      = 단일 급등 초입 오진입 완전 차단!
    """
    if not closes or len(closes) < lookback:
        return 0
    window = closes[-lookback:]
    peaks = 0
    for i in range(min_gap, len(window) - min_gap):
        try:
            center = float(window[i])
            left_max = max(float(x) for x in window[i - min_gap:i])
            right_max = max(float(x) for x in window[i + 1:i + min_gap + 1])
            if center > left_max and center > right_max:
                peaks += 1
        except Exception:
            continue
    return peaks


def _check_bb_upper_breakout(bc, symbol: str) -> tuple[bool, float, dict]:
    """🎯 BB 상단 돌파 감지 (핵심!)

    사장님 verbatim: "급등해서 볼밴 상단돌파 했을때"

    조건 (둘 중 하나만 만족해도 통과!):
      A. 마지막 봉 close > BB 상단 AND 돌파 강도 >= 0.3%
      B. 최근 3봉 중 2봉 이상이 BB 상단 위 마감!

    Returns:
        (detected, breakout_strength_pct, snapshot)
    """
    try:
        from app.services.chart_analyzer import ChartAnalyzer
        a15 = ChartAnalyzer.analyze_timeframe(bc, symbol, "15m", limit=60)
        if not a15:
            return False, 0.0, {"reason": "no_analysis"}

        closes = a15.get("closes") or []
        bb_up = a15.get("bb_up_last")
        if not closes or bb_up is None or len(closes) < 30:
            return False, 0.0, {"reason": "insufficient_data"}

        close_now = float(closes[-1])
        bb_up_f = float(bb_up)
        if bb_up_f <= 0:
            return False, 0.0, {"reason": "invalid_bb_up"}

        breakout_pct = (close_now - bb_up_f) / bb_up_f * 100.0

        # 조건 A: 직접 돌파 + 강도!
        cond_a = close_now > bb_up_f and breakout_pct >= BREAKOUT_STRENGTH_MIN_PCT

        # 조건 B: 최근 3봉 지속 (2/3봉 상단 위!)
        # BB 상단은 마지막 값만 있으므로 근사 = 최근 3봉 close 대비 bb_up_f 유지!
        recent_3 = closes[-3:] if len(closes) >= 3 else closes
        above_count = sum(1 for c in recent_3 if float(c) > bb_up_f)
        cond_b = above_count >= 2

        snapshot = {
            "close_now": close_now,
            "bb_up": bb_up_f,
            "bb_lo": a15.get("bb_lo_last"),
            "breakout_pct": round(breakout_pct, 3),
            "above_count_last3": above_count,
            "cond_a": cond_a,
            "cond_b": cond_b,
            "rsi_now": a15.get("rsi_now"),
            "cci_now": a15.get("cci_now"),
        }

        return (cond_a or cond_b), breakout_pct, snapshot
    except Exception as e:
        logger.warning("[Fix67/bb_breakout] %s: %s (fail-open=False)", symbol, e)
        return False, 0.0, {"reason": f"error:{e}"}


def _check_martingale_signals(bc, symbol: str) -> tuple[int, dict]:
    """🎯 마틴게일 진입 3중 지표 확인 (사장님 사상 = 확실한 수익!)

    사장님 verbatim: "마틴게일 전략으로 진입해야 확실한 수익을 만들수 있어"

    3중 조건:
      1. RSI > 70 (과매수 = 정점 가능성!)
      2. MACD Hist 최근 3봉 상승 지속 (모멘텀 존재 = 돌파 유효!)
      3. 볼륨 급증 (최근 3봉 평균 > 이전 6봉 평균 × 1.5!)

    Returns:
        (passed_count 0~3, signals dict)
    """
    signals: dict[str, Any] = {}
    try:
        from app.services.chart_analyzer import ChartAnalyzer
        a15 = ChartAnalyzer.analyze_timeframe(bc, symbol, "15m", limit=60)
        if not a15:
            return 0, {"reason": "no_analysis"}

        # 1. RSI > 70
        rsi_now = a15.get("rsi_now")
        signals["rsi_overbought"] = bool(rsi_now is not None and float(rsi_now) > RSI_OVERBOUGHT)
        signals["rsi_value"] = float(rsi_now) if rsi_now is not None else None

        # 2. MACD Hist 상승 지속 (최근 3봉 = -3 <= -2 <= -1 monotonic ascending!)
        hist = a15.get("macd_hist") or []
        macd_rising = False
        if len(hist) >= 3:
            try:
                h_last = float(hist[-1])
                h_prev = float(hist[-2])
                h_prev2 = float(hist[-3])
                # 최근 2단계 모두 상승 (또는 유지) = 상승 지속!
                macd_rising = (h_last >= h_prev) and (h_prev >= h_prev2)
                signals["macd_hist_last3"] = [
                    round(h_prev2, 6), round(h_prev, 6), round(h_last, 6),
                ]
            except Exception:
                pass
        signals["macd_rising"] = macd_rising

        # 3. 볼륨 급증 (최근 3봉 avg > 이전 6봉 avg × 1.5)
        vol_surge = False
        try:
            klines = bc.get_klines(symbol=symbol, interval="15m", limit=20)
            if isinstance(klines, list) and len(klines) >= 9:
                vols = [float(k[5]) for k in klines[-9:]]  # 최근 9봉
                recent_3_avg = sum(vols[-3:]) / 3.0
                prior_6_avg = sum(vols[:6]) / 6.0
                if prior_6_avg > 0:
                    ratio = recent_3_avg / prior_6_avg
                    vol_surge = ratio >= VOLUME_SURGE_RATIO
                    signals["vol_recent3_avg"] = round(recent_3_avg, 3)
                    signals["vol_prior6_avg"] = round(prior_6_avg, 3)
                    signals["vol_ratio"] = round(ratio, 3)
        except Exception as _ve:
            logger.debug("[Fix67/vol] %s vol calc 실패: %s", symbol, _ve)
        signals["vol_surge"] = vol_surge

        passed = sum([
            signals["rsi_overbought"],
            signals["macd_rising"],
            signals["vol_surge"],
        ])
        return passed, signals
    except Exception as e:
        logger.warning("[Fix67/martingale_signals] %s: %s", symbol, e)
        return 0, {"reason": f"error:{e}"}


def _save_alert_redis(
    r,
    symbol: str,
    breakout_pct: float,
    martingale_passed: int,
    martingale_signals: dict,
    breakout_snapshot: dict,
    confidence: float,
    chg_24h: float,
    trend_strength: str,
    peaks_4h: int = 0,
) -> bool:
    """Redis 알람 저장 (auto_short_at_top_worker가 processing!)

    ⚠️ CRITICAL fix: auto_short_at_top ALERT_PATTERN = "pump_top:alert:*" 만 스캔!
    → key = pump_top:alert:{symbol}:SHORT (pump_top_detector 동일 패턴!)
    source = "bb_upper_breakout" (구분!)
    """
    try:
        alert_key = f"pump_top:alert:{symbol}:SHORT"
        alert_data = {
            "symbol": symbol,
            "side": "SHORT",
            "confidence": confidence,
            "change_24h": chg_24h,
            "trend_strength": trend_strength,
            "trend_penalty_applied": (trend_strength == "strong_bull"),
            "breakout_pct": round(breakout_pct, 3),
            "martingale_passed": martingale_passed,
            "martingale_signals": martingale_signals,
            "peaks_4h": peaks_4h,  # Fix 100 = 반복 상승 횟수 학습!
            "entry_snapshot": {
                **breakout_snapshot,
                "martingale_signals": martingale_signals,
                "martingale_passed": martingale_passed,
                "trend_strength": trend_strength,
                "peaks_4h": peaks_4h,  # Fix 100
                "peak_lookback_bars": PEAK_LOOKBACK_BARS,
                "peak_min_gap": PEAK_MIN_GAP,
                "spec_version": SPEC_VERSION,
            },
            # legacy 호환 (auto_short_at_top L226~229 fallback!)
            "rsi": martingale_signals.get("rsi_value"),
            "cci_last": breakout_snapshot.get("cci_now"),
            "signals": {
                "bb_upper_breakout": True,
                "rsi_overbought": martingale_signals.get("rsi_overbought", False),
                "macd_rising": martingale_signals.get("macd_rising", False),
                "vol_surge": martingale_signals.get("vol_surge", False),
            },
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "source": "bb_upper_breakout",
            "spec_version": SPEC_VERSION,
        }
        r.setex(alert_key, ALERT_TTL_SEC, json.dumps(alert_data, default=str))
        return True
    except Exception as e:
        logger.warning("[Fix67/alert_save] %s: %s", symbol, e)
        return False


def run_bb_upper_breakout_short() -> dict:
    """🌟 Fix 67 메인: 급등 + BB 상단 돌파 SHORT 감지 (5분 주기!)"""
    from app.core.redis_client import get_redis_client
    from app.integrations.binance.client import BinanceClient
    from app.core.crypto import decrypt_text
    from app.core.api_backoff import is_account_banned

    db: Session = SessionLocal()
    scanned = 0
    detected_symbols: list[dict] = []
    try:
        # 1. mainnet 계정!
        acc = db.execute(
            select(ExchangeAccount)
            .where(ExchangeAccount.is_testnet == False)  # noqa: E712
            .where(ExchangeAccount.is_active == True)  # noqa: E712
            .limit(1)
        ).scalar_one_or_none()
        if not acc:
            logger.info("[Fix67] mainnet 계정 없음 = skip")
            return {"error": "no_mainnet_account", "detected": 0}

        # 2. API Ban 체크!
        if is_account_banned(acc.id):
            logger.info("[Fix67] API Ban 중 = skip")
            return {"error": "api_banned", "detected": 0}

        # 3. BinanceClient!
        bc = BinanceClient(
            api_key=decrypt_text(acc.api_key_enc),
            api_secret=decrypt_text(acc.api_secret_enc),
            is_testnet=False,
        )

        # 4. Redis!
        r = get_redis_client()

        # 5. 24h ticker → 급등 후보!
        tickers = bc.get_24hr_ticker()
        if not isinstance(tickers, list):
            return {"error": "ticker_failed", "detected": 0}

        candidates: list[tuple[str, float, dict]] = []
        for t in tickers:
            sym = str(t.get("symbol", "") or "")
            if not sym.endswith("USDT"):
                continue
            try:
                chg = float(t.get("priceChangePercent", 0) or 0)
                if chg >= MIN_24H_CHANGE:  # 사장님 verbatim "급등해서"!
                    candidates.append((sym, chg, t))
            except Exception:
                continue

        # 거래대금 정렬 후 상위 MAX_SYMBOLS!
        try:
            candidates.sort(
                key=lambda x: float(x[2].get("quoteVolume", 0) or 0),
                reverse=True,
            )
        except Exception:
            pass
        candidates = candidates[:MAX_SYMBOLS]

        if not candidates:
            logger.info(
                "[Fix67] 급등 후보 (24h>=+%.0f%%) 없음",
                MIN_24H_CHANGE,
            )
            return {"scanned": 0, "detected": 0, "spec_version": SPEC_VERSION}

        # 6. 활성 심볼 skip 준비!
        try:
            from app.core.strategy_status import ACTIVE_LIKE
            from app.models.strategy_instance import StrategyInstance
            active = db.execute(
                select(StrategyInstance).where(
                    StrategyInstance.status.in_(list(ACTIVE_LIKE))
                )
            ).scalars().all()
            active_syms = {row.symbol for row in active}
        except Exception:
            active_syms = set()

        # 7. Fix 44 트렌드 강도 필터 (재사용!)
        try:
            from app.workers.pump_top_detector_worker import _check_trend_strength
        except Exception as _te:
            logger.warning("[Fix67] _check_trend_strength import 실패: %s", _te)
            _check_trend_strength = None  # type: ignore

        # 8. 심볼별 감지 loop!
        for symbol, chg_24h, _t in candidates:
            scanned += 1
            try:
                # (a) 활성 심볼 skip!
                if symbol in active_syms:
                    logger.debug("[Fix67/skip] %s: active", symbol)
                    continue

                # (b) BB 상단 돌파 감지!
                bb_ok, breakout_pct, breakout_snap = _check_bb_upper_breakout(bc, symbol)
                if not bb_ok:
                    logger.debug(
                        "[Fix67/skip] %s: BB 상단 돌파 X (pct=%.3f%%)",
                        symbol, breakout_pct,
                    )
                    continue

                # (c) 마틴게일 3중 지표!
                mart_passed, mart_signals = _check_martingale_signals(bc, symbol)
                if mart_passed < 2:  # 3중 중 2/3 이상 = 통과!
                    logger.info(
                        "[Fix67/skip] %s: 마틴게일 지표 부족 %d/3",
                        symbol, mart_passed,
                    )
                    continue

                # (d) Fix 44 트렌드 강도 판정!
                trend = "normal"
                if _check_trend_strength is not None:
                    try:
                        trend = _check_trend_strength(bc, symbol)
                    except Exception as _tex:
                        logger.warning(
                            "[Fix67/trend44] %s: %s (fail-open=normal)",
                            symbol, _tex,
                        )
                        trend = "normal"
                if trend == "extreme_bull":
                    logger.info(
                        "[Fix67/skip] %s: extreme_bull (3일 +80%%+) = SHORT 매우 위험!",
                        symbol,
                    )
                    continue
                if trend == "strong_bull":
                    logger.info(
                        "[Fix67/warn] %s: strong_bull = confidence -%.2f 감산 예정!",
                        symbol, TREND_CONFIDENCE_PENALTY,
                    )

                # (e) Fix 65 OBV gate! (SHORT 세력 매집 skip)
                try:
                    from app.services.obv_gate import check_obv_gate
                    obv_pass, obv_reason = check_obv_gate(bc, symbol, "SHORT")
                    if not obv_pass:
                        logger.info(
                            "[Fix67+Fix65/skip] %s: %s",
                            symbol, obv_reason,
                        )
                        continue
                except Exception as _obv_exc:
                    logger.warning(
                        "[Fix67+Fix65] %s obv_gate error: %s (fail-open)",
                        symbol, _obv_exc,
                    )

                # (f) Fix 66 P1 양방향 실패 blocklist!
                try:
                    from app.services.bidirectional_blocklist import is_bidirectional_blocked
                    blocked, block_reason = is_bidirectional_blocked(db, symbol)
                    if blocked:
                        logger.info(
                            "[Fix67+Fix66P1/skip] %s: %s",
                            symbol, block_reason,
                        )
                        continue
                except Exception as _bl_exc:
                    logger.warning(
                        "[Fix67+Fix66P1] %s blocklist error: %s (fail-open)",
                        symbol, _bl_exc,
                    )

                # (g) Fix 66 P2 pump_dump_regime (SHORT!)
                # 주의: 사장님 verbatim = BB 상단 돌파 = 급등 완성!
                #      pump_active OK, pump_completed_dumping 만 skip!
                try:
                    from app.services.pump_dump_regime import is_regime_blocked_for_short
                    regime_blocked, regime_reason = is_regime_blocked_for_short(bc, symbol)
                    if regime_blocked:
                        logger.info(
                            "[Fix67+Fix66P2/skip] %s: %s",
                            symbol, regime_reason,
                        )
                        continue
                except Exception as _rg_exc:
                    logger.warning(
                        "[Fix67+Fix66P2] %s regime error: %s (fail-open)",
                        symbol, _rg_exc,
                    )

                # (g2) 🌟 Fix 100 (2026-08-26 사장님!): 반복 상승 감지!
                # 사장님 verbatim:
                #   "한번올랐다 다시 내려오고 이렇게 2-3번 반복하면
                #    rsi macd obv cci 등등 고점에 이란 신호를 보고 진입"
                # = 4H 창에서 swing peak 2회+ 확인!
                # = 단일 상승 초입 오진입 완전 차단!
                # ⚠️ Fix 111b (2026-08-26): 4H → 15m 정정! (사장님 龙虾USDT 지적!)
                #   여기는 「알람 생산자」 = 진짜 병목!
                #   4H 로 세면 급등은 폭발 캔들 1~2개 = peak 0~1 → 알람 자체가 안 생김
                #   → 소비자(auto_short_at_top)를 아무리 고쳐도 진입 영원히 0건!
                #   헌법 72(급등 BB상단돌파 마틴게일)를 여기서 봉쇄하고 있었음!
                from app.services.peak_confirmation import confirm_peak
                _pk_ok, _pk_why, _pk_det = confirm_peak(bc, symbol, "SHORT")
                peaks_4h = _pk_det.get("swings_15m", 0)   # 하위 호환 (confidence/스냅샷용)
                if not _pk_ok:
                    logger.info("[Fix111b/bb_upper/skip] %s: %s | %s", symbol, _pk_why, _pk_det)
                    continue

                # (h) confidence 계산!
                # base 0.85 + 마틴게일 (3/3 시 +0.05) + BB 강도 보너스 (>=1% 시 +0.02)
                confidence = 0.85
                if mart_passed >= 3:
                    confidence += 0.05
                if breakout_pct >= 1.0:
                    confidence += 0.02
                # Fix 51 P3: strong_bull = 감산!
                if trend == "strong_bull":
                    confidence = round(confidence - TREND_CONFIDENCE_PENALTY, 4)
                confidence = round(min(confidence, 0.95), 4)
                if confidence < MIN_CONFIDENCE:
                    logger.info(
                        "[Fix67/skip] %s: confidence %.2f < %.2f",
                        symbol, confidence, MIN_CONFIDENCE,
                    )
                    continue

                # (i) Redis 알람 저장 (auto_short_at_top 자동 처리!)
                if not _save_alert_redis(
                    r, symbol, breakout_pct, mart_passed, mart_signals,
                    breakout_snap, confidence, chg_24h, trend,
                    peaks_4h=peaks_4h,
                ):
                    continue

                detected_symbols.append({
                    "symbol": symbol,
                    "side": "SHORT",
                    "confidence": confidence,
                    "change_24h": chg_24h,
                    "breakout_pct": round(breakout_pct, 3),
                    "martingale_passed": mart_passed,
                    "peaks_4h": peaks_4h,  # Fix 100
                })
                logger.warning(
                    "[Fix67/detected] %s: chg=+%.2f%% bb_breakout=%.2f%% "
                    "mart=%d/3 trend=%s conf=%.2f peaks_4h=%d",
                    symbol, chg_24h, breakout_pct, mart_passed, trend, confidence,
                    peaks_4h,
                )

                # (j) 텔레그램 알림!
                try:
                    from app.services.notification_service import NotificationService
                    _db_n = SessionLocal()
                    try:
                        NotificationService(_db_n).send_system_alert(
                            title=f"🌟 [Fix67 BB돌파] {symbol} SHORT ({confidence*100:.0f}%)",
                            body=(
                                f"🌟 사장님 신 사상 v2 SHORT!\n"
                                f"심볼: {symbol} SHORT\n"
                                f"신뢰도: {confidence*100:.0f}%\n"
                                f"24h: +{chg_24h:.1f}%\n"
                                f"BB 돌파 강도: {breakout_pct:.2f}%\n"
                                f"마틴게일 지표: {mart_passed}/3\n"
                                f"트렌드: {trend}\n"
                                f"🎯 4H 반복 상승: {peaks_4h}회 (Fix 100!)\n"
                                f"→ auto_short_at_top 자동 진입 대기!\n"
                                f"→ 실패 시 realtime_reentry 마틴게일 (300/600/1800)!"
                            ),
                        )
                    finally:
                        try:
                            _db_n.close()
                        except Exception:
                            pass
                except Exception as _te:
                    logger.warning("[Fix67] telegram 실패: %s", _te)

            except Exception as _e:
                logger.warning("[Fix67] %s 처리 실패: %s", symbol, _e)
                continue

        logger.info(
            "[Fix67] 완료: scanned=%d detected=%d spec=%s",
            scanned, len(detected_symbols), SPEC_VERSION,
        )
        return {
            "scanned": scanned,
            "detected": len(detected_symbols),
            "symbols": detected_symbols,
            "spec_version": SPEC_VERSION,
        }
    except Exception as e:
        logger.exception("[Fix67] 실행 실패: %s", e)
        return {"error": str(e), "detected": 0, "spec_version": SPEC_VERSION}
    finally:
        try:
            db.close()
        except Exception:
            pass
