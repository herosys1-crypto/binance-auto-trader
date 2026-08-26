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

import json
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


def _mtf_merge(snapshot, symbol, side):
    """🎯 Fix 132: entry_snapshot 에 15m/1h/4h 전 지표를 덧붙인다.

    사장님 요구 = "성공과 실패의 15분 1시간 4시간 차트와 보조지표들의 정확한 수치"
    기존 키는 절대 덮지 않으며, 실패해도 원본을 그대로 돌려준다 (진입을 막지 않음).
    """
    try:
        from app.services.mtf_snapshot import merge_into
        return merge_into(snapshot, None, symbol, side)
    except Exception as e:
        logger.warning("[Fix132] %s MTF 스냅샷 실패 (진입 계속): %s", symbol, e)
        return snapshot


# ============================================================================
# SPEC 상수 (Fix 50 v2 = 사장님 verbatim 2 패턴 분기!)
#   사장님 verbatim 1: "급락한 종목에서 롱을 찾아야지 지금은 급등후에 조정후 상승에 진입이 많은것 같아"
#   사장님 verbatim 2: "경로 A: 진짜 급락(-30%~-10%) ... 최근 1일 -2일 10% 전후 상승하는
#                       심볼을 모니터링해서 상승할 심볼에 롱으로 진입하고 나머진 급상승후 큰조정에서
#                       모니터링중 심볼중에 다시 상승할것 같으면 롱으로 진입하는거야"
# ============================================================================
# Fix 61 P1 = 사장님 verbatim (2026-08-24): "손실만 늘어나는데 진입조건을
#              다시 정리해서 롱은 좀더 신뢰도을 높혀줘"
#            → MIN_CONFIDENCE 0.85→0.90, RSI/OBV 임계값 강화,
#              패턴 A/B 조건 대폭 상향! (손실 방지!)
SPEC_VERSION = "auto_long_at_bottom_v4_fix75_2026-08-25"
INTERVAL_SEC = 30

# 🚨 Fix 75 (2026-08-25 사장님!): long_bottom_detector_worker가 저장한 알람을
# 실제로 소비하는 Redis key pattern (auto_short_at_top ALERT_PATTERN 대칭!)
# 사장님 verbatim: "macd 15분 하락 후 반등 시작점과 반등후 하락 위치를 참고"
ALERT_PATTERN = "sajangnim:bottom_long:*"

DEFAULT_LEVERAGE = 2          # 사장님 default!
DEFAULT_CAPITAL = 300.0       # sajangnim_default_capital fallback!
DEFAULT_DAILY_LIMIT = 20      # sajangnim_top_short_daily_limit fallback!

# 4H OBV 상승 하드 게이트 = Fix 48 + Fix 61 P1 (사장님 verbatim = 손실 방지!)
OBV_LOOKBACK_4H = 20          # 4H 최근 20봉 = 약 3일 매크로!
OBV_MIN_SLOPE_PCT = 1.0       # Fix 61 P1: 0.5 → 1.0 (더 확실한 상승!)

# 15m MACD/RSI/CCI 반전 (레거시 상수 = 다른 곳 참조 방지 = 유지!)
MACD_15M_LIMIT = 80
RSI_OVERSOLD_MAX = 45         # RSI ≤ 45 = 과매도 회복권!
RSI_MIN_TURNUP = 0.5          # RSI now > prev + 0.5 = 반등!
CCI_OVERSOLD_MAX = -50        # CCI ≤ -50 = 저점권!
CCI_MIN_TURNUP = 5.0          # CCI now > prev + 5 = 반등!

# 🌟 Fix 87 P0 (2026-08-25 사장님 = 헌법 78!):
# 사장님 verbatim: "전략에 들어가는건 당일 급등락한 심볼만 거래하는거야"
# → LONG = 급락 (-10% 이하)만! 상승 = SHORT 대칭 처리!
# 패턴 A (+5%~+15% 상승 지속) = 헌법 78 위반 = 완전 skip!
# 패턴 B 상한도 -3%로 강화 = 더 확실한 급락 심볼만!
# 24h 필터 (Fix 87 = 급락만!)
# ═══════════════════════════════════════════════════════════════════════════
# 🚨 Fix 148 (2026-08-26): 닫힌 구간 [-15%, -3%] 이 사장님 LONG 시나리오를 배제
#
# 사장님 verbatim (헌법 73~75, LONG 4 시나리오):
#   "롱진입은 급락후 반등하는 시점과 장기 하락후 볼밴하단 지지또는 돌파 확인된 시점에
#    많이 진입하고 급등후 조정 볼밴 중단 지지와 하단 지지에 진입해야 해"
#
# 옛 창이 배제한 것:
#   24h -20% (진짜 급락)  → 하한 -15% 미만이라 제외  ← 시나리오 1 의 강한 케이스
#   24h +5%  (급등 후 조정) → 상한 -3% 초과라 제외    ← 시나리오 3 전체
#   = 4개 시나리오 중 2개가 코드 레벨에서 영구 봉쇄
#
# 헌법 78 "당일 급등락한 심볼만" 은 지켜야 하므로 「절대값」 기준으로 바꾼다:
#   |24h| >= 3%  = 급등이든 급락이든 당일 움직인 종목만 (헌법 78 충족)
#   하한 제거    = -20%, -30% 급락도 후보 (시나리오 1)
#   상한 제거    = +5%, +20% 급등 후 조정도 후보 (시나리오 3)
# 실제 진입 판정은 BB 위치·지표 반전·peak_confirmation 이 담당한다.
# (24h 는 "움직인 종목인가"를 거르는 1차 필터일 뿐, 방향 판정 도구가 아니다)
# ═══════════════════════════════════════════════════════════════════════════
MIN_ABS_24H_CHANGE = 3.0      # |24h| >= 3% = 당일 급등락 종목 (헌법 78)
# 🎯 Fix 150: 급등 종목이 「조정 중」인지 판정하는 BB 위치 상한
#   bb_pos = (종가-하단)/(상단-하단). 0.5 = 중단, 1.0 = 상단
#   사장님 "급등후 조정 볼밴 중단 지지" → 중단(0.5) 이하로 내려왔을 때만 LONG
PUMP_PULLBACK_MAX_BBPOS = 0.5
MIN_24H_CHANGE = -15.0        # (레거시 = 패턴 B 등 다른 참조 유지용)
MAX_24H_CHANGE = -3.0         # (레거시)

