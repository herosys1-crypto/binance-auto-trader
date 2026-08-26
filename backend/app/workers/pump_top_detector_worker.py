"""🎯 v223 (2026-08-23 사장님!): 15m MAIN gate + 1h/4h 보조 (역방향 skip!)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사장님 verbatim (v223, 2026-08-23):
  "15분봉이 메인 = 진짜 급격한 반전 = 1h/4h는 반대 방향만 배제!"
  "15분봉이 최상단 최하단 나올때 진입 하지만 1시간 4시간 반대면 안됨!"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

v223 로직 (신 = MAIN gate = 15m!):
  1. 15m 5개 지표 score (BB+OBV+MACD+RSI+CCI) >= 3/5 = MAIN gate!
  2. 1h 역방향 확인 = 반대 방향 score >= 3 이면 skip!
  3. 4h 역방향 확인 = 반대 방향 score >= 3 이면 skip!
  4. 통과 = 자동 진입!
  5. confidence = 0.85 + 0.03 × (score_15m - 3) = 0.85/0.88/0.91

이전 (v222) 로직:
  4H 대장 (>=4/5) + weighted 0.75+ = 진입!
  = 4H 우선 = 반전 확인 늦음 (사장님 지적!)
  = v223에서 = 15m MAIN + 1h/4h 보조로 전환!

이전 (v219) 순수 SHORT 로직:
  4H 7중 완전 정점 = MULTI_TF_ENABLED=False 시 fallback!

헌법 68 (2026-08-22 v219): 7중 정점 SHORT = 헌법 64 예외!
헌법 69 (2026-08-23 v223): 15m MAIN gate = 사장님 반전 감지 사상!
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

LOOKBACK = 20        # 최고점 판정 창 (v219 순수 로직용!)
# 🌟 v222 (2026-08-23): 다중 시간대 = 심볼당 3 kline call = 60→40 축소 (API 부담!)
# 🎯 Fix 64 (2026-08-25): 사장님 요구 = 상위 50 심볼 모니터링!
MAX_SYMBOLS = 50     # 스캔 상한 (v219 60 → v222 40 → Fix 64 50 = 사장님 요구!)
# 🎯 v220 사장님 신 사상 (2026-08-22):
# "급등락이 10 20 30 40 등등 상관없어 차트가 하락으로 시작할수 있는 타이핑에!"
# = 크기 무관! but API pre-filter 최소치 5% (완전 제거 X = 하락 종목 필터!)
MIN_24H_CHANGE = 5.0   # 15→5 = 사장님 사상 반영! (지표 중심!)
ALERT_TTL_SEC = 1800   # 알람 유효 30분!
MIN_CONFIDENCE = 0.85  # 최소 신뢰도 (남발 차단!)
# 🌟 v223 (2026-08-23): 15m MAIN gate!
V223_ENABLED = True      # False = v222 (4H 대장) fallback!
V223_MIN_SCORE_15M = 3   # 15m 최소 score (5개 중 3개 = 60%)
V223_OPP_SKIP_SCORE = 3  # 1h/4h 반대 방향 score >= 이 값 = skip!
# 하위 호환 (v222 fallback 시!)
MULTI_TF_ENABLED = True
MULTI_TF_LONG_ENABLED = True  # 사장님 "하락 시작 타이밍" = LONG 대칭!




# ============================================================
# Fix 44 (2026-08-24 사장님!): 트렌드 강도 필터
# 사장님 verbatim: "강한 상승 트렌드 (3-5일 60-85%!) = SHORT 매우 위험!"
# 사례: ENAUSDT/STXUSDT/PENGUUSDT 모두 실패!
# ============================================================
TREND_EXTREME_BULL_PCT = 80.0
TREND_STRONG_BULL_PCT = 50.0
TREND_BEAR_PCT = -20.0
TREND_CONFIDENCE_PENALTY = 0.05

# ============================================================
# 🌟 Fix 100 (2026-08-26 사장님 신 사상!): 반복 상승 감지!
# 사장님 verbatim:
#   "한번올랐다 다시 내려오고 이렇게 2-3번 반복하면
#    rsi macd obv cci 등등 고점에 이란 신호를 보고 진입"
# = 단일 상승 초입 오진입 완전 차단! 4H swing peak 2회+ 필수!
# ============================================================
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


def _check_trend_strength(bc, symbol):
    """Fix 44: 트렌드 강도 판정!"""
    try:
        kl_4h = bc.get_klines(symbol=symbol, interval="4h", limit=20)
        if not kl_4h or len(kl_4h) < 18:
            return "unknown"
        closes = [float(k[4]) for k in kl_4h]
        lows = [float(k[3]) for k in kl_4h]
        
        # 1. 3일 상승률
        close_now = closes[-1]
        close_3d_ago = closes[-18]
        if close_3d_ago <= 0: return "unknown"
        up_pct = (close_now - close_3d_ago) / close_3d_ago * 100
        
        # 2. OBV 3일 상승 (Fix 48!)
        obv_up = False
        try:
            from app.services.chart_analyzer import ChartAnalyzer
            obv = list(ChartAnalyzer.compute_obv(kl_4h) or [])
            if len(obv) >= 18:
                obv_up = float(obv[-1]) > float(obv[-18])
        except Exception: pass
        
        # 3. 조정 깊이 (BB 중단!)
        deep_pullback = False
        try:
            from app.services.bb_4h_band_analyzer import BB4HBandAnalyzer
            mid, up, lo = BB4HBandAnalyzer.bollinger(closes)
            if mid and len(mid) >= 10:
                recent_low = min(lows[-10:])
                recent_mid = float(mid[-5])
                deep_pullback = recent_low < recent_mid
        except Exception: pass
        
        # 판정!
        if up_pct > TREND_EXTREME_BULL_PCT and obv_up and not deep_pullback:
            return "extreme_bull"
        elif up_pct > TREND_STRONG_BULL_PCT and obv_up:
            return "strong_bull"
        elif up_pct < TREND_BEAR_PCT:
            return "bear"
        return "normal"
    except Exception as e:
        logger.warning(f"[Fix44] trend_strength {symbol}: {e}")
        return "unknown"


class PumpTopDetector:
    """7중 정점 감지 (사장님 실 성공 로직 v219!) + v222 다중 시간대 + v223 15m MAIN!"""

    # ==========================================================================
    # 🌟 v223 (2026-08-23): 15m MAIN gate + 1h/4h 역방향 skip!
    # 사장님 verbatim: "15분봉이 메인 = 진짜 급격한 반전 = 1h/4h는 반대 방향만 배제!"
    # ==========================================================================
    @classmethod
    def check_v223_15m_primary(cls, bc, symbol: str, side: str) -> dict:
        """v223: 15m MAIN gate + 1h/4h 역방향 확인!

        Args:
            bc: BinanceClient
            symbol: 심볼 (예: BTCUSDT)
            side: "LONG" or "SHORT"

        Returns:
            dict: {detected, side, confidence, score_15m, entry_snapshot, reason}
        """
        try:
            side_u = (side or "").upper()
            if side_u not in ("LONG", "SHORT"):
                return {"detected": False, "reason": f"invalid side={side!r}"}

            # 1. 15m MAIN score! (BB+OBV+MACD+RSI+CCI = 0~5)
            a15 = ChartAnalyzer.analyze_timeframe(bc, symbol, "15m", limit=60)
            if not a15:
                return {"detected": False, "reason": "15m 데이터 없음"}
            s15 = ChartAnalyzer.compute_reversal_score(a15, side_u)
            if s15 < V223_MIN_SCORE_15M:
                return {
                    "detected": False,
                    "reason": f"15m score {s15}/5 < {V223_MIN_SCORE_15M}",
                }

            # 2. 1h 역방향 확인 (반대 방향 강하면 skip!)
            opposite = "LONG" if side_u == "SHORT" else "SHORT"
            a1h = ChartAnalyzer.analyze_timeframe(bc, symbol, "1h", limit=80)
            s_opp_1h = 0
            if a1h:
                s_opp_1h = ChartAnalyzer.compute_reversal_score(a1h, opposite)
                if s_opp_1h >= V223_OPP_SKIP_SCORE:
                    return {
                        "detected": False,
                        "reason": f"1h 역방향 (opp {opposite} = {s_opp_1h}/5)",
                    }

            # 3. 4h 역방향 확인 (반대 방향 강하면 skip!)
            a4h = ChartAnalyzer.analyze_timeframe(bc, symbol, "4h", limit=120)
            s_opp_4h = 0
            if a4h:
                s_opp_4h = ChartAnalyzer.compute_reversal_score(a4h, opposite)
                if s_opp_4h >= V223_OPP_SKIP_SCORE:
                    return {
                        "detected": False,
                        "reason": f"4h 역방향 (opp {opposite} = {s_opp_4h}/5)",
                    }

            # 4. 통과 = 자동 진입! confidence = 0.85 + 0.03 × (score - 3)
            # score=3 → 0.85, score=4 → 0.88, score=5 → 0.91
            confidence = round(0.85 + 0.03 * (s15 - V223_MIN_SCORE_15M), 4)

            # 5. entry_snapshot = 3 시간대 학습 데이터!
            def _snap(a: dict | None, want_score_side: str) -> dict | None:
                if not a:
                    return None
                closes = a.get("closes") or []
                own_score = ChartAnalyzer.compute_reversal_score(a, want_score_side) if a else 0
                return {
                    "close": closes[-1] if closes else None,
                    "rsi_now": a.get("rsi_now"),
                    "cci_now": a.get("cci_now"),
                    "bb_up": a.get("bb_up_last"),
                    "bb_lo": a.get("bb_lo_last"),
                    "score_side": own_score,
                }

            _snap_15m = _snap(a15, side_u) or {}
            _snap_15m["score"] = s15
            entry_snapshot = {
                "15m": _snap_15m,
                "1h": _snap(a1h, side_u),
                "1h_opp_score": s_opp_1h,
                "4h": _snap(a4h, side_u),
                "4h_opp_score": s_opp_4h,
                "spec_version": "v223",
            }

            return {
                "detected": True,
                "side": side_u,
                "confidence": confidence,
                "score_15m": s15,
                "opp_score_1h": s_opp_1h,
                "opp_score_4h": s_opp_4h,
                "entry_snapshot": entry_snapshot,
            }
        except Exception as e:
            logger.warning(
                "[pump_top_v223] check_v223_15m_primary %s %s 실패: %s",
                symbol, side, e,
            )
            return {"detected": False, "reason": f"예외: {e}"}

    # ==========================================================================
    # v219 순수 SHORT 7중 정점 (MULTI_TF_ENABLED=False 시 fallback!)
    # ==========================================================================
    @classmethod
    def check_7_signals(cls, kl_4h: list, ticker_24h: dict) -> dict:
        """7중 조건 검증 (v219 순수 SHORT!).

        Args:
            kl_4h: 4시간봉 klines (Binance format!)
            ticker_24h: 24h ticker dict

        Returns:
            dict: {detected, passed, confidence, signals, close, rsi, cci_last}
        """
        try:
            closes = [float(k[4]) for k in kl_4h]
            highs = [float(k[2]) for k in kl_4h]

            mid, up, lo = BB4HBandAnalyzer.bollinger(closes)

            c1 = up[-1] is not None and closes[-1] > up[-1]

            obv = [float(x) for x in ChartAnalyzer.compute_obv(kl_4h)]
            c2 = len(obv) >= LOOKBACK and obv[-1] >= max(obv[-LOOKBACK:])

            c3 = cls._macd_hist_peak_turned(closes)

            rsi_now = BB4HBandAnalyzer._calc_rsi(closes)
            rsi_prev = BB4HBandAnalyzer._calc_rsi(closes[:-1])
            c4 = (rsi_now is not None and rsi_prev is not None
                  and rsi_now >= 70 and rsi_now < rsi_prev)

            cci = ChartAnalyzer.compute_cci(kl_4h)
            c5 = len(cci) >= 2 and cci[-1] >= 200 and cci[-1] < cci[-2]

            c6 = c2 and c3 and c4 and c5

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
            hist = [m - s for m, s in zip(macd_line[-len(signal_line):], signal_line)]
            if len(hist) < LOOKBACK:
                return False
            return hist[-2] >= max(hist[-LOOKBACK:]) and hist[-1] < hist[-2]
        except Exception:
            return False


def run_pump_top_detector() -> dict:
    """매 5분 실행 = 정점 감지 (v223 15m MAIN → v222 → v219 fallback)!"""
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
            logger.info("[pump_top_v223] API Ban 중 = skip!")
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

        usdt = [t for t in tickers if str(t.get("symbol", "")).endswith("USDT")]
        try:
            usdt.sort(key=lambda x: float(x.get("quoteVolume", 0) or 0), reverse=True)
        except Exception:
            pass
        # 🌟 v222/v223: SHORT (chg≥+5) + LONG (chg≤-5) = 대칭!
        candidates = [
            t for t in usdt[:MAX_SYMBOLS * 2]
            if abs(float(t.get("priceChangePercent", 0) or 0)) >= MIN_24H_CHANGE
        ][:MAX_SYMBOLS]

        if not candidates:
            logger.info("[pump_top_v223] 급등락 심볼 (>=+%.0f%%) 없음!", MIN_24H_CHANGE)
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

        # 7. 심볼별 정점 감지 (v223 → v222 → v219)!
        for t in candidates:
            symbol = str(t.get("symbol", ""))
            if not symbol or symbol in active_syms:
                continue
            try:
                scanned += 1
                chg24 = float(t.get("priceChangePercent", 0) or 0)
                # 🚨 Fix 64 (2026-08-25): API v219-monitoring이 pump_top:scanned:*
                #    를 읽어 "감시 심볼" 섹션에 노출 = 사장님 요구!
                #    감시 초기 상태 = 통과 여부 미정 = passed_v219=False!
                #    각 성공 경로(v223/v222/v219)에서 True로 갱신!
                _passed_this_iter = False

                # 방향 결정: chg24 부호 = 우선 후보!
                # Fix 44 적용: 트렌드 강도 판정!
                # Fix 51 P3 (2026-08-24): strong_bull = confidence 감산 실 적용!
                trend = _check_trend_strength(bc, symbol)
                if trend == "extreme_bull":
                    logger.info(f"[Fix44] {symbol} 트렌드 극강 (3일 +80%+!) = SHORT skip!")
                    continue
                if trend == "strong_bull":
                    logger.info(
                        "[Fix44/51] %s 강세 트렌드 = 신중 진입 (confidence -%.2f 감산 예정!)",
                        symbol, TREND_CONFIDENCE_PENALTY,
                    )
                
                sides_to_test = []
                if chg24 >= MIN_24H_CHANGE:
                    sides_to_test.append("SHORT")  # 급등 = 정점 SHORT!
                if chg24 <= -MIN_24H_CHANGE and MULTI_TF_LONG_ENABLED:
                    sides_to_test.append("LONG")   # 급락 = 저점 LONG!
                if not sides_to_test:
                    continue

                # 🌟 Fix 100 (2026-08-26 사장님!): 4H 반복 상승 감지!
                # 사장님 verbatim:
                #   "한번올랐다 다시 내려오고 이렇게 2-3번 반복하면
                #    rsi macd obv cci 등등 고점에 이란 신호를 보고 진입"
                # = 단일 상승 초입 오진입 완전 차단! (STARUSDT 사례!)
                # LONG/SHORT 모두 동일 로직 = swing peak 2회+ 필수
                # (반복 pump-and-dump 소진 후 진짜 반전 = LONG 저점도 동일 사상!)
                # ⚠️ Fix 111b (2026-08-26): 4H → 15m 정정! (사장님 龙虾USDT 지적!)
                #
                # 🚨 Fix 111 이 반쪽이었던 이유:
                #   Fix 111 은 「소비자」(auto_short_at_top) 의 4H 게이트만 고쳤는데,
                #   진짜 병목은 여기 「생산자」였음! 알람 자체가 안 만들어지면
                #   소비자를 아무리 고쳐도 진입은 영원히 0건!
                #   → 龙虾USDT 가 계속 차단된 진짜 이유가 바로 이 줄!
                #
                # 4H peak 의 문제: 급등은 4H 로 보면 폭발 캔들 1~2개 = peak 0~1
                #   → 사장님이 「진입해야 한다」고 지적하신 정점까지 전부 차단
                # 15m 으로 보면 계단식 2~3회 상승이 뚜렷 = 사장님 기준과 일치!
                # chg24 >= +15% 와 <= -15% 는 상호배타 → sides_to_test 는 항상 1개
                side_hint = sides_to_test[0]
                from app.services.peak_confirmation import confirm_peak
                _pk_ok, _pk_why, _pk_det = confirm_peak(bc, symbol, side_hint)
                peaks_4h = _pk_det.get("swings_15m", 0)   # 하위 호환 (로그/스냅샷용)
                if not _pk_ok:
                    logger.info(
                        "[Fix111b/pump_top/skip] %s (%s): %s | %s",
                        symbol, side_hint, _pk_why, _pk_det,
                    )
                    continue

                for side in sides_to_test:
                    # ========================================================
                    # 🌟 v223: 15m MAIN gate + 1h/4h 역방향 skip! (default!)
                    # ========================================================
                    if V223_ENABLED:
                        v = PumpTopDetector.check_v223_15m_primary(bc, symbol, side)
                        if not v.get("detected"):
                            # verbose 로깅 (뭐가 걸렸는지 = 사장님 디버깅!)
                            logger.debug(
                                "[pump_top_v223] skip %s %s: %s",
                                symbol, side, v.get("reason"),
                            )
                            continue
                        conf = v.get("confidence", 0)
                        # Fix 51 P3: strong_bull = confidence 감산 실 적용!
                        if trend == "strong_bull":
                            _conf_before = conf
                            conf = round(conf - TREND_CONFIDENCE_PENALTY, 4)
                            logger.info(
                                "[Fix44/51] %s strong_bull v223 = confidence %.2f -> %.2f (신중 진입!)",
                                symbol, _conf_before, conf,
                            )
                        if conf < MIN_CONFIDENCE:
                            if trend == "strong_bull":
                                logger.info(
                                    "[Fix44/51] %s v223 confidence 부족 (%.2f < %.2f) = skip",
                                    symbol, conf, MIN_CONFIDENCE,
                                )
                            continue

                        alert_key = f"pump_top:alert:{symbol}:{side}"
                        # Fix 100: entry_snapshot에도 peaks_4h 병합 (학습!)
                        _es_v223 = dict(v.get("entry_snapshot") or {})
                        _es_v223["peaks_4h"] = peaks_4h
                        _es_v223["peak_lookback_bars"] = PEAK_LOOKBACK_BARS
                        _es_v223["peak_min_gap"] = PEAK_MIN_GAP
                        alert_data = {
                            "symbol": symbol,
                            "side": side,
                            "confidence": conf,
                            "trend_strength": trend,
                            "trend_penalty_applied": (trend == "strong_bull"),
                            "score_15m": v.get("score_15m"),
                            "opp_score_1h": v.get("opp_score_1h"),
                            "opp_score_4h": v.get("opp_score_4h"),
                            "peaks_4h": peaks_4h,  # Fix 100
                            "entry_snapshot": _es_v223,
                            "change_24h": chg24,
                            "detected_at": datetime.now(timezone.utc).isoformat(),
                            "source": "sajangnim_15m_main_v223",
                            "spec_version": "pump_top_detector_v3_fix100_multi_peak_2026-08-26",
                        }
                        r.setex(alert_key, ALERT_TTL_SEC, json.dumps(alert_data, default=str))
                        _passed_this_iter = True  # Fix 64: 감시 마커 pass!
                        detected_symbols.append({
                            "symbol": symbol, "side": side,
                            "confidence": conf, "change_24h": chg24,
                            "score_15m": v.get("score_15m"),
                        })

                        logger.warning(
                            "[pump_top_v223+Fix100] 🎯 %s %s conf=%.2f 15m=%d/5 24h=%+.1f%% "
                            "opp(1h=%d,4h=%d) peaks_4h=%d",
                            symbol, side, conf, v.get("score_15m", 0),
                            chg24, v.get("opp_score_1h", 0), v.get("opp_score_4h", 0),
                            peaks_4h,
                        )

                        # 텔레그램!
                        try:
                            from app.services.notification_service import NotificationService
                            _db_n = SessionLocal()
                            _ns = NotificationService(_db_n)
                            _body = (
                                f"🎯 사장님 반전 감지! (v223 + Fix 100)\n"
                                f"심볼: {symbol} {side}\n"
                                f"신뢰도: {conf*100:.0f}%\n"
                                f"15m score: {v.get('score_15m')}/5 (MAIN)\n"
                                f"1h/4h 역방향: {v.get('opp_score_1h')}/{v.get('opp_score_4h')}\n"
                                f"🎯 4H 반복 상승: {peaks_4h}회 (Fix 100!)\n"
                                f"24h: {chg24:+.1f}%\n"
                                f"15m MAIN + 반복 상승 확인! 자동 {side} 진입 대기!"
                            )
                            _ns.send_system_alert(
                                title=f"🎯 [v223 반전] {symbol} {side} ({conf*100:.0f}%)",
                                body=_body,
                            )
                            try:
                                _db_n.close()
                            except Exception:
                                pass
                        except Exception as _te:
                            logger.warning("[pump_top_v223] telegram 실패: %s", _te)
                        continue  # 이 side 완료 → 다음 side!

                    # ========================================================
                    # v222 fallback: 4H 대장 (>=4/5) + weighted 0.75+!
                    # ========================================================
                    if MULTI_TF_ENABLED:
                        mtf = ChartAnalyzer.multi_tf_entry_score(bc, symbol, side)
                        if not mtf.get("enter"):
                            continue
                        conf = mtf.get("confidence", 0)
                        # Fix 51 P3: strong_bull = confidence 감산 실 적용!
                        if trend == "strong_bull":
                            _conf_before = conf
                            conf = round(conf - TREND_CONFIDENCE_PENALTY, 4)
                            logger.info(
                                "[Fix44/51] %s strong_bull v222 = confidence %.2f -> %.2f (신중 진입!)",
                                symbol, _conf_before, conf,
                            )
                        if conf < MIN_CONFIDENCE:
                            if trend == "strong_bull":
                                logger.info(
                                    "[Fix44/51] %s v222 confidence 부족 (%.2f < %.2f) = skip",
                                    symbol, conf, MIN_CONFIDENCE,
                                )
                            continue
                        alert_key = f"pump_top:alert:{symbol}:{side}"
                        alert_data = {
                            "symbol": symbol, "side": side, "confidence": conf,
                            "trend_strength": trend,
                            "trend_penalty_applied": (trend == "strong_bull"),
                            "weighted": mtf.get("weighted"),
                            "score_4h": mtf.get("score_4h"),
                            "score_1h": mtf.get("score_1h"),
                            "score_15m": mtf.get("score_15m"),
                            "peaks_4h": peaks_4h,  # Fix 100
                            "change_24h": chg24,
                            "detected_at": datetime.now(timezone.utc).isoformat(),
                            "source": "sajangnim_mtf_v222",
                            "spec_version": "pump_top_detector_v3_fix100_multi_peak_2026-08-26",
                        }
                        r.setex(alert_key, ALERT_TTL_SEC, json.dumps(alert_data))
                        _passed_this_iter = True  # Fix 64: 감시 마커 pass!
                        detected_symbols.append({
                            "symbol": symbol, "side": side,
                            "confidence": conf, "change_24h": chg24,
                            "weighted": mtf.get("weighted"),
                        })
                        logger.warning(
                            "[pump_top_v222] 🎯 %s %s conf=%.2f 24h=%+.1f%%",
                            symbol, side, conf, chg24,
                        )
                        continue

                    # ========================================================
                    # v219 fallback: SHORT만 = 7중 완전 정점!
                    # ========================================================
                    if side != "SHORT":
                        continue
                    kl = bc.get_klines(symbol=symbol, interval="4h", limit=120)
                    if not isinstance(kl, list) or len(kl) < 60:
                        continue
                    result = PumpTopDetector.check_7_signals(kl, t)
                    if not result.get("detected"):
                        continue
                    conf = result.get("confidence", 0)
                    # Fix 51 P3: strong_bull = confidence 감산 실 적용!
                    if trend == "strong_bull":
                        _conf_before = conf
                        conf = round(conf - TREND_CONFIDENCE_PENALTY, 4)
                        logger.info(
                            "[Fix44/51] %s strong_bull v219 = confidence %.2f -> %.2f (신중 진입!)",
                            symbol, _conf_before, conf,
                        )
                    if conf < MIN_CONFIDENCE:
                        if trend == "strong_bull":
                            logger.info(
                                "[Fix44/51] %s v219 confidence 부족 (%.2f < %.2f) = skip",
                                symbol, conf, MIN_CONFIDENCE,
                            )
                        continue
                    alert_key = f"pump_top:alert:{symbol}:SHORT"
                    alert_data = {
                        "symbol": symbol, "side": "SHORT",
                        "confidence": conf,
                        "trend_strength": trend,
                        "trend_penalty_applied": (trend == "strong_bull"),
                        "signals": result["signals"],
                        "close": result["close"], "rsi": result["rsi"],
                        "cci_last": result["cci_last"],
                        "peaks_4h": peaks_4h,  # Fix 100
                        "change_24h": result["change_24h"],
                        "detected_at": datetime.now(timezone.utc).isoformat(),
                        "source": "sajangnim_top_v219",
                        "spec_version": "pump_top_detector_v3_fix100_multi_peak_2026-08-26",
                    }
                    r.setex(alert_key, ALERT_TTL_SEC, json.dumps(alert_data))
                    _passed_this_iter = True  # Fix 64: 감시 마커 pass!
                    detected_symbols.append({
                        "symbol": symbol, "side": "SHORT",
                        "confidence": conf, "change_24h": chg24,
                    })

                # 🚨 Fix 64 (2026-08-25): 감시 마커 (통과 여부 관계없이 스캔 완료 심볼!)
                #    v219-monitoring API가 `pump_top:scanned:*` 스캔 → UI "감시 심볼"!
                try:
                    _scan_key = f"pump_top:scanned:{symbol}"
                    _scan_data = {
                        "symbol": symbol,
                        "change_24h": chg24,
                        "trend": trend,
                        "peaks_4h": peaks_4h,  # Fix 100 = 반복 상승 횟수!
                        "passed_v219": bool(_passed_this_iter),
                        "sides_tested": sides_to_test,
                        "scanned_at": datetime.now(timezone.utc).isoformat(),
                    }
                    r.setex(_scan_key, ALERT_TTL_SEC, json.dumps(_scan_data, default=str))
                except Exception as _se:
                    logger.debug("[pump_top_v223] scanned marker 저장 skip %s: %s", symbol, _se)

            except Exception as e:
                logger.warning("[pump_top_v223] %s 스캔 실패: %s", symbol, e)
                continue

        logger.info(
            "[pump_top_v223] 완료: scanned=%d detected=%d",
            scanned, len(detected_symbols),
        )
        return {
            "scanned": scanned,
            "detected": len(detected_symbols),
            "symbols": detected_symbols,
            "spec_version": "v223" if V223_ENABLED else "v222",
        }
    except Exception as e:
        logger.exception("[pump_top_v223] 실행 실패: %s", e)
        return {"error": str(e), "detected": 0}
    finally:
        db.close()
