"""Fix 65: OBV 절대값 검증 공통 서비스

사장님 verbatim: "OBV = 급등/급락 결정!"
- 4H OBV 매우 큰 음수 = LONG 금지 (세력 이탈!)
- 4H OBV 매우 큰 양수 = SHORT 금지 (세력 매집!)
- 다중 시간대 OBV 불일치 = 관망!
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Fix 141: OBV 기울기/평균거래량 산출 창 (4H 봉 기준 = 약 3~4일)
OBV_SLOPE_LOOKBACK = 20

# Fix 65 상수 (사장님 사상!)
# OBV 극단 임계값 = 심볼별 상대적이지만 = 절대값 기준!
# 4H OBV 절대값이 = 유통량 대비 매우 크면 = 극단!
# 실제: OBV / 최근 봉의 볼륨 = 상대적 비율 판단!

# 🚨 Fix 141: ratio 지표 자체가 잘못돼 있었다.
#   옛: |누적 OBV| / 봉당 평균거래량  → 봉 수에 비례해 커진다 (80봉이면 ~80)
#       임계 20 은 거의 항상 초과 = 의미 없는 수치
#   신: |누적 OBV| / (평균거래량 × 봉수) = 0~1
#       "전체 거래량 중 몇 %가 한 방향이었는가" = 세력 확신도
#   0.6 = 전체의 60% 가 한 방향 = 진짜 극단으로 본다
OBV_EXTREME_RATIO = 0.6


def _get_obv_direction_4h(bc, symbol) -> tuple:
    """4H OBV 방향 + 절대값 상대 비율 판단!

    Returns: (direction, ratio, obv_now)
        direction = "up" / "down" / "flat"
        ratio = OBV / (avg_volume x bars)  — **부호 있음** (Fix 227)
        obv_now = 현재 OBV 값
    """
    try:
        from app.services.chart_analyzer import ChartAnalyzer
        result = ChartAnalyzer.analyze_timeframe(bc, symbol, "4h")
        if not result:
            return ("unknown", 0.0, 0.0)

        # ═══════════════════════════════════════════════════════════════════
        # 🚨 Fix 141 (2026-08-26): 이 게이트는 「존재하지 않는 키」를 읽고 있었다
        #
        # analyze_timeframe(chart_analyzer.py) 이 실제로 돌려주는 키는
        #   closes / volumes / obv / rsi_now / rsi_prev / macd_hist /
        #   cci_now / cci_prev / bb_up_last / bb_mid_last / bb_lo_last / kl_count
        # 이며 obv_slope / obv_now / avg_volume 은 「없다」.
        # → obv_slope 가 항상 None → direction="unknown" → check_obv_gate 가
        #   무조건 (True, "unknown_pass") 로 통과.
        # → OBV 게이트를 쓰는 워커 6개 전부에서 이 안전장치가 무효였다.
        #   (auto_long_at_bottom / auto_short_at_top / bb_upper_breakout_short /
        #    long_bottom_detector / macd_reversal_15m / pump_dump_early_detector)
        #
        # 사장님 사상에서 OBV 는 「지속성」의 핵심 지표인데 그게 죽어 있었다.
        # → 실제 반환값(obv 리스트, volumes)에서 직접 산출한다.
        # ═══════════════════════════════════════════════════════════════════
        _obv = result.get("obv") or []
        _vols = result.get("volumes") or []

        obv_now = float(_obv[-1]) if _obv else 0.0

        # 기울기: 창 진폭 대비 % (심볼 스케일 차이를 제거해야 임계 비교가 의미를 갖는다)
        obv_slope = None
        try:
            from app.services.mtf_snapshot import _slope_pct
            obv_slope = _slope_pct([float(x) for x in _obv], OBV_SLOPE_LOOKBACK)
        except Exception as _se:
            logger.warning("[Fix141/obv] %s 기울기 산출 실패: %s", symbol, _se)

        # 평균 거래량 (ratio 의 분모)
        try:
            _recent = [float(v) for v in _vols[-OBV_SLOPE_LOOKBACK:]] if _vols else []
            avg_vol = (sum(_recent) / len(_recent)) if _recent else 1.0
        except Exception:
            avg_vol = 1.0
        if avg_vol <= 0:
            avg_vol = 1.0

        # 방향
        if obv_slope is None:
            direction = "unknown"
        elif obv_slope > 0.5:
            direction = "up"
        elif obv_slope < -0.5:
            direction = "down"
        else:
            direction = "flat"

        # 🚨 Fix 227 (2026-08-30): **부호를 지킨다.**
        #
        #   옛 코드는 abs(obv_now) 였다. 그런데 이 파일의 명세(맨 위 docstring)는
        #       "4H OBV 매우 큰 **음수** = LONG 금지 (세력 이탈)"
        #       "4H OBV 매우 큰 **양수** = SHORT 금지 (세력 매집)"
        #   이다. 절대값을 쓰면 **부호가 사라져** 명세가 뒤집힌다:
        #
        #     obv_now = +49,000,000 (13일 매집 극단 = 세력이 사 모으는 중)
        #     direction = 'down'    (최근 20봉 기울기만 하락)
        #     → 옛 코드: ratio 0.61 >= 0.6 → **LONG 차단**
        #        로그: "LONG skip: 4H OBV 극단 하락 (obv=+49000000)"  ← 양수인데 「하락」
        #
        #   사장님 2026-08-30 원칙과 정면으로 충돌한다:
        #     "볼밴 하단까지 갔다가도 **obv가 강하면 이것도 다시 상승으로 전환**된다고 봐야해"
        #   OBV 가 가장 강할 때가 LONG 자리인데, 바로 그때 시스템이 LONG 을 막고 있었다.
        #
        #   방향(20봉)과 크기(전체 누적)의 창이 다른 것도 원인이다. 부호를 살리면
        #   「누적은 +인데 최근만 하락」이 자연히 통과한다.
        _bars = max(len(_obv), 1)
        ratio = obv_now / max(abs(avg_vol) * _bars, 1.0)

        return (direction, ratio, float(obv_now))
    except Exception as e:
        logger.warning("[Fix65/obv_4h] %s: %s", symbol, e)
        return ("unknown", 0.0, 0.0)


def check_obv_gate(bc, symbol: str, side: str) -> tuple:
    """Fix 65: OBV 절대값 검증 (진입 워커 공통!)

    사장님 사상:
    - LONG + 4H OBV 매우 큰 음수 = skip! (세력 이탈!)
    - SHORT + 4H OBV 매우 큰 양수 = skip! (세력 매집!)
    - unknown = 통과 (안전 fail-open!)

    Returns:
        (bool, str) = (통과 여부, 이유)
    """
    try:
        direction, ratio, obv_now = _get_obv_direction_4h(bc, symbol)

        # unknown = fail-open (다른 지표에 맡김!)
        if direction == "unknown":
            return (True, "unknown_pass")

        # LONG 진입 시:
        if side == "LONG":
            # 4H OBV 매우 큰 음수 = 세력 이탈 = LONG 금지!
            # Fix 227: 누적 OBV 가 **음수 극단**일 때만 = 진짜 세력 이탈
            if direction == "down" and ratio <= -OBV_EXTREME_RATIO:
                reason = f"LONG skip: 4H OBV 극단 하락 (ratio={ratio:+.3f} obv={obv_now:.0f})"
                logger.warning("[Fix65/gate] %s %s: %s", symbol, side, reason)
                return (False, reason)
            # 🚨 Fix 141: 「방향만으로 무조건 차단」 제거!
            #   사장님 LONG 시나리오 1 = "급락 후 반등" → 급락 종목은 OBV 가 하락 상태다.
            #   그걸 무조건 막으면 사장님이 원하는 진입을 정확히 차단하게 된다.
            #   (Fix 114 의 24h 절대 필터와 같은 실수)
            #   → 극단(ratio >= OBV_EXTREME_RATIO) 만 남긴다 = 세력 이탈 방어는 유지.
            if direction == "down":
                logger.info(
                    "[Fix141/gate] %s LONG: 4H OBV 하락이지만 극단 아님 "
                    "(ratio=%.3f < %.2f) = 통과 (반등 진입 허용)",
                    symbol, ratio, OBV_EXTREME_RATIO,
                )

        # SHORT 진입 시:
        elif side == "SHORT":
            # 4H OBV 매우 큰 양수 = 세력 매집 = SHORT 금지!
            # Fix 227: 누적 OBV 가 **양수 극단**일 때만 = 진짜 세력 매집
            if direction == "up" and ratio >= OBV_EXTREME_RATIO:
                reason = f"SHORT skip: 4H OBV 극단 상승 (ratio={ratio:+.3f} obv={obv_now:.0f})"
                logger.warning("[Fix65/gate] %s %s: %s", symbol, side, reason)
                return (False, reason)
            # 🚨 Fix 141: 헌법 72 = "급등해서 볼밴 상단돌파 했을때 마틴게일 진입"
            #   급등 종목은 OBV 가 상승 상태다. 방향만으로 막으면 헌법 72 가 영구 봉쇄된다.
            #   → 극단만 차단.
            if direction == "up":
                logger.info(
                    "[Fix141/gate] %s SHORT: 4H OBV 상승이지만 극단 아님 "
                    "(ratio=%.3f < %.2f) = 통과 (헌법 72 정점 진입 허용)",
                    symbol, ratio, OBV_EXTREME_RATIO,
                )

        # 통과!
        return (True, f"pass:{direction}_ratio_{ratio:+.2f}")
    except Exception as e:
        logger.warning("[Fix65/gate] %s: %s", symbol, e)
        return (True, "error_pass")  # fail-open (안전!)