# Fix 50 v2 = 사장님 verbatim 2 패턴 분기 상수 (Fix 87 = 패턴 A 완전 skip!)
# ⚠️ Fix 87 (헌법 78): PATTERN_A_* 상수는 dispatcher에서 참조하지만 실제 진입은 skip!
#   (상수는 유지 = 다른 곳 참조 방지 + 로그 표현)
PATTERN_A_MIN_CHG = 5.0       # 패턴 A 하한 (지속 상승 초기!) — Fix 87 = 진입 skip!
PATTERN_A_MAX_CHG = 15.0      # 패턴 A 상한 — Fix 87 = 진입 skip!
PATTERN_B_MIN_CHG = -15.0     # 패턴 B 하한 (큰 조정!)
PATTERN_B_MAX_CHG = -3.0      # 🌟 Fix 87: 0 → -3.0 (급락 확실!)
TREND_EXTREME_BULL_PCT_3D = 30.0  # 3일 +30%↑ = extreme (skip! 정점 위험!)
RSI_PATTERN_A_MIN = 35.0      # Fix 61 P1: 30 → 35 (더 엄격!)
RSI_PATTERN_A_MAX = 55.0      # Fix 61 P1: 60 → 55 (과매수 X! 더 엄격!)
# 🚨 Fix 153 (2026-08-26): 게이트 2 와 3 이 서로 모순 — 실측 13/13 전멸
#
# 사장님 실 로그: nd:B1=16 nd:B3=13 nd:B2=7 nd:B0=3
#   게이트 3 까지 도달한 13개가 「전부」 탈락 = 100% 거부율.
#
# 게이트 2: MACD bullish (cross or hist_turnup) = 반등이 「이미 시작」됨
# 게이트 3: RSI <= 40                          = 아직 「깊은 과매도」
#   MACD 가 상승 전환했다면 가격이 이미 반등 중이고 RSI 는 보통 40 을 넘어 회복한다.
#   두 조건을 동시에 요구하면 극히 좁은 순간만 통과 = 사실상 진입 불가.
#
# 사장님 헌법 77: "macd 15분 하락 후 반등 시작점" —
#   반등 시작점에서 RSI 는 바닥을 벗어나 올라오는 중이다.
#   40 을 요구하면 사장님이 지목한 바로 그 시점을 배제한다.
#   (Fix 61 P1 이 45 → 40 으로 더 엄격하게 만든 것이 이 모순을 키웠다)
#
# → 50 으로 조정. 50 은 여전히 중립 이하라 과매수 진입은 막으면서,
#   MACD 반등 직후의 전형적 RSI 대역(40~50)을 포함한다.
#   ⚠️ 한 번에 하나만 바꾼다. B1(OBV 4H 반전, 16건 거부)은 사장님 사상의 핵심
#      「OBV = 지속성」이므로 이번엔 손대지 않고 결과를 관찰한다.
RSI_PATTERN_B_MAX = 50.0

# 🌟 Fix 87 P0 (2026-08-25 사장님!): BTC 방향 필터 (SHORT auto_short_at_top 대칭!)
# BTC 24h < -2% = 시장 하락장 = LONG 위험! (LONG skip!)
# 🚨 Fix 147 (2026-08-26): 2.0 → 3.0 (auto_bb_breakdown 과 동일 = 진짜 대칭)
#   옛 주석은 "auto_short_at_top BTC 필터 대칭" 이라 했지만
#   auto_short_at_top_worker.py 에는 BTC 코드가 「한 줄도 없다」 = 근거가 거짓이었다.
#   실제로는 LONG 만 시장 전체 차단을 받고 SHORT 는 무제한이었다 (SHORT 편중 원인).
#   ⚠️ 사장님 LONG 시나리오 1 "급락 후 반등" 은 BTC 가 빠지는 국면이 바로 그 setup 이다.
#      전면 차단은 사상과 충돌하므로 최소한 대칭값으로 맞춘다.
#      진짜 안전장치는 peak_confirmation (반복 하락 + 지표 저점 반등) 이다.
BTC_DIRECTION_THRESHOLD_LONG = 3.0

# 스캔 상한!
MAX_SYMBOLS = 40              # 심볼당 4 kline call = API 부담 대응!
MIN_CONFIDENCE = 0.85         # 🌟 Fix 90 (2026-08-25 사장님!): 0.90 → 0.85
                              # long_bottom_detector와 통일! (기존 = 알람 대부분 drop = 낭비!)
                              # Fix 87 헌법 78 (급락만) + BTC 필터 + Pattern A skip = 이미 안전!
MIN_PASSED = 5                # Fix 61 P1: 4/7 → 5/7 (71% = 더 엄격!)
                              # (참고 = 각 패턴 함수는 모든 조건 AND 통과 시만
                              #  detected=True 반환 = 사실상 100% 통과가 게이트.
                              #  이 상수는 문서/향후 확장용!)

# ============================================================================
# 조건 검사 헬퍼 (v219 대칭 = LONG 방향!)
# ============================================================================


def _get_btc_change_24h() -> float | None:
    """🌟 Fix 87 (2026-08-25): BTC 24h 변동 조회 = 시장 방향!
    (auto_bb_breakdown._get_btc_change_24h L975 대칭!)
    """
    try:
        from app.core.redis_client import get_redis_client
        import json as _j
        r = get_redis_client()
        _raw = r.get("ticker_24h:BTCUSDT")
        if _raw:
            _data = _j.loads(_raw.decode() if isinstance(_raw, bytes) else _raw)
            return float(_data.get("priceChangePercent", 0) or 0)
    except Exception:
        pass
    return None


def _matches_btc_direction_conflict_long() -> tuple[bool, str]:
    """🌟 Fix 87 (2026-08-25 사장님!): BTC 하락장 = LONG 진입 금지!

    ⚠️ Fix 147 정정: 옛 주석의 "auto_short_at_top 대칭" 은 사실이 아니었다
    (그 워커에 BTC 코드 없음). 임계를 auto_bb_breakdown 과 같은 3.0 으로 맞춤.
      - BTC 24h < -3% = 시장 하락장 = LONG skip

    Returns:
        (blocked, reason)
    """
    _btc = _get_btc_change_24h()
    if _btc is None:
        return False, "btc 데이터 없음 = 통과"
    if _btc < -BTC_DIRECTION_THRESHOLD_LONG:
        return True, (
            f"🚨 Fix 87: BTC 24h {_btc:+.2f}% < -{BTC_DIRECTION_THRESHOLD_LONG}% "
            f"= 시장 하락장 = LONG skip!"
        )
    return False, f"btc {_btc:+.2f}% = 통과"


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


# ============================================================================
# Fix 50 v2 = 사장님 verbatim 2 패턴 헬퍼! (재사용 우선 = 헌법 6 단일 진실!)
# ============================================================================


def _check_trend_strength_long(bc, symbol: str) -> str:
    """Fix 50 v2: 3일 종가 기반 트렌드 강도 판정!

    Returns:
      - "extreme_bull" (3일 +30%↑) = LONG skip (급등 지속 = 정점 위험!)
      - "strong_bull" (3일 +15~30%) = 패턴 A로만 가능 (조심!)
      - "normal" (3일 ±15%) = 패턴 A/B 모두 가능
      - "bear" (3일 -15%↓) = 패턴 B 우선!
      - "unknown" (조회 실패 = 안전상 skip 처리 대상!)
    """
    try:
        klines = bc.get_klines(symbol=symbol, interval="1d", limit=4)
        if not isinstance(klines, list) or len(klines) < 4:
            return "unknown"
        close_3d_ago = float(klines[0][4])
        close_now = float(klines[-1][4])
        if close_3d_ago <= 0:
            return "unknown"
        chg_3d = ((close_now - close_3d_ago) / close_3d_ago) * 100.0
        if chg_3d >= TREND_EXTREME_BULL_PCT_3D:
            return "extreme_bull"
        if chg_3d >= 15.0:
            return "strong_bull"
        if chg_3d <= -15.0:
            return "bear"
        return "normal"
    except Exception as e:
        logger.debug("[Fix50/trend] %s: %s", symbol, e)
        return "unknown"


