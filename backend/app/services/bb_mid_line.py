"""📐 볼밴 **중단선** 4종 진입 — 별도 전략 (Fix 278).

## 사장님 원문 (2026-09-02)

  "상승중 볼밴 **중단지지**와 **중단저항** 그리고 **중단돌파** **중단하락돌파**에도
   우리 시스템로직이 상승과 하락이 판단되면 이것도 포지션에 진입해줘
   **이전략은 빼줘**"
  "이전략은 **15분 차트를 기준**이야 **1시간과 4시간은 참고용**으로 사용해줘"

「이전략은 빼줘」= 볼밴 분할에서 **분리**하라는 뜻으로 읽었다 (급등 사다리 때와 같은
패턴 — 새 아이디어는 별도 전략). 그래서 pump_split 의 중단 모드는 Fix 277 로 껐고
(설정 `pump_split_long_trend_enabled`), 중단선 판정은 여기로 옮긴다.

## 4종 (사장님이 지정한 방향 그대로)

    중단 지지   = 상승 중 중단선을 찍고 위로 마감      -> LONG
    중단 저항   = 하락 중 중단선을 찍고 아래로 마감    -> SHORT
    중단 상향돌파 = 종가가 중단선을 아래->위로 통과     -> LONG
    중단 하락돌파 = 종가가 중단선을 위->아래로 통과     -> SHORT

🚨 **지금까지의 코드는 돌파 2종의 방향이 사장님과 반대였다.**
   pump_split 중단 모드는 `종가 < 중단선` 이면 **LONG** 이었다 (평균회귀 해석).
   사장님은 「중단 하락돌파 -> SHORT」(추세 추종)이다. 실측도 사장님 쪽이 맞다:

     중단 하락돌파 -> LONG (옛 동작)   -215.46 | 전 +347.26 후 -554.86   ❌
     중단 하락돌파 -> SHORT (사장님)   +293.73 | 전 -166.11 후 +503.64
     중단 하락돌파 -> SHORT + 4H 확인  +655.93 | 전  +89.10 후 +571.69   ✅

## 실측 (130심볼 x 15m 1000봉 = 10.4일, TP+5%/SL-10% ROI, 자본 100, 레버 2)

    규칙                     방향   건수  승률   합계     건당   전/후반
    중단 저항 (15m 만)       SHORT 1188 69.7% +785.11 +0.661  +294/+558  ✅ 채택
    중단 저항 (+15m hist)    SHORT 1010 69.2% +633.90 +0.628  +214/+468
    중단 하락돌파 (15m 만)   SHORT 1384 66.5% +293.73 +0.212  -166/+504  ❌ 전반 음수
    중단 하락돌파 (+4H 확인) SHORT  886 70.5% +655.93 +0.740   +89/+572  ✅ 채택
    중단 지지 (15m 만)       LONG  1117 64.5% +214.25 +0.192  +535/-424  ❌ 후반 음수
    중단 지지 (+4H 확인)     LONG   926 65.3% +182.37 +0.197  +329/-160  ❌
    중단 상향돌파 (15m 만)   LONG  1332 61.1% -476.01 -0.357   +86/-590  ❌
    중단 상향돌파 (+4H 확인) LONG   891 64.1%  +90.05 +0.101  +330/-302  ❌

  → **SHORT 2종만 과적합 검사를 통과한다.** LONG 2종은 어떤 조합도 후반이 음수다.
    그래서 SHORT 2종은 기본 ON, LONG 2종은 **기본 OFF** 로 넣는다
    (사장님이 4종을 다 지시하셨으므로 코드는 넣되, 켜는 것은 사장님 판단).

## 「우리 시스템 로직이 상승과 하락이 판단되면」

  🚨 **15m MACD 로 방향을 판정하면 전부 나빠진다** (실측):
       중단 지지 LONG  +214 -> **-294**
       중단 저항 SHORT +785 -> +634
       중단 하락돌파   +294 -> +260
     사장님 사상 ⑥ 「4H = 확정된 흐름 / 15m = 진입 타이밍」이 여기서도 맞다.
     방향은 4H 가 본다. 15m 은 **자리(중단선 터치·돌파)** 를 본다.

  그래서 사장님 "15분 기준 / 1H·4H 참고"를 이렇게 구현한다:
     • **자리(트리거) = 15분봉 중단선** — 전부 15m 로 판정한다 (사장님 「기준」)
     • **1H·4H = 참고** — 항상 계산해 기록/화면에 남긴다
     • 4H 확인을 **필수로 거는 것은 「중단 하락돌파」 하나뿐**이다.
       실측이 명확히 요구하기 때문이고(전반 -166 -> +89), 규칙마다 설정으로 끌 수 있다.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "PATTERNS", "PATTERN_SIDE", "PATTERN_DEFAULT_ON", "PATTERN_NEEDS_4H",
    "slope_up", "slope_dir", "evaluate_mid_line", "SLOPE_BARS",
]

# 중단선 기울기를 볼 봉수 (실측에 쓴 값)
SLOPE_BARS: int = 6

PATTERNS = ("mid_support", "mid_resist", "mid_break_up", "mid_break_down")

PATTERN_SIDE = {
    "mid_support": "LONG",      # 중단 지지
    "mid_resist": "SHORT",      # 중단 저항
    "mid_break_up": "LONG",     # 중단 상향돌파
    "mid_break_down": "SHORT",  # 중단 하락돌파
}

PATTERN_LABEL = {
    "mid_support": "중단 지지",
    "mid_resist": "중단 저항",
    "mid_break_up": "중단 상향돌파",
    "mid_break_down": "중단 하락돌파",
}

# 실측에서 과적합 검사(전/후반 모두 양수)를 통과한 것만 기본 ON
PATTERN_DEFAULT_ON = {
    "mid_support": False,      # 후반 -424 (4H 걸어도 -160)
    "mid_resist": True,        # +785.11, 전 +294 / 후 +558
    "mid_break_up": False,     # -476.01 (4H 걸어도 후반 -302)
    "mid_break_down": True,    # 4H 필수: +655.93, 전 +89 / 후 +572
}

# 4H 확인을 **필수**로 거는 패턴 (실측이 요구하는 것만)
PATTERN_NEEDS_4H = {
    "mid_support": False,
    "mid_resist": False,       # 4H 를 걸면 오히려 +785 -> +662
    "mid_break_up": False,
    "mid_break_down": True,    # 안 걸면 전반 -166 = 과적합 실패
}


def slope_dir(mid: list, idx: int, bars: int = SLOPE_BARS) -> int | None:
    """중단선 기울기. +1 상승 / -1 하락 / 0 **평탄** / None 값없음.

    🚨 평탄(0)을 따로 두는 이유: 실측에 쓴 판정식이 `mid[i] > mid[i-6]`(지지) 와
       `mid[i] < mid[i-6]`(저항) 로 **양쪽 다 엄격**이었다. 「상승 아님 = 하락」으로
       구현하면 평탄한 구간이 전부 저항으로 들어와 **측정과 다른 규칙**이 된다.
    """
    j = idx - bars
    if idx < 0 or j < 0 or idx >= len(mid) or mid[idx] is None or mid[j] is None:
        return None
    a, b = float(mid[idx]), float(mid[j])
    return 1 if a > b else (-1 if a < b else 0)


def slope_up(mid: list, idx: int, bars: int = SLOPE_BARS) -> bool | None:
    """(기록용) 중단선이 bars 봉 전보다 위인가. 값이 없으면 None."""
    d = slope_dir(mid, idx, bars)
    return None if d is None else d > 0


def evaluate_mid_line(
    closes: list,
    highs: list,
    lows: list,
    mid: list,
    *,
    slope_bars: int = SLOPE_BARS,
) -> dict[str, Any]:
    """15분 **완료봉**에서 중단선 4종을 판정한다.

    🚨 판정봉은 `closes[-2]` 다 — `closes[-1]` 은 아직 안 끝난 봉이라
       그 봉이 되돌리면 없던 신호가 된다 (Fix 216 교훈).

    반환: {"idx", "mid", "close", "slope_up", "hits": [패턴명...], "detail": {...}}
    """
    out: dict[str, Any] = {"hits": [], "detail": {}}
    n = len(closes)
    if n < slope_bars + 3 or len(mid) < n:
        out["why"] = f"봉 부족({n})"
        return out

    i = n - 2                              # 마지막 완료봉
    if mid[i] is None or mid[i - 1] is None:
        out["why"] = "중단선 값 없음"
        return out

    m, m_prev = float(mid[i]), float(mid[i - 1])
    c, c_prev = float(closes[i]), float(closes[i - 1])
    hi, lo = float(highs[i]), float(lows[i])
    sdir = slope_dir(mid, i, slope_bars)
    up = None if sdir is None else sdir > 0

    out.update(idx=i, mid=m, close=c, slope_up=up)
    out["slope_dir"] = sdir
    out["detail"] = {
        "mid": m, "close": c, "high": hi, "low": lo,
        "close_prev": c_prev, "mid_prev": m_prev,
        "slope_up": up, "slope_dir": sdir,
    }

    # 중단 지지 = **상승 중**(엄격) 중단선을 찍고(저가가 닿음) 위로 마감
    if sdir == 1 and lo <= m and c > m:
        out["hits"].append("mid_support")
    # 중단 저항 = **하락 중**(엄격) 중단선을 찍고(고가가 닿음) 아래로 마감
    if sdir == -1 and hi >= m and c < m:
        out["hits"].append("mid_resist")
    # 중단 상향돌파 = 아래 -> 위 통과
    if c_prev <= m_prev and c > m:
        out["hits"].append("mid_break_up")
    # 중단 하락돌파 = 위 -> 아래 통과
    if c_prev >= m_prev and c < m:
        out["hits"].append("mid_break_down")

    out["why"] = (
        f"중단 {m:.6g} / 종가 {c:.6g} / 기울기 "
        f"{ {1: '상승', -1: '하락', 0: '평탄'}.get(sdir, '?') } "
        f"/ 적중 {','.join(PATTERN_LABEL[h] for h in out['hits']) or '없음'}"
    )
    return out
