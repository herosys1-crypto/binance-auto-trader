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

# Fix 65 상수 (사장님 사상!)
# OBV 극단 임계값 = 심볼별 상대적이지만 = 절대값 기준!
# 4H OBV 절대값이 = 유통량 대비 매우 크면 = 극단!
# 실제: OBV / 최근 봉의 볼륨 = 상대적 비율 판단!

OBV_EXTREME_RATIO = 20.0  # OBV / avg_volume >= 20 = 극단!


def _get_obv_direction_4h(bc, symbol) -> tuple:
    """4H OBV 방향 + 절대값 상대 비율 판단!

    Returns: (direction, ratio, obv_now)
        direction = "up" / "down" / "flat"
        ratio = OBV / avg_volume (절대값!)
        obv_now = 현재 OBV 값
    """
    try:
        from app.services.chart_analyzer import ChartAnalyzer
        result = ChartAnalyzer.analyze_timeframe(bc, symbol, "4h")
        if not result:
            return ("unknown", 0.0, 0.0)

        obv_slope = result.get("obv_slope")
        obv_now = result.get("obv_now") or 0
        avg_vol = result.get("avg_volume") or 1

        # 방향
        if obv_slope is None:
            direction = "unknown"
        elif obv_slope > 0.5:
            direction = "up"
        elif obv_slope < -0.5:
            direction = "down"
        else:
            direction = "flat"

        # 절대값 상대 비율
        ratio = abs(float(obv_now)) / max(abs(float(avg_vol)), 1.0)

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
            if direction == "down" and ratio >= OBV_EXTREME_RATIO:
                reason = f"LONG skip: 4H OBV 극단 하락 (ratio={ratio:.1f} obv={obv_now:.0f})"
                logger.warning("[Fix65/gate] %s %s: %s", symbol, side, reason)
                return (False, reason)
            # 4H OBV 방향 = 하락 지속 = LONG 위험!
            if direction == "down":
                reason = f"LONG skip: 4H OBV 하락 지속 (ratio={ratio:.1f})"
                logger.info("[Fix65/gate] %s %s: %s", symbol, side, reason)
                return (False, reason)

        # SHORT 진입 시:
        elif side == "SHORT":
            # 4H OBV 매우 큰 양수 = 세력 매집 = SHORT 금지!
            if direction == "up" and ratio >= OBV_EXTREME_RATIO:
                reason = f"SHORT skip: 4H OBV 극단 상승 (ratio={ratio:.1f} obv={obv_now:.0f})"
                logger.warning("[Fix65/gate] %s %s: %s", symbol, side, reason)
                return (False, reason)
            # 4H OBV 방향 = 상승 지속 = SHORT 위험!
            if direction == "up":
                reason = f"SHORT skip: 4H OBV 상승 지속 (ratio={ratio:.1f})"
                logger.info("[Fix65/gate] %s %s: %s", symbol, side, reason)
                return (False, reason)

        # 통과!
        return (True, f"pass:{direction}_ratio_{ratio:.1f}")
    except Exception as e:
        logger.warning("[Fix65/gate] %s: %s", symbol, e)
        return (True, "error_pass")  # fail-open (안전!)