def _get_rsi(bc, symbol: str, interval: str = "15m"):
    """Fix 50 v2: 특정 timeframe RSI (rsi_now) 조회 헬퍼.

    ChartAnalyzer.analyze_timeframe 재사용 = 헌법 6 단일 진실!
    """
    try:
        from app.services.chart_analyzer import ChartAnalyzer
        a = ChartAnalyzer.analyze_timeframe(bc, symbol, interval, limit=60)
        if not a:
            return None
        return a.get("rsi_now")
    except Exception as e:
        logger.debug("[Fix50/rsi] %s %s: %s", symbol, interval, e)
        return None


def _check_obv_uptrend(bc, symbol: str, interval: str = "4h", period: int = 20) -> bool:
    """Fix 50 v2: OBV 상승 지속 (기울기 >= OBV_MIN_SLOPE_PCT).

    _get_obv_trend 재사용 = 헌법 6 단일 진실!
    """
    tr = _get_obv_trend(bc, symbol, interval)
    return bool(tr.get("rising"))


def _check_obv_reversal_up(bc, symbol: str, interval: str = "4h") -> bool:
    """Fix 50 v2: OBV 반전 상승 (조정 저점 후 회복!).

    조건: 최근 8봉 = 저점 만들고 재상승 (last > 이전 저점 + last > prev)
    """
    try:
        from app.services.chart_analyzer import ChartAnalyzer
        kl = bc.get_klines(symbol=symbol, interval=interval, limit=15)
        if not isinstance(kl, list) or len(kl) < 8:
            return False
        obv = [float(x) for x in ChartAnalyzer.compute_obv(kl)]
        if len(obv) < 8:
            return False
        recent = obv[-8:]
        last = recent[-1]
        prev = recent[-2]
        window_min = min(recent[:-1])
        base = max(abs(max(recent)), abs(min(recent)), 1.0)
        # 최근 봉이 이전 봉보다 크고, 이전 저점 대비 확실히 회복!
        if last <= prev:
            return False
        recover_ratio = (last - window_min) / base * 100.0
        return recover_ratio >= 0.5
    except Exception as e:
        logger.debug("[Fix50/obv-rev] %s: %s", symbol, e)
        return False


def _check_macd_hist_positive(bc, symbol: str, interval: str = "15m") -> bool:
    """Fix 50 v2: MACD Histogram 양수 (지속 상승!).

    _get_macd_signal 재사용 = hist_now > 0!
    """
    try:
        m = _get_macd_signal(bc, symbol, interval)
        hn = m.get("hist_now")
        return hn is not None and float(hn) > 0.0
    except Exception:
        return False


def _check_macd_hist_reversal_up(bc, symbol: str, interval: str = "15m") -> bool:
    """Fix 50 v2: MACD Hist 반전 (음수 저점 → 상승!).

    _get_macd_signal.bullish (cross or hist_turnup) 재사용!
    """
    try:
        m = _get_macd_signal(bc, symbol, interval)
        return bool(m.get("bullish"))
    except Exception:
        return False


# ============================================================================
# Fix 50 v2 = 메인 dispatcher + 패턴 A/B 분기 (사장님 verbatim!)
# ============================================================================


def _check_long_entry_conditions(bc, symbol: str, ticker_24h: dict) -> dict:
    """Fix 50 v2: 사장님 verbatim 2 패턴 분기!

    - 패턴 A: 24h +5~+15% 상승 진행 + OBV/MACD/RSI 지속 신호!
    - 패턴 B: 24h -15~0% 조정 + OBV/MACD/RSI 반전 신호!

    Returns:
        {detected, passed, confidence, signals, entry_snapshot, reason}
    """
    try:
        chg24 = float(ticker_24h.get("priceChangePercent", 0) or 0)

        # 트렌드 강도 확인 (extreme_bull = skip = 정점 위험!)
        trend = _check_trend_strength_long(bc, symbol)
        if trend == "extreme_bull":
            return {
                "detected": False, "passed": 0, "confidence": 0.0,
                "reason": (
                    f"3일 +{TREND_EXTREME_BULL_PCT_3D}%↑ extreme_bull SKIP "
                    f"(정점 위험!)"
                ),
                "trend": trend,
            }

        # 🌟 Fix 87 P0 (2026-08-25 사장님 = 헌법 78!):
        # 사장님 verbatim: "전략에 들어가는건 당일 급등락한 심볼만 거래하는거야"
        # → LONG = 급락만! 패턴 A (+5%~+15% 상승) = 완전 skip!
        if PATTERN_A_MIN_CHG <= chg24 <= PATTERN_A_MAX_CHG:
            return {
                "detected": False, "passed": 0, "confidence": 0.0,
                "reason": (
                    f"🌟 Fix 87 (헌법 78) = 패턴 A skip! "
                    f"24h={chg24:.2f}% 상승 = LONG X (급락만 진입!)"
                ),
                "trend": trend, "pattern": "A_SKIPPED",
            }
        # ═══════════════════════════════════════════════════════════════════
        # 🚨 Fix 150 (2026-08-26): 사장님 LONG 시나리오 3 이 코드에 아예 없었다
        #
        # 사장님 verbatim (헌법 73~75):
        #   "급등후 조정 볼밴 중단 지지와 하단 지지에 진입해야 해"
        #
        # Fix 87 이 「헌법 78 = LONG 은 급락만」을 근거로 패턴 A 를 통째로 막았는데,
        # 두 가지를 혼동했다:
        #   (a) 급등 「중」 상승 지속 LONG = 추격매수 = 위험 = 막는 게 맞다
        #   (b) 급등 「후」 조정에서 BB중단/하단 지지 LONG = 사장님이 원하는 진입
        # 둘은 BB 위치로 구별된다. (a)는 상단 근처, (b)는 중단 이하로 내려와 있다.
        #
        # 그리고 아래 fallthrough 때문에 24h < -15% (진짜 급락) 도 전부 탈락했다.
        # 사장님 시나리오 1 의 가장 강한 케이스가 배제되고 있었던 것.
        #
        # → 급락은 하한 제거, 급등은 「BB 중단 이하로 조정됐을 때만」 허용.
        # ═══════════════════════════════════════════════════════════════════

        # 시나리오 1·2: 급락 (하한 제거 = -22%, -30% 도 후보)
        if chg24 <= PATTERN_B_MAX_CHG:
            return _check_pattern_B_after_correction(
                bc, symbol, ticker_24h, trend, chg24,
            )

        # 시나리오 3: 급등 후 「조정」 — BB 중단 이하로 내려왔을 때만
        if chg24 >= PATTERN_A_MIN_CHG:
            _bbpos = None
            try:
                from app.services.chart_analyzer import ChartAnalyzer
                _a15 = ChartAnalyzer.analyze_timeframe(bc, symbol, "15m", limit=80)
                if _a15:
                    _cl = _a15.get("closes") or []
                    _up, _lo = _a15.get("bb_up_last"), _a15.get("bb_lo_last")
                    if _cl and _up is not None and _lo is not None:
                        _w = float(_up) - float(_lo)
                        if _w > 0:
                            _bbpos = (float(_cl[-1]) - float(_lo)) / _w
            except Exception as _be:
                logger.warning("[Fix150] %s bb_pos 산출 실패: %s", symbol, _be)

            if _bbpos is None:
                return {
                    "detected": False, "passed": 0, "confidence": 0.0,
                    "reason": f"24h={chg24:.2f}% 급등 but BB 위치 확인 불가 = skip",
                    "trend": trend, "pattern": "A_NO_BBPOS",
                }
            if _bbpos > PUMP_PULLBACK_MAX_BBPOS:
                return {
                    "detected": False, "passed": 0, "confidence": 0.0,
                    "reason": (
                        f"24h={chg24:.2f}% 급등 중 BB {_bbpos:.2f} (>{PUMP_PULLBACK_MAX_BBPOS}) "
                        f"= 아직 상단권 = 추격매수 금지 (헌법 78)"
                    ),
                    "trend": trend, "pattern": "A_STILL_HIGH",
                }
            # BB 중단 이하로 조정됨 = 사장님 시나리오 3 = 급락 판정 로직 재사용
            logger.info(
                "[Fix150] %s 급등 후 조정 감지: 24h=%+.2f%% BB위치=%.2f (<=%.2f) "
                "= 사장님 시나리오 3 진입 검사",
                symbol, chg24, _bbpos, PUMP_PULLBACK_MAX_BBPOS,
            )
            return _check_pattern_B_after_correction(
                bc, symbol, ticker_24h, trend, chg24,
            )

        return {
            "detected": False, "passed": 0, "confidence": 0.0,
            "reason": (
                f"24h={chg24:.2f}% = 당일 급등락 아님 "
                f"(급락<={PATTERN_B_MAX_CHG}% or 급등>={PATTERN_A_MIN_CHG}%)"
            ),
            "trend": trend,
        }
    except Exception as e:
        logger.warning("[Fix50/check] %s 실패: %s", symbol, e)
        return {
            "detected": False, "passed": 0, "confidence": 0.0,
            "reason": f"exc:{e}",
        }


