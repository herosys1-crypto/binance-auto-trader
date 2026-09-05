"""📈 LONG 은 「급등 중」에만 — 실패가 많던 LONG 을 조정한다 (Fix 274).

## 사장님 사상 (2026-08-31 정정)

  "급등중에 조정은 **다시 급등**으로 간다고 했어 **바로 수익을 많이 낼수 있고** 했고
   급락한건 **언제 어떤 심볼이 급등하는 찾는게 힘들다**고 헀어"

즉 LONG 의 주력은 **「급등 중 조정」**이지 「아무 종목의 저점」이 아니다.
그런데 코드의 LONG 진입 경로는 24h 변동을 **제한하지 않았다** —
평범한 종목(24h +2%)의 저점 LONG 이 대부분이었고, 그게 손실의 거의 전부였다.

## 실측 (LONG 130건 / 12일, 진입 시점 캔들 복원)

**승자와 패자를 가르는 것:**

    지표                  승 중앙값   패 중앙값   효과크기
    **24h 변동%**        **+21.46**   **+2.28**   0.69   <- 승자는 급등 중
    15m RSI                 47.01       38.45     0.66
    72h 레인지 위치           0.684       0.557     0.49
    4H hist > 0             96.3%       65.0%     0.62
    15m hist 상승           40.7%       68.9%    -0.56   <- 🚨 오히려 반대

  🚨 **15m hist 가 이미 상승 중이면 오히려 진다.** 사장님 「급등 중 **조정**」이
     맞다 — 15m 은 아직 조정이어야 하고, 이미 오르고 있으면 늦은 것이다.

**게이트로 썼을 때 (Fix 270 4H 게이트가 이미 켜진 위에):**

    Fix270 만 (현재 상태)        30건 승률 43.3%    +12.15  건당  +0.40
    **Fix270 + 24h >= 15%**      20건 승률 **65.0%**  **+80.07**  건당 **+4.00**  <- 채택
    Fix270 + 24h >= 20%          16건      62.5%     +74.93       +4.68
    Fix270 + 24h >= 25%          10건      70.0%    +111.72      +11.17

  차단되는 것들:
    24h < 15%      85건 승률 **8.2%**  **-803.25**  건당 -9.45
    4H hist <= 0   37건 승률  2.7%      -665.22        -17.98

  과적합 검사 — **24h >= 15% 만 양쪽 절반이 모두 양수**:
    24h >= 10%   최근 -54.82(14건)  이전 +71.18(7건)
    **24h >= 15%   최근  +8.89(13건)  이전 +71.18(7건)**  <- 채택
    24h >= 20%   최근  -3.00(11건)  이전 +77.93(5건)

  현행 전체 130건 **-947.45** -> 게이트 적용 20건 **+80.07**.

## ⚠️ 더 조이면 오히려 나빠진다

레인지 위치(0.6+)와 15m 조정 조건을 **더하면** -3.02 -> -12.85 로 악화된다.
효과크기가 있었는데도 손익은 나빠졌다 — 「효과크기 != 손익」의 또 한 사례다.
조건은 **24h 급등 하나만** 더한다.

## ⚠️ 대가

LONG 진입이 130건 -> 20건 = **1/6.5** 로 준다.
지금 건당 -7.29 로 잃고 있으므로 줄이는 쪽이 맞다.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["check_long_surge", "long_surge_gate_enabled", "SETTING_KEY", "MIN_CHG_24H",
           "SETTING_SURGE_EXEMPT", "SURGE_PATTERNS", "surge_pattern_exempt_enabled"]

# 📈 Fix 347 (2026-09-04 사장님): "15% 심볼 롱 차단 이건 또 뭐지 차단 자체가없어 올라가면 롱으로 진입을 해야지"
#   이 게이트는 「급등 중이 아닌 종목의 저점 롱」을 거르는 용도다. 이미 올라가고 있는 자리에서
#   들어가는 급등 계열 패턴(상승 초입 SURGE_START / 급등중 조정 SURGE_PULLBACK)은 24h 가 아직
#   15% 가 안 됐어도(MINIMAXUSDT +8%) 롱이다 → 면제. 기본 ON.
SETTING_SURGE_EXEMPT = "long_surge_gate_surge_exempt"
SURGE_PATTERNS: tuple[str, ...] = ("SURGE_START", "SURGE_PULLBACK", "MULTIDAY_PULLBACK")   # Fix 352: 다일 조정 반등(당일은 −%) 도 면제

SETTING_KEY = "long_surge_gate_enabled"

# 실측: 10% 와 20% 는 표본 절반 중 한쪽이 음수. 15% 만 양쪽 다 양수.
MIN_CHG_24H: float = 15.0


def long_surge_gate_enabled(db) -> bool:
    """기본 OFF. LONG 진입을 1/6.5 로 줄이는 큰 변화라 명시적으로 켠다 (헌법 161)."""
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, SETTING_KEY)
        if row is None or row.value is None:
            return False
        return str(row.value).strip().lower() in ("1", "true", "on", "yes")
    except Exception as e:
        logger.warning("[Fix274] %s 조회 실패 = OFF: %s", SETTING_KEY, e)
        return False


def surge_pattern_exempt_enabled(db) -> bool:
    """급등 계열 패턴(SURGE_PATTERNS)을 이 게이트에서 면제할 것인가. 기본 **예** (Fix 347)."""
    if db is None:
        return True
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, SETTING_SURGE_EXEMPT)
        if row is None or row.value is None or not str(row.value).strip():
            return True
        return str(row.value).strip().lower() in ("1", "true", "on", "yes")
    except Exception as e:
        logger.warning("[Fix347] %s 조회 실패 = 면제 유지: %s", SETTING_SURGE_EXEMPT, e)
        return True


def check_long_surge(bc, symbol: str, side: str) -> tuple[bool, str, dict[str, Any]]:
    """LONG 이면 「24h 급등 중」인가. SHORT 은 이 게이트의 대상이 아니다.

    ⚠️ **fail-open** — 티커를 못 받았다고 매매를 멈추지 않는다.
       좋은 자리를 고르는 필터이지 안전장치가 아니다.
    """
    d: dict[str, Any] = {"side": side, "min_chg": MIN_CHG_24H}
    if str(side).upper() != "LONG":
        return True, "SHORT 은 대상 아님", d
    try:
        t = bc.get_24hr_ticker(symbol=symbol)
        if isinstance(t, list):
            t = t[0] if t else None
        if not t:
            return True, "티커 없음 (fail-open)", d
        chg = float(t.get("priceChangePercent") or 0)
        d["chg_24h"] = chg
        if chg < MIN_CHG_24H:
            return False, f"24h 변동 {chg:+.1f}% < {MIN_CHG_24H:.0f}% (급등 중 아님)", d
        return True, f"24h {chg:+.1f}% = 급등 중", d
    except Exception as e:
        logger.debug("[Fix274] %s 티커 조회 실패 (fail-open): %s", symbol, e)
        d["error"] = str(e)[:200]
        return True, f"조회 실패 (fail-open): {e}", d
