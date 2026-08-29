"""📉 Fix 50 v2 (2026-08-24 사장님 신 사상!): 2-패턴 LONG 감지 (A=상승 지속, B=조정 후 반전!)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Fix 50 v2 사장님 verbatim:
  "최근 1일 -2일 10% 전후 상승하는 심볼을 모니터링해서 상승할 심볼에 롱으로 진입하고
   나머진 급상승후 큰조정에서 모니터링중 심볼중에 다시 상승할것 같으면 롱으로 진입"

패턴 A (상승 지속 진입): 24h +5% ~ +15%
  = OBV 지속 상승 + MACD Hist 양수 + RSI 30~60 (과열 아님) → 추세 지속 LONG!
패턴 B (조정 후 반전 진입): 24h -15% ~ 0%
  = OBV 반전 상승 + MACD Hist 저점 반전 + RSI 40 회복 → 반전 저점 LONG!

기존 사상 (LONG 대칭!):
  "급락 종목 저점 = OBV 반전 상승이 나올 때 저점 LONG!"
  "OBV 반전 없으면 = 급락 지속 = 반대매매 금지 (헌법 64)!"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

v223 대칭 로직 (SHORT의 정점 → LONG의 저점):
  1. 15m 5개 지표 score (BB+OBV+MACD+RSI+CCI) >= 3/5 = MAIN gate!
  2. 1h 역방향 (SHORT) 확인 = score >= 3 이면 skip!
  3. 4h 역방향 (SHORT) 확인 = score >= 3 이면 skip!
  4. 통과 = 자동 LONG 진입!
  5. confidence = 0.85 + 0.03 × (score_15m - 3)

v219 대칭 fallback (7중 완전 저점):
  4H BB 최하단 이탈 / OBV 최저점→반전 상승 / MACD Hist 저점→반전 /
  RSI ≤ 30 / CCI ≤ -100 / all_bottom / 24h 변동률 ≤ -10%
  = OBV 반전 없으면 무조건 skip (사장님 verbatim!)

헌법 68 대칭 (2026-08-24): 7중 저점 LONG = 헌법 64 (급락 반대매매 금지) 예외!
  단, OBV 반전 상승 확인 필수 = 급락 지속 중이면 진입 X!
헌법 69 대칭 (2026-08-24): 15m MAIN gate = 사장님 반전 감지 사상!
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

LOOKBACK = 20        # 최저점 판정 창 (v219 순수 대칭 로직용!)
# 🌟 v222 대칭 (2026-08-24): 다중 시간대 = 심볼당 3 kline call = API 부담 축소!
MAX_SYMBOLS = 50     # Fix 64 = 하위 50 심볼 모니터링!
# 🎯 사장님 사상 대칭 (2026-08-24):
# 급락 종목 = 반대매매 위험 크므로 (헌법 64!) LONG 최소 -10% 요구 (SHORT +5%보다 엄격)
MIN_24H_CHANGE = 10.0  # LONG용 = 24h ≤ -10% (사장님 verbatim 완화 요구!)
ALERT_TTL_SEC = 1800   # 알람 유효 30분!
MIN_CONFIDENCE = 0.85  # 최소 신뢰도 (남발 차단!)
# 🌟 v223 대칭: 15m MAIN gate!
V223_ENABLED = True      # False = v219 대칭 (7중 저점) fallback!
V223_MIN_SCORE_15M = 3   # 15m 최소 score (5개 중 3개 = 60%)
V223_OPP_SKIP_SCORE = 3  # 1h/4h 역방향 (SHORT) score >= 이 값 = skip!

# 🌟 Fix 44 대칭 (2026-08-24): 트렌드 강도 필터 (LONG 방향)!
# 사장님 사상: "강한 하락 트렌드 (3-5일 -60~-85%!) = LONG 매우 위험!"
# = 낙엽 잡기 (falling knife) 방지!
TREND_STRENGTH_ENABLED = True   # False = filter 완전 비활성 (v223 대칭 순수)
TREND_EXTREME_BEAR_PCT = -80.0  # 3일(72h) 하락률 이 이하 = extreme_bear (LONG 금지!)
TREND_STRONG_BEAR_PCT = -50.0   # 3일 이 이하 (+ OBV 하락) = strong_bear (신중!)
TREND_BULL_PCT = 20.0           # 3일 이 이상 = bull (LONG 유리, SHORT 신중!)
TREND_EXTREME_BULL_PCT_3D = 30.0  # 🌟 Fix 50 v2: 3일 +30% 이상 = extreme_bull (LONG skip, 정점 위험!)
TREND_CONFIDENCE_PENALTY = 0.05  # strong_bear LONG confidence 감소량!

# 🌟 Fix 87 P0 (2026-08-25 사장님 = 헌법 78!):
# 사장님 verbatim: "전략에 들어가는건 당일 급등락한 심볼만 거래하는거야"
# → LONG = 급락 (-3% 이하)만! 상승 = SHORT 대칭 처리!
# 패턴 A (+5%~+15% 상승 지속) = 헌법 78 위반 = 완전 skip!
# 패턴 B 상한 = 0 → -3.0 (더 확실한 급락!)
SPEC_VERSION = "long_bottom_detector_v3_fix87_dump_only_2026-08-25"
PATTERN_A_MIN_CHG = 5.0     # 패턴 A: 24h 최소 +5% (Fix 87 = 진입 skip!)
PATTERN_A_MAX_CHG = 15.0    # 패턴 A: 24h 최대 +15% (Fix 87 = 진입 skip!)
# 🚨 Fix 225 (2026-08-30) — **Fix 220 을 되돌린다.**
#
#   사장님 verbatim:
#     "큰상승후 큰하락해서 **원점을 간 심볼은 다시 상승하는 심볼을 찾기는 힘들어**.
#      그래서 롱은 **큰상승을 시작한 심볼**을 모니터링해서 포지션에 들어가는게 매우 유리해"
#
#   Fix 220 은 「하락 50위도 감시」 지시를 받아 하한을 -100% 로 열었다. 그런데 그
#   지시는 **SHORT 후보 확대**를 뜻했고, 이 함수는 **LONG 후보**를 고른다.
#   결과적으로 원점까지 무너진 종목을 LONG 대상에 더 많이 담게 됐다 =
#   사장님이 "다시 상승하기 힘들다"고 지목한 바로 그 종목들이다.
#
#   ⚠️ -15% 복원은 **임시 방어**다. 24h 변동률만으로는 「추세 중 조정」과
#      「원점 회귀」를 구별할 수 없다. 진짜 판정은 되돌림 비율이어야 한다:
#          되돌림 = (고점 - 현재가) / (고점 - 상승 시작가)
#          >= 70~80% → 원점 회귀 = LONG 금지
#          30~60%    → 추세 중 조정 = LONG 자리
#      이건 기획서에 설계로 넣고 별도 구현한다.
PATTERN_B_MIN_CHG = -15.0   # 패턴 B: 24h 최소 -15%  (Fix 225 = Fix 220 되돌림)
PATTERN_B_MAX_CHG = -3.0    # 🌟 Fix 87: 0 → -3.0 (급락 확실!)


def _check_trend_strength_long(bc, symbol: str) -> str:
    """트렌드 강도 판정 (Fix 44 대칭 = LONG 방향!).

    4H 봉 20개 (약 3.3일) 기준으로 판정:
      - "extreme_bear": 3일 -80% 이하 + OBV 3일 하락 + 반등 얕음 → LONG 절대 금지!
      - "strong_bear": 3일 -50%~-80% + OBV 3일 하락 → LONG 매우 신중 (confidence 감소)!
      - "extreme_bull": 3일 +30% 이상 (Fix 50 v2!) → LONG skip! (이미 정점 = 추격 매수 위험!)
      - "bull": 3일 +20%~+30% → LONG 유리 (SHORT 신중!)
      - "normal": 그 외
      - "unknown": 데이터 부족/예외

    Args:
        bc: BinanceClient
        symbol: 심볼 (예: BTCUSDT)

    Returns:
        str: 판정 라벨
    """
    try:
        kl_4h = bc.get_klines(symbol=symbol, interval="4h", limit=20)
        if not isinstance(kl_4h, list) or len(kl_4h) < 18:
            return "unknown"

        closes = [float(k[4]) for k in kl_4h]
        highs = [float(k[2]) for k in kl_4h]

        # 1. 3일 하락률 (4H × 18 = 72h!)
        close_now = closes[-1]
        close_3d_ago = closes[-18]
        if close_3d_ago <= 0:
            return "unknown"
        chg_pct = (close_now - close_3d_ago) / close_3d_ago * 100.0

        # 2. OBV 지속 하락 확인 (SHORT의 상승 확인 대칭!)
        obv_down = False
        try:
            obv = list(ChartAnalyzer.compute_obv(kl_4h) or [])
            if len(obv) >= 18:
                obv_now = float(obv[-1])
                obv_3d_ago = float(obv[-18])
                obv_down = obv_now < obv_3d_ago  # 3일간 OBV 하락!
        except Exception:
            obv_down = False

        # 3. 반등 얕음 판별 (BB 중단 이상 도달 여부 = 얕은 반등 = 하락 지속!)
        shallow_bounce = False
        try:
            mid, _up, _lo = BB4HBandAnalyzer.bollinger(closes)
            if mid and len(mid) >= 10:
                recent_high = max(highs[-10:])
                mid_ref = mid[-5] if len(mid) >= 5 else None
                if mid_ref is not None:
                    recent_mid = float(mid_ref)
                    shallow_bounce = recent_high < recent_mid  # 고점이 BB 중단 이하!
        except Exception:
            shallow_bounce = False

        # 판정! (Fix 50 v2: extreme_bull 추가 = 3일 +30% 이상 정점 추격 방지!)
        if chg_pct <= TREND_EXTREME_BEAR_PCT and obv_down and shallow_bounce:
            return "extreme_bear"  # LONG 절대 금지!
        elif chg_pct <= TREND_STRONG_BEAR_PCT and obv_down:
            return "strong_bear"   # LONG 매우 신중!
        elif chg_pct >= TREND_EXTREME_BULL_PCT_3D:
            return "extreme_bull"  # 🌟 Fix 50 v2: 3일 +30%↑ = 정점 위험 → LONG skip!
        elif chg_pct >= TREND_BULL_PCT:
            return "bull"          # LONG 유리!
        else:
            return "normal"
    except Exception as e:
        logger.warning("[Fix44/trend_strength_long] %s 실패: %s", symbol, e)
        return "unknown"


class LongBottomDetector:
    """7중 저점 감지 (pump_top의 완전 대칭!) + v223 15m MAIN + v219 대칭 fallback!"""

    # ==========================================================================
    # 🌟 v223 대칭: 15m MAIN gate + 1h/4h 역방향 (SHORT) skip!
    # ==========================================================================
    @classmethod
    def check_v223_15m_primary(cls, bc, symbol: str) -> dict:
        """v223 대칭: 15m MAIN gate + 1h/4h 역방향 (SHORT) 확인 (LONG 전용!)!

        Args:
            bc: BinanceClient
            symbol: 심볼 (예: BTCUSDT)

        Returns:
            dict: {detected, side, confidence, score_15m, entry_snapshot, reason}
        """
        try:
            side_u = "LONG"  # 이 detector = LONG 전용!

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

            # 2. 1h 역방향 (SHORT) 확인 = 반대 방향 강하면 skip!
            opposite = "SHORT"
            a1h = ChartAnalyzer.analyze_timeframe(bc, symbol, "1h", limit=80)
            s_opp_1h = 0
            if a1h:
                s_opp_1h = ChartAnalyzer.compute_reversal_score(a1h, opposite)
                if s_opp_1h >= V223_OPP_SKIP_SCORE:
                    return {
                        "detected": False,
                        "reason": f"1h 역방향 (opp {opposite} = {s_opp_1h}/5)",
                    }

            # 3. 4h 역방향 (SHORT) 확인 = 반대 방향 강하면 skip!
            a4h = ChartAnalyzer.analyze_timeframe(bc, symbol, "4h", limit=120)
            s_opp_4h = 0
            if a4h:
                s_opp_4h = ChartAnalyzer.compute_reversal_score(a4h, opposite)
                if s_opp_4h >= V223_OPP_SKIP_SCORE:
                    return {
                        "detected": False,
                        "reason": f"4h 역방향 (opp {opposite} = {s_opp_4h}/5)",
                    }

            # 4. 통과 = 자동 LONG 진입! confidence = 0.85 + 0.03 × (score - 3)
            confidence = round(0.85 + 0.03 * (s15 - V223_MIN_SCORE_15M), 4)

            # 5. entry_snapshot = 3 시간대 학습 데이터!
            def _snap(a: dict | None, want_score_side: str) -> dict | None:
                if not a:
                    return None
                closes = a.get("closes") or []
                own_score = (
                    ChartAnalyzer.compute_reversal_score(a, want_score_side) if a else 0
                )
                # 🚨 Fix 228: OBV 방향을 -1~+1 로 남긴다 (obv_metrics = 단일 출처).
                #   사장님 "obv가 하락하지 않으면 결국은 obv 방향으로 간다" 의 측정치.
                #   여기서 안 남기면 하류(unified_15m_entry)가 None 으로 기록하게 된다.
                from app.services.obv_metrics import obv_direction_ratio
                return {
                    "close": closes[-1] if closes else None,
                    "rsi_now": a.get("rsi_now"),
                    "cci_now": a.get("cci_now"),
                    "bb_up": a.get("bb_up_last"),
                    "bb_mid": a.get("bb_mid_last"),
                    "bb_lo": a.get("bb_lo_last"),
                    "obv_dir": obv_direction_ratio(a.get("obv"), a.get("volumes")),
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
                "spec_version": "v223_long",
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
                "[LONG bottom detector v223] check_v223_15m_primary %s 실패: %s",
                symbol, e,
            )
            return {"detected": False, "reason": f"예외: {e}"}

    # ==========================================================================
    # v219 대칭 순수 LONG 7중 저점 (V223_ENABLED=False 시 fallback!)
    # 🚨 사장님 verbatim: OBV 반전 확인 통과 못하면 나머지 True여도 skip!
    # ==========================================================================
    @classmethod
    def check_7_signals(cls, kl_4h: list, ticker_24h: dict) -> dict:
        """7중 조건 검증 (v219 대칭 = 순수 LONG 저점!).

        Args:
            kl_4h: 4시간봉 klines (Binance format!)
            ticker_24h: 24h ticker dict

        Returns:
            dict: {detected, passed, confidence, signals, close, rsi, cci_last}
        """
        try:
            closes = [float(k[4]) for k in kl_4h]
            lows = [float(k[3]) for k in kl_4h]

            mid, up, lo = BB4HBandAnalyzer.bollinger(closes)

            # c1: 4H BB 최하단 접촉/이탈!
            c1 = lo[-1] is not None and closes[-1] < lo[-1]

            # c2: OBV 최저점 → 반전 상승 시작! (SHORT의 최고점→하락 대칭!)
            obv = [float(x) for x in ChartAnalyzer.compute_obv(kl_4h)]
            c2 = False
            if len(obv) >= LOOKBACK and len(obv) >= 2:
                obv_prev_was_min = obv[-2] <= min(obv[-LOOKBACK:])
                obv_now_rising = obv[-1] > obv[-2]
                c2 = obv_prev_was_min and obv_now_rising  # 최저점 후 반전 상승!

            # 🚨 사장님 verbatim: OBV 반전 없으면 = 나머지 True여도 skip!
            if not c2:
                return {
                    "detected": False,
                    "passed": 0,
                    "confidence": 0.0,
                    "signals": {
                        "bb_lower": c1, "obv_bottom": c2, "macd_bottom": False,
                        "rsi_bottom": False, "cci_bottom": False,
                        "all_bottom": False, "dump": False,
                    },
                    "close": closes[-1] if closes else None,
                    "obv_skip": True,  # OBV 반전 미확인으로 skip!
                }

            # c3: MACD Hist 저점 후 상승 반전!
            c3 = cls._macd_hist_bottom_turned(closes)

            # c4: RSI ≤ 30 + 상승 반전!
            rsi_now = BB4HBandAnalyzer._calc_rsi(closes)
            rsi_prev = BB4HBandAnalyzer._calc_rsi(closes[:-1])
            c4 = (rsi_now is not None and rsi_prev is not None
                  and rsi_now <= 30 and rsi_now > rsi_prev)

            # c5: CCI ≤ -100 + 상승 반전!
            cci = ChartAnalyzer.compute_cci(kl_4h)
            c5 = len(cci) >= 2 and cci[-1] <= -100 and cci[-1] > cci[-2]

            # c6: 모든 지표 저점 정렬!
            c6 = c2 and c3 and c4 and c5

            # c7: 24h 변동률 ≤ -10% (LONG 완화!) + 최저점!
            chg24 = float(ticker_24h.get("priceChangePercent", 0) or 0)
            c7 = (len(lows) >= LOOKBACK
                  and lows[-1] <= min(lows[-LOOKBACK:]))

            passed = sum([c1, c2, c3, c4, c5, c6, c7])
            confidence = 0.85 + 0.02 * (passed - 5) if passed >= 5 else 0.0

            return {
                "detected": passed == 7,
                "passed": passed,
                "confidence": round(confidence, 4),
                "signals": {
                    "bb_lower": c1, "obv_bottom": c2, "macd_bottom": c3,
                    "rsi_bottom": c4, "cci_bottom": c5,
                    "all_bottom": c6, "dump": c7,
                },
                "close": closes[-1],
                "rsi": rsi_now,
                "cci_last": cci[-1] if cci else None,
                "change_24h": chg24,
            }
        except Exception as e:
            logger.warning("[LONG bottom detector v219] check_7_signals 실패: %s", e)
            return {"detected": False, "passed": 0, "confidence": 0.0}

    @staticmethod
    def _macd_hist_bottom_turned(closes: list[float]) -> bool:
        """MACD 히스토그램 최저점 + 상승 반전 감지 (SHRT의 peak_turned 대칭!)"""
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
            # 대칭: 이전이 최저 + 지금이 반전 상승!
            return hist[-2] <= min(hist[-LOOKBACK:]) and hist[-1] > hist[-2]
        except Exception:
            return False


def _classify_pattern(chg24: float) -> str | None:
    """🌟 Fix 87 (2026-08-25 사장님 = 헌법 78!):
    "전략에 들어가는건 당일 급등락한 심볼만 거래하는거야"
    → LONG = 급락만! 패턴 A (상승) = 완전 skip!

    Returns:
        "B" = 급락 후 반전 진입 (-15%~-3%) 만 유효!
        None = skip! (패턴 A 포함!)
    """
    # 🌟 Fix 87: 패턴 A (+5%~+15% 상승) = 헌법 78 위반 = skip!
    #   ※ PATTERN_A_MIN_CHG/MAX_CHG 상수는 유지 (다른 곳 참조/로그 표현) but 진입 X!
    if PATTERN_A_MIN_CHG <= chg24 <= PATTERN_A_MAX_CHG:
        return None  # skip! (헌법 78 = LONG = 급락만!)
    if PATTERN_B_MIN_CHG <= chg24 <= PATTERN_B_MAX_CHG:
        return "B"
    return None


def _check_pattern_signals(bc, symbol: str, pattern: str) -> dict:
    """🌟 Fix 50 v2: 패턴별 세부 신호 검증 (사장님 신 사상 = 패턴별 지표 다름!).

    패턴 A (상승 지속) = OBV 지속 상승 + MACD Hist 양수 + RSI 30~60 (과열 아님)!
    패턴 B (반전 저점) = OBV 반전 상승 + MACD Hist 저점 반전 + RSI 40 회복!

    Returns:
        {"ok": bool, "reason": str, "signals": {...}}
    """
    try:
        # 4H 봉 60개 = 모든 지표 계산 충분!
        kl = bc.get_klines(symbol=symbol, interval="4h", limit=60)
        if not isinstance(kl, list) or len(kl) < 35:
            return {"ok": False, "reason": "4h 데이터 부족", "signals": {}}

        closes = [float(k[4]) for k in kl]

        # OBV
        obv = [float(x) for x in (ChartAnalyzer.compute_obv(kl) or [])]
        # RSI
        rsi_now = BB4HBandAnalyzer._calc_rsi(closes)
        rsi_prev = BB4HBandAnalyzer._calc_rsi(closes[:-1])
        # MACD Hist (마지막 값 + 이전 값)
        macd_hist_last = None
        macd_hist_prev = None
        try:
            ema12 = BB4HBandAnalyzer._calc_ema(closes, 12)
            ema26 = BB4HBandAnalyzer._calc_ema(closes, 26)
            offset = 26 - 12
            macd_line = [a - b for a, b in zip(ema12[offset:], ema26)]
            signal_line = BB4HBandAnalyzer._calc_ema(macd_line, 9)
            if signal_line and len(signal_line) >= 2:
                hist = [m - s for m, s in zip(macd_line[-len(signal_line):], signal_line)]
                if len(hist) >= 2:
                    macd_hist_last = hist[-1]
                    macd_hist_prev = hist[-2]
        except Exception:
            pass

        if pattern == "A":
            # 패턴 A = 상승 지속!
            # 1. OBV 지속 상승 (최근 5봉 vs 그 이전 5봉)
            obv_rising = False
            if len(obv) >= 10:
                obv_rising = obv[-1] > obv[-6]  # 5봉 전보다 상승!
            # 2. MACD Hist 양수 (추세 강함!)
            macd_positive = macd_hist_last is not None and macd_hist_last > 0
            # 3. RSI 30~60 (과열 아님!)
            rsi_ok = rsi_now is not None and 30 <= rsi_now <= 60

            ok = obv_rising and macd_positive and rsi_ok
            reason = (
                f"A: obv_rising={obv_rising} macd+={macd_positive} rsi_ok={rsi_ok} "
                f"(rsi={rsi_now})"
            )
            return {
                "ok": ok,
                "reason": reason,
                "signals": {
                    "obv_rising": obv_rising,
                    "macd_positive": macd_positive,
                    "rsi_ok": rsi_ok,
                    "rsi": rsi_now,
                    "macd_hist": macd_hist_last,
                },
            }
        elif pattern == "B":
            # 패턴 B = 조정 후 반전!
            # 1. OBV 반전 상승 (직전 저점 → 이번 봉 반등)
            obv_reversal = False
            if len(obv) >= LOOKBACK and len(obv) >= 2:
                obv_prev_was_min = obv[-2] <= min(obv[-LOOKBACK:])
                obv_now_rising = obv[-1] > obv[-2]
                obv_reversal = obv_prev_was_min and obv_now_rising
            # 2. MACD Hist 저점 반전 (직전 최저 → 이번 반전 상승)
            macd_reversal = LongBottomDetector._macd_hist_bottom_turned(closes)
            # 3. RSI 40 회복 (30에서 반등 시작!)
            rsi_recover = (
                rsi_now is not None and rsi_prev is not None
                and rsi_now >= 40 and rsi_now > rsi_prev
            )

            ok = obv_reversal and macd_reversal and rsi_recover
            reason = (
                f"B: obv_rev={obv_reversal} macd_rev={macd_reversal} "
                f"rsi_recover={rsi_recover} (rsi={rsi_now})"
            )
            return {
                "ok": ok,
                "reason": reason,
                "signals": {
                    "obv_reversal": obv_reversal,
                    "macd_reversal": macd_reversal,
                    "rsi_recover": rsi_recover,
                    "rsi": rsi_now,
                    "macd_hist": macd_hist_last,
                },
            }
        else:
            return {"ok": False, "reason": f"unknown pattern {pattern}", "signals": {}}
    except Exception as e:
        logger.warning("[Fix50v2/_check_pattern_signals] %s pattern=%s 실패: %s",
                       symbol, pattern, e)
        return {"ok": False, "reason": f"예외: {e}", "signals": {}}


def run_long_bottom_detector() -> dict:
    """매 5분 실행 = 저점 LONG 감지 (v223 15m MAIN → v219 대칭 fallback)!

    pump_top_detector와 완전 대칭 = LONG 전용!
    """
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
            logger.info("[LONG bottom detector v223] API Ban 중 = skip!")
            return {"error": "API Ban 중!", "detected": 0}

        # 3. BinanceClient!
        from app.integrations.binance.client import BinanceClient
        from app.core.crypto import decrypt_text
        bc = BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=False,
        )

        # 4. 상위 심볼 (거래대금!) 중 급락 종목만!
        tickers = bc.get_24hr_ticker()
        if not isinstance(tickers, list):
            return {"error": "ticker 실패!", "detected": 0}

        # ═══════════════════════════════════════════════════════════════════
        # 🚨 Fix 217 (2026-08-30 사장님): "당일 상승 50위와 하락 50위로 해줘"
        #   옛 코드는 **거래대금(quoteVolume)** 순으로 상위 150개를 자른 뒤 그 안에서
        #   패턴을 골랐다 = 거래대금 작은 급등락 종목은 감시망 밖이었다.
        #   pump_top_detector 와 **같은 함수**를 쓴다 (헌법 101 — 한쪽만 고치면 어긋난다).
        # ═══════════════════════════════════════════════════════════════════
        from app.services.market_movers import MIN_QUOTE_VOLUME, rank_map
        _ranked = rank_map(tickers, MAX_SYMBOLS)

        # 🌟 Fix 50 v2 (2026-08-24 사장님 verbatim!):
        # "1-2일 10% 전후 상승" (패턴 A: +5%~+15%) OR
        # "급상승후 큰조정" (패턴 B: -15%~0%)
        candidates = [
            t for (t, _d, _r) in _ranked
            if _classify_pattern(float(t.get("priceChangePercent", 0) or 0)) is not None
        ]
        _usdt_n = sum(
            1 for t in tickers if str(t.get("symbol") or "").endswith("USDT")
        )
        logger.info(
            "[Fix50v2/long] 감시 대상 = 당일 상승 %d위 ∪ 하락 %d위 = %d개 "
            "(USDT %d개 중 거래대금 %.0fM 하한 통과분에서 선정) "
            "→ 패턴 B[%.0f%%~%.0f%%] 통과 %d개 (Fix 217/220)",
            MAX_SYMBOLS, MAX_SYMBOLS, len(_ranked), _usdt_n,
            MIN_QUOTE_VOLUME / 1_000_000,
            PATTERN_B_MIN_CHG, PATTERN_B_MAX_CHG, len(candidates),
        )

        if not candidates:
            logger.info(
                "[Fix50v2/long] 후보 없음! (A: +%.1f~+%.1f%%, B: %.1f~%.1f%%)",
                PATTERN_A_MIN_CHG, PATTERN_A_MAX_CHG,
                PATTERN_B_MIN_CHG, PATTERN_B_MAX_CHG,
            )
            return {"detected": 0, "scanned": 0, "spec_version": SPEC_VERSION}

        # 5. 활성 심볼 skip! (헌법 6 = 단일 진실 = 공유 원칙!)
        active_syms = set()
        try:
            active = db.execute(
                select(StrategyInstance).where(
                    StrategyInstance.status.in_(list(ACTIVE_LIKE)),
                    StrategyInstance.is_archived.is_(False),  # Fix 171 (헌법 108): 보관된 전략이 심볼을 점유하지 않도록
                )
            ).scalars().all()
            active_syms = {r.symbol for r in active}
        except Exception:
            pass

        # 6. Redis! (헌법 6 = 단일 진실 = 공유 원칙!)
        from app.core.redis_client import get_redis_client
        r = get_redis_client()

        # 7. 심볼별 저점 감지 (v223 → v219 대칭 fallback)!
        for t in candidates:
            symbol = str(t.get("symbol", ""))
            if not symbol or symbol in active_syms:
                continue
            try:
                scanned += 1
                chg24 = float(t.get("priceChangePercent", 0) or 0)

                # 🌟 Fix 44 대칭: 트렌드 강도 판정 (심볼당 1회 = 4H×20봉)!
                # 사장님 사상: 강한 하락 트렌드 = 낙엽 잡기 = LONG 위험!
                trend = "unknown"
                if TREND_STRENGTH_ENABLED:
                    trend = _check_trend_strength_long(bc, symbol)

                # 🌟 Fix 44 대칭: 트렌드 필터 (LONG 위험 차단)!
                # 🌟 Fix 50 v2: extreme_bull 도 skip! (3일 +30%↑ = 정점 추격 방지!)
                if TREND_STRENGTH_ENABLED:
                    if trend == "extreme_bear":
                        logger.info(
                            "[Fix44/long] %s 트렌드 극약 (3일 %.0f%%!) = LONG skip!",
                            symbol, TREND_EXTREME_BEAR_PCT,
                        )
                        continue
                    if trend == "extreme_bull":
                        logger.info(
                            "[Fix50v2/long] %s 트렌드 extreme_bull (3일 +%.0f%%↑!) = LONG skip! (정점 위험!)",
                            symbol, TREND_EXTREME_BULL_PCT_3D,
                        )
                        continue
                    # strong_bear = skip X (진입은 허용) but confidence 감소 = 하단 처리!

                # 🌟 Fix 50 v2: 패턴 분류 (A=상승 지속 / B=조정 반전)!
                pattern = _classify_pattern(chg24)
                if pattern is None:
                    # 이론상 candidates 필터에서 걸러졌지만 방어!
                    continue

                # 🌟 Fix 50 v2: 패턴별 지표 확인!
                # 사장님 verbatim: "상승할 심볼에 롱으로 진입" + "다시 상승할것 같으면 롱으로 진입"
                pat_res = _check_pattern_signals(bc, symbol, pattern)
                if not pat_res.get("ok"):
                    logger.debug(
                        "[Fix50v2/long] %s pattern=%s 지표 미충족: %s",
                        symbol, pattern, pat_res.get("reason"),
                    )
                    continue
                logger.info(
                    "[Fix50v2/long] %s pattern=%s 지표 통과: %s",
                    symbol, pattern, pat_res.get("reason"),
                )

                # ========================================================
                # 🌟 v223 대칭: 15m MAIN gate + 1h/4h 역방향 skip! (default!)
                # ========================================================
                if V223_ENABLED:
                    v = LongBottomDetector.check_v223_15m_primary(bc, symbol)
                    if not v.get("detected"):
                        logger.debug(
                            "[LONG bottom detector v223] skip %s: %s",
                            symbol, v.get("reason"),
                        )
                        continue
                    conf = v.get("confidence", 0)
                    # 🌟 Fix 44 대칭: strong_bear LONG = confidence 감소 (신중!)
                    if TREND_STRENGTH_ENABLED and trend == "strong_bear":
                        conf = round(max(0.0, conf - TREND_CONFIDENCE_PENALTY), 4)
                        logger.info(
                            "[Fix44/long] %s LONG strong_bear → confidence -%.2f (신중 진입!)",
                            symbol, TREND_CONFIDENCE_PENALTY,
                        )
                    if conf < MIN_CONFIDENCE:
                        continue

                    # Redis 알람 (신 키 형식: sajangnim:bottom_long:{symbol})
                    # 🌟 Fix 50 v2: pattern 필드 추가 (A/B 구분!)
                    alert_key = f"sajangnim:bottom_long:{symbol}"
                    alert_data = {
                        "symbol": symbol,
                        "side": "LONG",
                        "pattern": pattern,        # 🌟 Fix 50 v2: A or B!
                        "chg_24h": chg24,          # 🌟 Fix 50 v2: 명시!
                        "confidence": conf,
                        "score_15m": v.get("score_15m"),
                        "opp_score_1h": v.get("opp_score_1h"),
                        "opp_score_4h": v.get("opp_score_4h"),
                        "entry_snapshot": v.get("entry_snapshot"),
                        "pattern_signals": pat_res.get("signals"),  # 🌟 Fix 50 v2!
                        "change_24h": chg24,       # 호환 유지 (기존 필드!)
                        "trend_strength": trend,   # Fix 44 대칭!
                        "detected_at": datetime.now(timezone.utc).isoformat(),
                        "source": "sajangnim_fix50v2_long",
                        "spec_version": SPEC_VERSION,
                    }
                    r.setex(alert_key, ALERT_TTL_SEC, json.dumps(alert_data, default=str))
                    detected_symbols.append({
                        "symbol": symbol, "side": "LONG",
                        "pattern": pattern,        # 🌟 Fix 50 v2!
                        "confidence": conf, "change_24h": chg24,
                        "score_15m": v.get("score_15m"),
                    })

                    # 🌟 Fix 50 v2: 로그에 pattern 명시!
                    logger.warning(
                        "[Fix50v2/long] 🎯 %s LONG pattern=%s conf=%.2f 15m=%d/5 24h=%+.1f%% opp(1h=%d,4h=%d)",
                        symbol, pattern, conf, v.get("score_15m", 0),
                        chg24, v.get("opp_score_1h", 0), v.get("opp_score_4h", 0),
                    )

                    # 텔레그램! (🌟 Fix 50 v2: pattern별 설명 추가!)
                    try:
                        from app.services.notification_service import NotificationService
                        _db_n = SessionLocal()
                        _ns = NotificationService(_db_n)
                        # 사장님 verbatim 인용!
                        if pattern == "A":
                            _pat_desc = (
                                f"패턴 A (상승 지속): 사장님 verbatim = \n"
                                f"「1-2일 10% 전후 상승 = 상승할 심볼에 롱으로 진입」!"
                            )
                        else:
                            _pat_desc = (
                                f"패턴 B (조정 반전): 사장님 verbatim = \n"
                                f"「급상승후 큰조정에서 다시 상승할것 같으면 롱으로 진입」!"
                            )
                        _body = (
                            f"🎯 Fix50v2 LONG 감지: {symbol} (24h {chg24:+.1f}%)\n"
                            f"패턴: {pattern}\n"
                            f"{_pat_desc}\n"
                            f"신뢰도: {conf*100:.0f}%\n"
                            f"15m score: {v.get('score_15m')}/5 (MAIN)\n"
                            f"1h/4h 역방향(SHORT): {v.get('opp_score_1h')}/{v.get('opp_score_4h')}\n"
                            f"자동 LONG 진입 대기!"
                        )
                        _ns.send_system_alert(
                            title=f"🎯 [Fix50v2 pat={pattern}] {symbol} LONG ({conf*100:.0f}%)",
                            body=_body,
                        )
                        try:
                            _db_n.close()
                        except Exception:
                            pass
                    except Exception as _te:
                        logger.warning(
                            "[LONG bottom detector v223] telegram 실패: %s", _te,
                        )
                    continue  # 이 심볼 완료 → 다음 심볼!

                # ========================================================
                # v219 대칭 fallback: LONG만 = 7중 완전 저점!
                # 🚨 OBV 반전 없으면 무조건 skip (사장님 verbatim!)
                # ========================================================
                kl = bc.get_klines(symbol=symbol, interval="4h", limit=120)
                if not isinstance(kl, list) or len(kl) < 60:
                    continue
                result = LongBottomDetector.check_7_signals(kl, t)
                if result.get("obv_skip"):
                    logger.debug(
                        "[LONG bottom detector v219] %s OBV 반전 미확인 = skip!",
                        symbol,
                    )
                    continue
                if not result.get("detected"):
                    continue
                if result.get("confidence", 0) < MIN_CONFIDENCE:
                    continue

                # Fix 65: OBV 절대값 검증 (사장님 사상!)
                try:
                    from app.services.obv_gate import check_obv_gate
                    obv_pass, obv_reason = check_obv_gate(bc, symbol, "LONG")
                    if not obv_pass:
                        logger.info("[long_bottom+Fix65] %s skip: %s", symbol, obv_reason)
                        continue
                except Exception as _obv_exc:
                    logger.warning("[long_bottom+Fix65] %s obv_gate error: %s", symbol, _obv_exc)

                # Fix 66 P1 + P2!
                try:
                    from app.services.bidirectional_blocklist import is_bidirectional_blocked
                    from app.services.pump_dump_regime import is_regime_blocked_for_long
                    from app.core.database import SessionLocal as _SL
                    db_bl = _SL()
                    try:
                        blocked, block_reason = is_bidirectional_blocked(db_bl, symbol)
                        if blocked:
                            logger.info("[long_bottom+Fix66] %s skip: %s", symbol, block_reason)
                            continue
                    finally:
                        db_bl.close()
                    regime_blocked, regime_reason = is_regime_blocked_for_long(bc, symbol)
                    if regime_blocked:
                        logger.info("[long_bottom+Fix66] %s skip: %s", symbol, regime_reason)
                        continue
                except Exception as _f66_exc:
                    logger.warning("[long_bottom+Fix66] error: %s", _f66_exc)

                alert_key = f"sajangnim:bottom_long:{symbol}"
                # 🌟 Fix 50 v2: fallback도 pattern 필드 명시!
                alert_data = {
                    "symbol": symbol, "side": "LONG",
                    "pattern": pattern,         # 🌟 Fix 50 v2!
                    "chg_24h": chg24,           # 🌟 Fix 50 v2!
                    "confidence": result["confidence"],
                    "signals": result["signals"],
                    "pattern_signals": pat_res.get("signals"),  # 🌟 Fix 50 v2!
                    "close": result["close"], "rsi": result["rsi"],
                    "cci_last": result["cci_last"],
                    "change_24h": result["change_24h"],
                    "trend_strength": trend,  # Fix 44 대칭!
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                    "source": "sajangnim_bottom_v219_long_fix50v2",
                    "spec_version": SPEC_VERSION,
                }
                r.setex(alert_key, ALERT_TTL_SEC, json.dumps(alert_data))
                detected_symbols.append({
                    "symbol": symbol, "side": "LONG",
                    "pattern": pattern,        # 🌟 Fix 50 v2!
                    "confidence": result["confidence"], "change_24h": chg24,
                })

                logger.warning(
                    "[Fix50v2/long/v219fb] 🎯 %s LONG pattern=%s conf=%.2f 24h=%+.1f%%",
                    symbol, pattern, result["confidence"], chg24,
                )

                # 텔레그램! (v219 대칭 fallback 경로!)
                try:
                    from app.services.notification_service import NotificationService
                    _db_n = SessionLocal()
                    _ns = NotificationService(_db_n)
                    _body = (
                        f"📉 7중 저점 LONG 감지: {symbol} (24h {chg24:+.1f}%)\n"
                        f"신뢰도: {result['confidence']*100:.0f}%\n"
                        f"RSI: {result.get('rsi')}, CCI: {result.get('cci_last')}\n"
                        f"OBV 반전 상승 확인! 자동 LONG 진입 대기!"
                    )
                    _ns.send_system_alert(
                        title=f"📉 [v219 저점] {symbol} LONG ({result['confidence']*100:.0f}%)",
                        body=_body,
                    )
                    try:
                        _db_n.close()
                    except Exception:
                        pass
                except Exception as _te:
                    logger.warning(
                        "[LONG bottom detector v219] telegram 실패: %s", _te,
                    )

            except Exception as e:
                logger.warning(
                    "[LONG bottom detector v223] %s 스캔 실패: %s", symbol, e,
                )
                continue

        # 🌟 Fix 50 v2: pattern별 카운트 로그!
        pat_a = sum(1 for d in detected_symbols if d.get("pattern") == "A")
        pat_b = sum(1 for d in detected_symbols if d.get("pattern") == "B")
        logger.info(
            "[Fix50v2/long] 완료: scanned=%d detected=%d (A=%d, B=%d)",
            scanned, len(detected_symbols), pat_a, pat_b,
        )
        return {
            "scanned": scanned,
            "detected": len(detected_symbols),
            "pattern_a": pat_a,
            "pattern_b": pat_b,
            "symbols": detected_symbols,
            "spec_version": SPEC_VERSION,
        }
    except Exception as e:
        logger.exception("[LONG bottom detector v223] 실행 실패: %s", e)
        return {"error": str(e), "detected": 0}
    finally:
        db.close()