def _check_pattern_A_continuation(
    bc, symbol: str, ticker_24h: dict, trend: str, chg24: float,
) -> dict:
    """Fix 50 v2 = 패턴 A: 지속 상승 편승 (초기 상승!).

    조건 (AND!):
      - OBV 4H 상승 지속 (slope >= 0.5%)
      - MACD Hist 양수 (15m + 1h!)
      - RSI 15m 30 ~ 60 (과매수 X!)

    Returns dict compatible with 호출자 (_check_long_entry_conditions 대체!).
    """
    try:
        # OBV 지속 상승 (4H!)
        obv_ok = _check_obv_uptrend(bc, symbol, "4h", period=OBV_LOOKBACK_4H)
        if not obv_ok:
            return {
                "detected": False, "passed": 0, "confidence": 0.0,
                "reason": "패턴 A: OBV 4H 상승 X",
                "pattern": "A", "trend": trend,
            }

        # MACD Hist 양수 (15m + 1h!)
        macd_15m_ok = _check_macd_hist_positive(bc, symbol, "15m")
        macd_1h_ok = _check_macd_hist_positive(bc, symbol, "1h")
        if not (macd_15m_ok and macd_1h_ok):
            return {
                "detected": False, "passed": 1, "confidence": 0.0,
                "reason": (
                    f"패턴 A: MACD Hist 양수 X "
                    f"(15m={macd_15m_ok} 1h={macd_1h_ok})"
                ),
                "pattern": "A", "trend": trend,
            }

        # RSI 30 ~ 60 (과매수 X!)
        rsi_15m = _get_rsi(bc, symbol, "15m")
        if rsi_15m is None or not (
            RSI_PATTERN_A_MIN <= float(rsi_15m) <= RSI_PATTERN_A_MAX
        ):
            return {
                "detected": False, "passed": 2, "confidence": 0.0,
                "reason": f"패턴 A: RSI 범위 밖 (rsi={rsi_15m})",
                "pattern": "A", "trend": trend,
            }

        # Fix 61 P1: 0.86 → 0.90 (사장님 신뢰도 상향! 손실 방지!)
        confidence = 0.90
        obv_tr = _get_obv_trend(bc, symbol, "4h")
        _kst_hour = (datetime.now(timezone.utc).hour + 9) % 24
        signals_passed = {
            "obv_4h_rising": True,
            "macd_hist_15m_pos": macd_15m_ok,
            "macd_hist_1h_pos": macd_1h_ok,
            "rsi_range": True,
            "chg24_pattern_A": True,
        }
        entry_snapshot = {
            "rsi": rsi_15m,
            "cci": None,
            "obv_slope_pct": obv_tr.get("slope_pct"),
            "regime": "PATTERN_A_CONTINUATION",
            "source": "SAJANGNIM_BOTTOM_v2_A",
            "sustained_bars": 0,
            "change_24h": chg24,
            "kst_hour": _kst_hour,
            "confidence": confidence,
            "trend_3d": trend,
            "signals_passed": signals_passed,
            "spec_version": SPEC_VERSION,
            "entered_at": datetime.now(timezone.utc).isoformat(),
        }
        return {
            "detected": True,
            "passed": 3,
            "confidence": confidence,
            "signals": signals_passed,
            "entry_snapshot": entry_snapshot,
            "change_24h": chg24,
            "obv_slope_pct": obv_tr.get("slope_pct"),
            "pattern": "A",
        }
    except Exception as e:
        logger.warning("[Fix50/A] %s 실패: %s", symbol, e)
        return {
            "detected": False, "passed": 0, "confidence": 0.0,
            "reason": f"exc:{e}", "pattern": "A", "trend": trend,
        }


