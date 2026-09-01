"""📐 4H 추세 게이트 — 「확정된 흐름」이 내 편인가 (Fix 270).

## 사장님 사상 ⑥

  "**4시간봉이 확정된 흐름(방향·국면)**, 15분봉은 진입 타이밍만"

사장님이 차트를 보내시며 하신 말씀:
  "장기 4시간 차트 **macd 와 cci 움직임**을 보면 **조정와 지지**를 알수 있고
   단기 15분차트는 하락후 상승하는 차트를 볼수 있어 ...
   포지션 진입에 **조정인지 하락인지 구분** 할때 참고 해줘"

## 실측 — 이 게이트가 손익을 뒤집는다

진입 시점 4시간봉을 복원해 「통과한 것만 진입했다면」을 계산했다 (최근 10일 158건):

    게이트                        건수   승률       합계        건당
    **게이트 없음 (현행)**         158  21.5%  **-3,599.87**  **-22.78**
    hist 상승중                    53  39.6%       +35.69      +0.67
    CCI 부호 내 편                 87  32.2%      -399.17      -4.59
    hist 상승중 AND CCI 부호        26  65.4%      +132.47      +5.09
    **hist 상승중 AND hist > 0**    33  **57.6%**  **+183.32**  **+5.56**   <- 채택

방향별 (채택안):
    LONG   게이트 없음 -13.51/건  ->  게이트 -0.51/건
    SHORT  게이트 없음 -30.16/건  ->  게이트 **+12.74/건**

과적합 검사 — **양쪽 절반 모두 음수에서 양수로**:
    최근 절반  +181.62 (22건)
    이전 절반    +1.70 (11건)

CCI 를 추가해도 결과가 **완전히 같았다**(3중 = hist상승+CCI). 즉 이 표본에서
`hist > 0` 이 CCI 부호를 포함한다. 조건은 적을수록 좋으므로 CCI 는 뺀다.

## 🚨 원시값이 아니라 「방향」으로 쓴다

    4H MACD hist 「상승 중」   효과크기 **2.08**   <- 최대급
    4H CCI 부호 내 편          효과크기 2.00
    4H MACD hist **원시값**    효과크기 **0.01**   <- 가격 단위라 무의미
    4H MACD > signal           효과크기 0.00

MACD hist 는 가격 단위라 심볼마다 스케일이 달라 그대로 쓰면 판별력이 없다.
**부호와 변화 방향**으로 바꿔야 살아난다.

## 🚨 같은 지표라도 용도가 다르면 결과가 다르다

이 축을 **반대매매 타이밍**에 썼을 때는 -118 ~ -145 USDT 로 **해로웠다**.
여기서는 **종목 선정**(진입 여부) 용도다. 다른 용도로 옮길 때는 반드시 그 용도로 다시 재라.

## ⚠️ 대가

통과율이 158건 중 33건 = **21%** 다. 진입이 약 1/5 로 줄어든다.
지금은 건당 -22.78 로 잃고 있으므로 줄이는 쪽이 맞지만, 흑자로 돌아선 뒤에는
「기회를 너무 줄이는가」를 다시 봐야 한다.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["check_trend_4h", "trend_4h_gate_enabled", "SETTING_KEY", "TF", "LIMIT"]

SETTING_KEY = "trend_4h_gate_enabled"
TF = "4h"
LIMIT = 60          # MACD(12,26,9) 안정화에 충분


def trend_4h_gate_enabled(db) -> bool:
    """기본 OFF. 진입을 1/5 로 줄이는 큰 변화라 명시적으로 켠다 (헌법 161)."""
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, SETTING_KEY)
        if row is None or row.value is None:
            return False
        return str(row.value).strip().lower() in ("1", "true", "on", "yes")
    except Exception as e:
        logger.warning("[Fix270] %s 조회 실패 = OFF: %s", SETTING_KEY, e)
        return False


def _ema(v: list[float], n: int) -> list[float]:
    k = 2.0 / (n + 1)
    out = [v[0]]
    for x in v[1:]:
        out.append(x * k + out[-1] * (1 - k))
    return out


def _macd_hist(closes: list[float]) -> list[float] | None:
    if len(closes) < 40:
        return None
    fast, slow = _ema(closes, 12), _ema(closes, 26)
    macd = [a - b for a, b in zip(fast, slow)]
    sig = _ema(macd, 9)
    return [a - b for a, b in zip(macd, sig)]


def check_trend_4h(bc, symbol: str, side: str) -> tuple[bool, str, dict[str, Any]]:
    """4H 흐름이 이 방향을 지지하는가.

    Returns:
        (통과, 사유, 상세)

    ⚠️ **fail-open** 이다 — 데이터를 못 받았다고 매매를 멈추면 안 된다.
       이건 「더 좋은 자리만 고르는」 필터이지 안전장치가 아니다.
       (자본을 늘리거나 방향을 뒤집는 판정이라면 fail-closed 여야 한다.)
    """
    d: dict[str, Any] = {"tf": TF, "side": side}
    try:
        kl = bc.get_klines(symbol=symbol, interval=TF, limit=LIMIT)
        if not kl or len(kl) < 40:
            return True, "4H 데이터 부족 (fail-open)", d
        closes = [float(k[4]) for k in kl]
        hist = _macd_hist(closes)
        if hist is None or len(hist) < 2:
            return True, "MACD 계산 불가 (fail-open)", d

        # 방향 보정: 내 편이면 +. LONG 은 그대로, SHORT 은 부호를 뒤집는다.
        sgn = 1.0 if str(side).upper() == "LONG" else -1.0
        now_v = hist[-1] * sgn
        rising = (hist[-1] - hist[-2]) * sgn > 0
        # 스케일 무관 비교를 위해 가격으로 정규화 (기록·로그용)
        d.update(hist_signed=now_v, rising=rising,
                 hist_norm_pct=now_v / closes[-1] * 100 if closes[-1] else None)

        if not rising:
            return False, "4H MACD hist 가 내 편으로 상승 중이 아님", d
        if now_v <= 0:
            return False, "4H MACD hist 가 아직 내 편 부호가 아님", d
        return True, "4H 흐름 지지 (hist 상승 + 내 편 부호)", d
    except Exception as e:
        # fail-open — 필터가 매매를 멈추게 하지 않는다
        logger.debug("[Fix270] %s %s 4H 판정 실패 (fail-open): %s", symbol, side, e)
        d["error"] = str(e)[:200]
        return True, f"판정 실패 (fail-open): {e}", d
