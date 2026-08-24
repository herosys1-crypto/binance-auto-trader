"""Fix 66 P2: 급등 완성 후 하락 국면 감지!

사장님 사상 (PENGUUSDT/XPLUSDT 학습!):
- 최근 3일 급등 (+30%+) → 하락 시작!
- = "pump_completed_dumping" 국면!
- LONG 절대 금지!
- SHORT도 = 하락 중반 이후 = skip! (반등 위험!)
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

PUMP_THRESHOLD_PCT = 30.0  # 3일 +30%+ = 급등!
DUMP_THRESHOLD_PCT = -5.0  # 최근 12h -5%+ = 하락 시작!


def check_pump_dump_regime(bc, symbol) -> tuple:
    """급등 완성 후 하락 국면 감지!
    Returns: (regime, detail)
        regime = "pump_active" (상승 중, LONG OK, SHORT 위험!)
                 "pump_completed_dumping" (하락 국면! LONG 금지, SHORT 늦음!)
                 "normal" (일반)
                 "unknown"
    """
    try:
        # 4H 30봉 (5일) = 급등/하락 판단
        klines = bc.get_klines(symbol=symbol, interval="4h", limit=30)
        if not klines or len(klines) < 18:
            return ("unknown", "insufficient_klines")

        # 3일 = 18봉 = 최근 18봉
        closes = [float(k[4]) for k in klines]
        c_now = closes[-1]
        c_3d_ago = closes[-18]
        c_12h_ago = closes[-3]

        pump_pct = ((c_now - c_3d_ago) / c_3d_ago) * 100 if c_3d_ago > 0 else 0
        recent_pct = ((c_now - c_12h_ago) / c_12h_ago) * 100 if c_12h_ago > 0 else 0

        # 최고가 (18봉!)
        peak = max(closes[-18:])
        pct_from_peak = ((c_now - peak) / peak) * 100 if peak > 0 else 0

        # 판정:
        # 1. pump_completed_dumping: 3일 +30% 급등 + 정점 대비 -5%+ 하락
        if pump_pct >= PUMP_THRESHOLD_PCT and pct_from_peak <= DUMP_THRESHOLD_PCT:
            detail = f"3일 +{pump_pct:.1f}% 급등 완성 → 정점 대비 {pct_from_peak:.1f}% 하락!"
            return ("pump_completed_dumping", detail)

        # 2. pump_active: 3일 +30% 급등 + 정점 근처 (-5% 이내)
        if pump_pct >= PUMP_THRESHOLD_PCT and pct_from_peak > DUMP_THRESHOLD_PCT:
            detail = f"3일 +{pump_pct:.1f}% 급등 진행 중 (정점 대비 {pct_from_peak:.1f}%)"
            return ("pump_active", detail)

        # 3. normal
        return ("normal", f"3일 {pump_pct:+.1f}% (정점 {pct_from_peak:+.1f}%)")
    except Exception as e:
        logger.warning("[Fix66/regime] %s: %s", symbol, e)
        return ("unknown", f"error: {e}")


def is_regime_blocked_for_long(bc, symbol) -> tuple:
    """LONG 진입 = pump_completed_dumping = skip!"""
    regime, detail = check_pump_dump_regime(bc, symbol)
    if regime == "pump_completed_dumping":
        return (True, f"LONG 금지: {detail}")
    return (False, f"regime:{regime}")


def is_regime_blocked_for_short(bc, symbol) -> tuple:
    """SHORT 진입 = pump_completed_dumping = 하락 중반 이후 = skip!
    (반등 위험!)
    """
    regime, detail = check_pump_dump_regime(bc, symbol)
    if regime == "pump_completed_dumping":
        # 하락 진행 중 = SHORT도 늦음!
        return (True, f"SHORT 늦음: {detail}")
    return (False, f"regime:{regime}")