def _check_pattern_B_after_correction(
    bc, symbol: str, ticker_24h: dict, trend: str, chg24: float,
) -> dict:
    """Fix 50 v2 = 패턴 B: 큰 조정 후 재상승!

    조건 (AND!):
      - 이전 3일 상승세 (strong_bull or normal) = 조정 前 상승!
      - OBV 4H 반전 상승 (저점 후 회복!)
      - MACD Hist 반전 (음수 저점 → 상승! 15m!)
      - RSI 15m <= 45 (조정 후 회복권!)
    """
    try:
        # 이전 3일 상승세 확인 (조정 전!)
        was_bull = trend in ("strong_bull", "normal")
        if not was_bull:
            return {
                "detected": False, "passed": 0, "confidence": 0.0,
                "reason": f"패턴 B: 이전 상승세 X (trend={trend})",
                "pattern": "B", "trend": trend,
            }

        # OBV 반전 상승!
        obv_reversal = _check_obv_reversal_up(bc, symbol, "4h")
        if not obv_reversal:
            return {
                "detected": False, "passed": 1, "confidence": 0.0,
                "reason": "패턴 B: OBV 4H 반전 X",
                "pattern": "B", "trend": trend,
            }

        # MACD Hist 반전 (음수 → 양수!)
        macd_reversal = _check_macd_hist_reversal_up(bc, symbol, "15m")
        if not macd_reversal:
            return {
                "detected": False, "passed": 2, "confidence": 0.0,
                "reason": "패턴 B: MACD Hist 반전 X (15m)",
                "pattern": "B", "trend": trend,
            }

        # RSI 회복권 (45 이하!)
        rsi_15m = _get_rsi(bc, symbol, "15m")
        if rsi_15m is None or float(rsi_15m) > RSI_PATTERN_B_MAX:
            return {
                "detected": False, "passed": 3, "confidence": 0.0,
                "reason": (
                    f"패턴 B: RSI 회복권 X "
                    f"(rsi={rsi_15m} > {RSI_PATTERN_B_MAX})"
                ),
                "pattern": "B", "trend": trend,
            }

        # Fix 61 P1: 0.88 → 0.92 (조정 후 재상승 = 더 확실! 사장님 verbatim!)
        confidence = 0.92
        obv_tr = _get_obv_trend(bc, symbol, "4h")
        _kst_hour = (datetime.now(timezone.utc).hour + 9) % 24
        signals_passed = {
            "prev_bull": True,
            "obv_4h_reversal": True,
            "macd_hist_reversal_15m": True,
            "rsi_recover": True,
            "chg24_pattern_B": True,
        }
        entry_snapshot = {
            "rsi": rsi_15m,
            "cci": None,
            "obv_slope_pct": obv_tr.get("slope_pct"),
            "regime": "PATTERN_B_AFTER_CORRECTION",
            "source": "SAJANGNIM_BOTTOM_v2_B",
            "sustained_bars": 0,
            "change_24h": chg24,
            "kst_hour": _kst_hour,
            "confidence": confidence,
            "trend_3d": trend,
            "signals_passed": signals_passed,
            "spec_version": SPEC_VERSION,
            "entered_at": datetime.now(timezone.utc).isoformat(),
        }
        return {
            "detected": True,
            "passed": 4,
            "confidence": confidence,
            "signals": signals_passed,
            "entry_snapshot": entry_snapshot,
            "change_24h": chg24,
            "obv_slope_pct": obv_tr.get("slope_pct"),
            "pattern": "B",
        }
    except Exception as e:
        logger.warning("[Fix50/B] %s 실패: %s", symbol, e)
        return {
            "detected": False, "passed": 0, "confidence": 0.0,
            "reason": f"exc:{e}", "pattern": "B", "trend": trend,
        }


# ============================================================================
# 세팅/카운터 헬퍼 (v219 공유!)
# ============================================================================


def _get_daily_limit(db: Session) -> int:
    """사장님 사상 (헌법 6 단일 진실!): v219 SHORT 과 같은 counter 공유!

    사장님 verbatim: "일 진입수는 급등락 실시간과 같이 세팅"
    = sajangnim_top_short_daily_limit → auto_bb_break_daily_limit 통합!
    """
    # 🚨🚨 Fix 108 (2026-08-26 CRITICAL): 「0 = OFF」 가 20 으로 둔갑하던 버그!
    #
    # 사장님 실측: 4개 설정 전부 0 인데 오늘 137건 진입!
    #   sajangnim_top_short_daily_limit=0 / auto_bb_break_daily_limit=0 ...
    #
    # 옛 로직: `if v > 0: return v` → 0 이면 return 안 하고 루프 계속
    #          → 전 키가 0 이면 마지막에 DEFAULT_DAILY_LIMIT(20) 반환!
    #          → 사장님이 「끄기」 하려고 0 을 넣어도 시스템은 20건씩 진입!
    #          = 정지 스위치가 작동하지 않는 상태 (자본 위험!)
    #
    # 신 로직: 값이 존재하면 0 이어도 그대로 존중 = 「명시적 0 = 완전 OFF」!
    #          키 자체가 없을 때만 DEFAULT 사용.
    for key in ("sajangnim_top_short_daily_limit", "auto_bb_break_daily_limit"):
        try:
            row = db.get(SystemSetting, key)
            if row and row.value is not None and str(row.value).strip() != "":
                v = int(row.value)
                if v <= 0:
                    logger.warning(
                        "[auto_long_bottom+Fix108] %s=%d → 자동 진입 완전 OFF (사장님 명시 정지!)",
                        key, v,
                    )
                    return 0        # 🚨 명시적 0 = OFF! (옛: 무시하고 20 으로 진행!)
                return v
        except Exception:
            continue
    return DEFAULT_DAILY_LIMIT


def _get_default_capital(db: Session) -> float:
    """🚨 Fix 159 (2026-08-26 사장님 지적): LONG 만 사다리를 무시하고 있었다.

    사장님 스크린샷: #1511/#1492/#1500 이 전부 「1단계 50U LONG」
      사다리는 10/300/600 인데 LONG 만 50 으로 진입.

    원인 = 이 워커가 자체 함수로 sajangnim_default_capital(=50) 을 읽었다.
      SHORT(auto_short_at_top)는 compute_stage1_capital → 사다리 1칸 = 10
      LONG(여기)          는 sajangnim_default_capital     = 50
      → 같은 「1단계 자본」에 읽는 경로가 둘 = 반드시 어긋난다 (헌법 101)
      Fix 143 이 compute_stage1_capital 만 고치고 이 함수를 놓쳤다.

    → SHORT 와 같은 단일 진실(사다리)을 쓴다 (헌법 6).
    """
    try:
        from app.services.sajangnim_capital import compute_stage1_capital
        v = float(compute_stage1_capital(None, db))
        if v > 0:
            return v
    except Exception as e:
        logger.warning("[Fix159] 사다리 조회 실패 → 옛 설정 fallback: %s", e)
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
    db: Session, symbol: str, capital: float, bc=None,
) -> StrategyInstance | None:
    """v219 진입 방식 재사용 = _create_auto_bb_strategy!

    - strategy_type_suffix = "_SAJANGNIM_BOTTOM" (v219 _SAJANGNIM_TOP 대칭!)
    - leverage = 2x (사장님 default!)
    - 1단계만 (v177 사상!)
    - SL 강제 -80% (v225 사장님 사상!)
    - MARKET 진입 + start_stage1 실 주문 발송!
    """
    try:
        # 🎯 Fix 111b (2026-08-26): LONG 저점 게이트! (SHORT 와 대칭 = 헌법 5)
        #   Fix 111 은 SHORT 경로에만 걸려 있었다 = 비대칭!
        #   사장님 사상은 LONG 도 동일: 「급락이 2-3회 반복 + 지표 저점 반등」
        #   → 단조 하락 도중(= 하락 초입) LONG 진입을 차단한다.
        #   ZROUSDT(고점 대비 -11% 조정 중 진입) 같은 사고의 대칭 방지책.
        if bc is not None:
            from app.services.peak_confirmation import confirm_peak
            _pk_ok, _pk_why, _pk_det = confirm_peak(bc, symbol, "LONG")
            if not _pk_ok:
                logger.warning(
                    "[auto_long_bottom+Fix111b] %s SKIP: %s | %s", symbol, _pk_why, _pk_det,
                )
                return None
            logger.info("[auto_long_bottom+Fix111b] %s %s", symbol, _pk_why)

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
    # 🎯 Fix 149 (2026-08-26): scanned=40 인데 skipped=0 entered=0 = 사유 불명이었다.
    #   판정 루프에 사유를 남기지 않는 continue 가 5개 있어
    #   「왜 LONG 이 안 들어가는가」를 로그로 알 수 없었다 (헌법 93).
    _reasons: dict[str, int] = {}

    def _bump(reason: str) -> None:
        _reasons[reason] = _reasons.get(reason, 0) + 1
    scanned = 0
    results: list[dict] = []
    try:
        # 🌟 Fix 87 P0 (2026-08-25 사장님!): BTC 방향 필터 = 하락장 = LONG 전면 skip!
        # (auto_short_at_top BTC 필터 대칭 = SHORT 대칭 정합성!)
        _btc_blocked, _btc_reason = _matches_btc_direction_conflict_long()
        if _btc_blocked:
            logger.warning("[auto_long_bottom+Fix87] %s → 전체 사이클 skip!", _btc_reason)
            return {
                "note": _btc_reason,
                "entered": 0, "spec": SPEC_VERSION, "btc_blocked": True,
            }

        # 1. daily_limit 체크 (v219 통합!)
        # 🚨 Fix 109 (2026-08-26 헌법 80): 조기 return 무로그 금지!
        #   무로그 return = 「워커가 죽음」과 「조용히 종료」를 구별 불가!
        #   (realtime_reentry 가 정확히 이것 때문에 며칠간 침묵했음 = Fix 103!)
        # 🎯 Fix 112 (2026-08-26 사장님 verbatim):
        #   "일 20개로 하지말고 일 20개 최대 20개 수정해줘"
        #   = 동시 보유 상한! (SHORT 와 같은 풀 공유 = 전체 노출 20건 고정!)
        from app.services.position_limit import check_position_slot
        _ok, _why, active_cnt, daily_limit = check_position_slot(db, "auto_long_bottom")
        if not _ok:
            logger.warning("[auto_long_bottom+Fix112] SKIP: %s", _why)
            return {
                "note": _why, "entered": 0, "spec": SPEC_VERSION,
                "active": active_cnt, "limit": daily_limit,
            }

        used = active_cnt
        remaining = daily_limit - active_cnt
        logger.info("[auto_long_bottom+Fix112] %s", _why)

        # 2. mainnet 계정!
        account = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if not account:
            logger.warning("[auto_long_bottom] SKIP: mainnet 계정 없음! (설정 확인 필요)")
            return {"error": "mainnet 계정 없음!", "entered": 0, "spec": SPEC_VERSION}

        # 3. API Ban 체크!
        try:
            from app.core.api_backoff import is_account_banned
            if is_account_banned(account.id):
                logger.warning(
                    "[auto_long_bottom] SKIP: API Ban 중! (account_id=%s)", account.id,
                )
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

        # ========================================================
        # 활성 심볼 + 자본 (alert loop + 자체 스캔 loop 공유!)
        # Fix 75: 이전엔 자체 스캔에서만 계산했으나, alert loop도 필요 =
        # 상위로 승격 → 아래 자체 스캔은 재계산 X (헌법 6 단일 진실!)
        # ========================================================
        active_syms: set[str] = set()
        try:
            active = db.execute(
                select(StrategyInstance).where(
                    StrategyInstance.status.in_(list(ACTIVE_LIKE)),
                    StrategyInstance.is_archived.is_(False),  # Fix 171 (헌법 108): 보관된 전략이 심볼을 점유하지 않도록
                )
            ).scalars().all()
            active_syms = {r_.symbol for r_ in active}
        except Exception:
            pass

        capital = _get_default_capital(db)

        # ========================================================
        # 🚨 Fix 75 (2026-08-25 사장님!): Redis alert consumer!
        # long_bottom_detector_worker가 저장하는 sajangnim:bottom_long:*
        # alert를 실제로 소비 = auto_short_at_top와 100% 대칭!
        # 사장님 verbatim: "macd 15분 하락 후 반등 시작점과 반등후
        #                    하락 위치를 참고해줘"
        # additive = 기존 24h ticker 자체 스캔은 유지 (fallback!)
        # ========================================================
        alert_keys: list = []
        r = None
        try:
            from app.core.redis_client import get_redis_client
            r = get_redis_client()
            alert_keys = list(r.scan_iter(ALERT_PATTERN))
        except Exception as _rc_exc:
            logger.warning(
                "[Fix75/alert-long] Redis alert scan 실패 (fail-open): %s",
                _rc_exc,
            )
            alert_keys = []

        for _ak in alert_keys:
            if remaining <= 0:
                break
            key_str = _ak.decode() if isinstance(_ak, bytes) else _ak
            try:
                raw = r.get(key_str) if r is not None else None
                if not raw:
                    continue
                alert = json.loads(
                    raw.decode() if isinstance(raw, bytes) else raw
                )
                symbol = alert.get("symbol")
                side = alert.get("side", "LONG")
                if not symbol or side != "LONG":
                    logger.info(
                        "[Fix75/alert-skip] %s: side=%s (LONG 아님)",
                        symbol, side,
                    )
                    continue
                if symbol in active_syms:
                    skipped += 1
                    logger.info(
                        "[Fix75/alert-skip] %s: 이미 활성 심볼", symbol,
                    )
                    continue

                confidence = float(alert.get("confidence", 0) or 0)
                if confidence < MIN_CONFIDENCE:
                    logger.info(
                        "[Fix75/alert-skip] %s: conf=%.2f < %.2f",
                        symbol, confidence, MIN_CONFIDENCE,
                    )
                    _bump("alert_confidence_below_min")
                    continue

                # Fix 65: OBV 절대값 검증 (LONG 방향)
                try:
                    from app.services.obv_gate import check_obv_gate
                    obv_pass, obv_reason = check_obv_gate(bc, symbol, "LONG")
                    if not obv_pass:
                        logger.info(
                            "[Fix75/alert-long+Fix65] %s skip: %s",
                            symbol, obv_reason,
                        )
                        _bump("alert_obv_gate")
                        continue
                except Exception as _obv_exc:
                    logger.warning(
                        "[Fix75/alert-long+Fix65] %s obv_gate error: %s (fail-open)",
                        symbol, _obv_exc,
                    )

                # Fix 66 P1: 양방향 실패 blocklist!
                try:
                    from app.services.bidirectional_blocklist import (
                        is_bidirectional_blocked,
                    )
                    blocked, block_reason = is_bidirectional_blocked(db, symbol)
                    if blocked:
                        logger.info(
                            "[Fix75/alert-long+Fix66] %s skip: %s",
                            symbol, block_reason,
                        )
                        _bump("alert_btc_or_blocked")
                        continue
                except Exception as _bl_exc:
                    logger.warning(
                        "[Fix75/alert-long+Fix66] blocklist error: %s",
                        _bl_exc,
                    )

                # Fix 66 P2: pump_dump_regime (LONG 사이드!)
                try:
                    from app.services.pump_dump_regime import (
                        is_regime_blocked_for_long,
                    )
                    regime_blocked, regime_reason = is_regime_blocked_for_long(
                        bc, symbol,
                    )
                    if regime_blocked:
                        logger.info(
                            "[Fix75/alert-long+Fix66] %s skip: %s",
                            symbol, regime_reason,
                        )
                        _bump("alert_regime_blocked")
                        continue
                except Exception as _rg_exc:
                    logger.warning(
                        "[Fix75/alert-long+Fix66] regime error: %s", _rg_exc,
                    )

                # 실 진입! (_create_long_strategy 재사용 = 헌법 6!)
                new_strategy = _create_long_strategy(db, symbol, capital, bc)
                if not new_strategy:
                    skipped += 1
                    logger.info(
                        "[Fix75/alert-long] ❌ %s 진입 실패 = 알람 유지 (재시도!)",
                        symbol,
                    )
                    continue

                # 🌟 Fix 87 P0 (2026-08-25 사장님!): -10% 손절 override!
                # 원 -5% = leverage 2x + 15m 알트 노이즈 = 자연 노이즈 손절!
                # 신 -10% = leverage 2x → 실 가격 5% = 15m 알트 노이즈 뛰어넘음!
                # 기존 사장님 verbatim: "v219 단계별 진입후 -5% 손실이면 청산하고
                #                        대기 모니터링" → 사장님 요구 상향 반영!
                try:
                    new_strategy.force_sl_enabled_override = True
                    new_strategy.force_sl_roi_override = Decimal("10")
                    db.commit()
                    logger.info(
                        "[Fix75/alert-long+Fix87] 🛡️ %s SL override -10%% 적용 "
                        "(strategy_id=%s, 2x 상향 = 15m 노이즈 방지!)",
                        symbol, new_strategy.id,
                    )
                except Exception as _sl_exc:
                    logger.warning(
                        "[Fix75/alert-long] ⚠️ %s SL override 실패: %s "
                        "(진입은 유지)",
                        symbol, _sl_exc,
                    )
                    db.rollback()

                # entry_snapshot 병합 (Fix 72 upstream rich 우선 =
                #                       auto_short_at_top L233~L260 대칭!)
                _kst_hour = (datetime.now(timezone.utc).hour + 9) % 24
                _entered_iso = datetime.now(timezone.utc).isoformat()
                upstream_snapshot = alert.get("entry_snapshot") \
                    if isinstance(alert, dict) else None
                if isinstance(upstream_snapshot, dict) and upstream_snapshot:
                    entry_snapshot = dict(upstream_snapshot)
                    entry_snapshot.setdefault("regime", "BOTTOM_REVERSAL")
                    entry_snapshot.setdefault("source", "SAJANGNIM_BOTTOM_ALERT")
                    entry_snapshot.setdefault(
                        "change_24h",
                        alert.get("change_24h") or alert.get("chg_24h"),
                    )
                    entry_snapshot.setdefault(
                        "signals_passed",
                        alert.get("signals") or alert.get("pattern_signals"),
                    )
                    entry_snapshot["kst_hour"] = _kst_hour
                    entry_snapshot["confidence"] = confidence
                    entry_snapshot["entered_at"] = _entered_iso
                    entry_snapshot.setdefault("sustained_bars", 0)
                    entry_snapshot.setdefault("spec_version", SPEC_VERSION)
                else:
                    entry_snapshot = {
                        "rsi": alert.get("rsi"),
                        "cci": alert.get("cci_last"),
                        "obv_slope_pct": None,
                        "regime": "BOTTOM_REVERSAL",
                        "source": "SAJANGNIM_BOTTOM_ALERT",
                        "sustained_bars": 0,
                        "change_24h":
                            alert.get("change_24h") or alert.get("chg_24h"),
                        "kst_hour": _kst_hour,
                        "confidence": confidence,
                        "signals_passed":
                            alert.get("signals") or alert.get("pattern_signals"),
                        "entered_at": _entered_iso,
                        "spec_version": SPEC_VERSION,
                    }

                _chg24_val = float(
                    alert.get("change_24h") or alert.get("chg_24h") or 0,
                )
                sugg = StrategySuggestion(
                    symbol=symbol, side="LONG",
                    suggestion_type="sajangnim_bottom_long",
                    strategy_config={
                        "capitals": [capital],
                        "symbol": symbol, "side": "LONG",
                        "sajangnim_bottom": True,
                        "confidence": confidence,
                        "signals":
                            alert.get("signals") or alert.get("pattern_signals"),
                        "entry_snapshot": _mtf_merge(entry_snapshot, symbol, "LONG"),
                        "alert_source": alert.get("source"),
                        "pattern": alert.get("pattern"),
                    },
                    confidence_score=Decimal(str(round(confidence, 4))),
                    reason=(
                        f"🐂 사장님 저점 LONG (Fix75/alert)! "
                        f"pattern={alert.get('pattern', '?')} "
                        f"conf={confidence*100:.0f}% "
                        f"24h={_chg24_val:+.2f}% "
                        f"src={alert.get('source', '?')}"
                    ),
                    status="EXECUTED",
                    execution_mode="AUTO",
                    executed_at=datetime.now(timezone.utc),
                    executed_strategy_id=new_strategy.id,
                    outcome_status="PENDING",
                )
                db.add(sugg)
                db.commit()

                # 알람 삭제 = 중복 진입 방지! (auto_short_at_top L290 대칭!)
                try:
                    if r is not None:
                        r.delete(key_str)
                except Exception as _de:
                    logger.debug(
                        "[Fix75/alert-long] alert delete 실패 (무시): %s", _de,
                    )

                # 자체 스캔 fallback에서 재진입 방지!
                active_syms.add(symbol)

                remaining -= 1
                entered += 1
                results.append({
                    "symbol": symbol, "side": "LONG",
                    "capital": capital,
                    "confidence": confidence,
                    "strategy_id": new_strategy.id,
                    "source": "alert",
                })
                logger.warning(
                    "[Fix75/alert-long] ✅ %s LONG 진입 성공: id=%d source=%s "
                    "conf=%.2f pattern=%s",
                    symbol, new_strategy.id,
                    alert.get("source", "?"), confidence,
                    alert.get("pattern", "?"),
                )

                # 텔레그램! (기존 _notify_entry 재사용!)
                _notify_entry(new_strategy, confidence, entry_snapshot)

                # 오케스트라 EventBus (v206 통합!)
                try:
                    from app.agents.orchestrator.event_bus import get_event_bus
                    from app.agents.orchestrator.event_types import EventType
                    bus = get_event_bus()
                    bus.publish(EventType.AUTO_ENTRY_TRIGGERED, {
                        "strategy_id": new_strategy.id,
                        "symbol": symbol, "side": "LONG",
                        "prob": confidence,
                        "regime": "BOTTOM_REVERSAL",
                        "source": "SAJANGNIM_BOTTOM_ALERT",
                    })
                except Exception as _be:
                    logger.debug(
                        "[Fix75/alert-long] EventBus 실패 (fail-open): %s", _be,
                    )

            except Exception as e:
                logger.warning(
                    "[Fix75/alert-long] %s 처리 실패: %s", key_str, e,
                )
                skipped += 1
                try:
                    db.rollback()
                except Exception:
                    pass
                continue

        # ========================================================
        # 5. 24h ticker 자체 스캔 (Fix 75 이전 로직 = fallback 유지!)
        # ========================================================
        # 5. 24h ticker 상위 = 후보!
        tickers = bc.get_24hr_ticker()
        if not isinstance(tickers, list):
            return {"error": "ticker 실패!", "entered": 0, "spec": SPEC_VERSION}

        usdt = [t for t in tickers if str(t.get("symbol", "")).endswith("USDT")]

        # Fix 50 v2: 정렬 우선순위 = 패턴 B (조정 심볼) 우선 → 패턴 A (상승 심볼) → 그 외
        # 사장님 verbatim 1: "급락한 종목에서 롱을 찾아야지" = 조정 우선!
        # 같은 그룹 내에서는 quoteVolume 큰 심볼 우선 (유동성!)
        def _pattern_priority(t):
            try:
                c = float(t.get("priceChangePercent", 0) or 0)
            except Exception:
                c = 0.0
            try:
                v = float(t.get("quoteVolume", 0) or 0)
            except Exception:
                v = 0.0
            if PATTERN_B_MIN_CHG <= c <= PATTERN_B_MAX_CHG:
                return (0, -v)  # 패턴 B (조정!) 우선!
            if PATTERN_A_MIN_CHG <= c <= PATTERN_A_MAX_CHG:
                return (1, -v)  # 패턴 A (지속 상승!)
            return (2, -v)      # 그 외 (범위 밖 = 후순위!)
        try:
            usdt.sort(key=_pattern_priority)
        except Exception:
            pass

        # 24h 범위 pre-filter (Fix 50 v2 = -15% ~ +15% 확장!)
        candidates = []
        for t in usdt[:MAX_SYMBOLS * 3]:
            try:
                c = float(t.get("priceChangePercent", 0) or 0)
                # Fix 148: 닫힌 구간 → 절대값 기준 (급등/급락 양쪽 모두 후보)
                if abs(c) >= MIN_ABS_24H_CHANGE:
                    candidates.append(t)
                if len(candidates) >= MAX_SYMBOLS:
                    break
            except Exception:
                continue

        if not candidates:
            return {"note": "24h 범위 심볼 없음", "entered": 0, "spec": SPEC_VERSION}

        # 6~7. 활성 심볼 + 자본 = Fix 75에서 이미 상위로 승격됨 (헌법 6 단일 진실!)
        # (alert loop에서 진입한 심볼은 위 active_syms.add(symbol)로 자동 반영)

        # 8. 심볼별 검사 + 진입!
        for t in candidates:
            # 🚨 Fix 112b: 옛 `entered >= remaining` = 이중 차감 버그!
            #   진입할 때마다 entered 는 +1, remaining 은 -1 (L1064/L1267) →
            #   두 값이 서로 마주 달려서 실효 예산이 절반으로 줄었음.
            #   alert 루프(L859)와 동일하게 remaining 하나만 예산으로 사용!
            if remaining <= 0:
                break
            symbol = str(t.get("symbol", ""))
            if not symbol or symbol in active_syms:
                continue

            try:
                scanned += 1
                result = _check_long_entry_conditions(bc, symbol, t)
                if not result.get("detected"):
                    # 🎯 Fix 151: not_detected 는 단일 버킷이라 「어느 게이트가 막았는지」
                    #   알 수 없었다. 판정 함수가 이미 pattern/reason 을 돌려주므로
                    #   그걸 버킷 키로 써서 한 번에 원인을 보이게 한다 (헌법 93).
                    _pat = result.get("pattern")
                    if _pat:
                        # 🎯 Fix 152: 패턴 B 는 순차 AND 게이트 4개이고
                        #   실패 지점마다 passed 값이 다르다 (0~3).
                        #   그 값을 버킷에 넣어야 「어느 게이트가 막는지」 한 번에 보인다.
                        #     B0 = was_bull 실패 (이전 상승 이력 없음)
                        #     B1 = OBV 4H 반전 실패
                        #     B2 = MACD 15m 반전 실패
                        #     B3 = RSI > 40 (과매도 회복 안 됨)
                        _ps = result.get("passed")
                        _bump(f"nd:{_pat}{_ps}" if _ps is not None else f"nd:{_pat}")
                    else:
                        _r = str(result.get("reason") or "")
                        if "extreme_bull" in _r or "정점 위험" in _r:
                            _bump("nd:extreme_bull")
                        elif "급등락 아님" in _r:
                            _bump("nd:not_moving")
                        elif "BB" in _r:
                            _bump("nd:bb_gate")
                        elif "OBV" in _r or "obv" in _r:
                            _bump("nd:obv")
                        elif "통과" in _r or "/7" in _r:
                            _bump("nd:signals_short")   # 7중 조건 미달
                        else:
                            _bump("nd:other")
                            if _reasons.get("nd:other", 0) <= 2:
                                logger.info(
                                    "[Fix151] %s not_detected 미분류 사유: %s",
                                    symbol, _r[:160],
                                )
                    continue
                confidence = float(result.get("confidence", 0))
                if confidence < MIN_CONFIDENCE:
                    _bump("confidence_below_min")
                    continue

                # Fix 65: OBV 절대값 검증 (사장님 사상! PENGUUSDT 사고 재발 방지!)
                try:
                    from app.services.obv_gate import check_obv_gate
                    obv_pass, obv_reason = check_obv_gate(bc, symbol, "LONG")
                    if not obv_pass:
                        logger.info("[auto_long_bottom+Fix65] %s skip: %s", symbol, obv_reason)
                        _bump("obv_gate")
                        continue
                except Exception as _obv_exc:
                    logger.warning("[auto_long_bottom+Fix65] %s obv_gate error: %s (fail-open)", symbol, _obv_exc)

                # Fix 66 P1: 양방향 실패 blocklist!
                try:
                    from app.services.bidirectional_blocklist import is_bidirectional_blocked
                    blocked, block_reason = is_bidirectional_blocked(db, symbol)
                    if blocked:
                        logger.info("[auto_long_bottom+Fix66] %s skip: %s", symbol, block_reason)
                        _bump("btc_or_blocked")
                        continue
                except Exception as _bl_exc:
                    logger.warning("[auto_long_bottom+Fix66] blocklist error: %s", _bl_exc)

                # Fix 66 P2: pump_dump_regime (LONG 금지!)
                try:
                    from app.services.pump_dump_regime import is_regime_blocked_for_long
                    regime_blocked, regime_reason = is_regime_blocked_for_long(bc, symbol)
                    if regime_blocked:
                        logger.info("[auto_long_bottom+Fix66] %s skip: %s", symbol, regime_reason)
                        _bump("regime_blocked")
                        continue
                except Exception as _rg_exc:
                    logger.warning("[auto_long_bottom+Fix66] regime error: %s", _rg_exc)

                # 9. 실 진입!
                new_strategy = _create_long_strategy(db, symbol, capital, bc)
                if not new_strategy:
                    skipped += 1
                    logger.info(
                        "[auto_long_bottom] ❌ %s 진입 실패 = skip (다음 사이클 재시도!)",
                        symbol,
                    )
                    continue

                # 🌟 Fix 87 P0 (2026-08-25 사장님!): -10% 손절 override!
                # 원 -5% = leverage 2x + 15m 알트 노이즈 = 자연 노이즈 손절!
                # 신 -10% = leverage 2x → 실 가격 5% = 15m 알트 노이즈 뛰어넘음!
                # 기존 활성 전략은 그대로! 신 진입만 -10%!
                try:
                    new_strategy.force_sl_enabled_override = True
                    new_strategy.force_sl_roi_override = Decimal("10")
                    db.commit()
                    logger.info(
                        "[auto_long_bottom+Fix87] 🛡️ %s SL override -10%% 적용 (strategy_id=%s, 2x 상향!)",
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
            "[auto_long_bottom] 완료: scanned=%d entered=%d skipped=%d used=%d/%d | 사유: "
            + (" ".join(f"{k}={v}" for k, v in sorted(_reasons.items(), key=lambda x: -x[1])) or "-"),
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
