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

# ══════════════════════════════════════════════════════════════════════
# 🚨 Fix 330 (2026-09-03 사장님 정정) — 4H 는 「거부권」이 아니라 「참고」다
#
# 사장님 원문:
#   "**15분이 기준이고 4시간을 참고**하고 4시간 장기 흐름을 판단하는 차트라고
#    그렇게 이야기를 했으고 차트전문가라면 **4시간 차트의 의미는 중단기 지속적인
#    흐름을 판단하는 정도** 차트라는걸 알잖아"
#
# 이 파일의 원 설계는 4H 를 **통과 조건**으로 썼다. 그 결과 실측:
#
#     최근 6시간 [Fix270/4H]   차단 1,546건 / 통과 52건 = **통과율 3.3%**
#     (문서에는 21% 라고 적혀 있는데 실제로는 그보다 훨씬 빡빡했다)
#
# 🚨 **정점/저점 반전 전략과는 구조적으로 충돌한다.**
#   사장님 사상 ①: "급등 정점에서, 지표 최고점에서 하락·지지 여러번 반복 후 하락 시작"
#   → 정점 SHORT 는 **정의상 4H 가 아직 안 꺾인 자리**에서 잡는 것이다.
#     그런데 이 게이트는 "4H hist 가 이미 내 편으로 상승 중 AND 내 편 부호"를 요구한다.
#     = "이미 하락이 시작된 뒤에만 SHORT 하라" = **정점이 아니라 추세추종**이다.
#
#   실제 피해: 사다리(10/300/600)를 켠 2026-09-03 07:22 이후
#            v219 정점 SHORT 가 **단 한 건도 생성되지 않아** 사다리가 도는지조차
#            확인할 수 없었다. 사장님 루프(1단계 → 부분손절 → 2단계 → …)의
#            **출발점 자체가 막혀 있었다.**
#
# 그래서 **전략 종류로 나눈다**:
#   · 반전 전략(정점 SHORT / 저점 LONG) → 4H 는 **참고만**. 막지 않는다.
#   · 그 외(추세 편승 계열)            → 기존대로 통과 조건 유지.
#
# ⚠️ 게이트를 전부 여는 것이 아니다. 아래 실측(게이트 없음 158건 -3,599.87)이
#   말하는 위험은 그대로 있다. 다만 그 측정은 **다른 게이트가 없던 시절**의 것이고,
#   지금은 Fix 111(정점 확인 2/2 꺾임) · Fix 303 · Fix 310/325/328 · Fix 327 ·
#   obv_gate 가 앞단에 겹겹이 있다. 반전 전략에 한해 4H 를 참고로 내린다.
#
# 🚨 되돌리기: `trend_4h_reversal_exempt = 0` 이면 예전처럼 반전 전략도 막는다.
# ══════════════════════════════════════════════════════════════════════

SETTING_REVERSAL_EXEMPT = "trend_4h_reversal_exempt"   # 기본 ON (사장님 정정)

#: 반전(정점/저점) 계열 — 4H 를 참고로만 쓴다
REVERSAL_MARKERS: tuple[str, ...] = (
    "SAJANGNIM_TOP",        # v219 급등 정점 SHORT
    "SAJANGNIM_BOTTOM",     # v219 급락 저점 LONG
    "TOP_REVERSAL",
    "BOTTOM_REVERSAL",
)


def reversal_exempt_enabled(db) -> bool:
    """반전 전략에서 4H 를 참고로만 쓸 것인가 (사장님 정정 = 기본 ON)."""
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, SETTING_REVERSAL_EXEMPT)
        if row is None or row.value is None or not str(row.value).strip():
            return True                     # 기본 ON
        return str(row.value).strip().lower() in ("1", "true", "on", "yes")
    except Exception as e:
        logger.warning("[Fix330] %s 조회 실패 → 기본 ON: %s", SETTING_REVERSAL_EXEMPT, e)
        return True


def is_reversal_strategy(strategy_type_or_suffix: object) -> bool:
    """정점/저점 **반전** 전략인가.

    반전 전략은 「4H 가 아직 안 꺾인 자리」를 노리므로 4H 를 통과 조건으로
    쓰면 안 된다 (사장님 정정: 15분이 기준, 4시간은 참고).
    """
    s = str(strategy_type_or_suffix or "").upper()
    return any(m in s for m in REVERSAL_MARKERS)


# ══════════════════════════════════════════════════════════════════════
# 🔁 Fix 334 (2026-09-03) — 손절 후 **재진입**도 신규 진입 게이트를 참고로만
#
# 감사 실측: 재진입 워커가 30초마다 살아서 도는데 **24시간 608회 시도, 성공 0건**.
#
#     방향   시도   주 차단자                        건수
#     LONG   304   Fix 274 (24h 급등 15% 미만)      297   ← 통과율 0.19%
#     SHORT  297   Fix 270 (4H MACD hist)           294
#
#     [reentry_alert v130] 🎯 재진입 알람! SUIUSDT LONG obv_reverse=True rsi_reverse=True
#     [Fix274/LONG급등]    ⛔ SUIUSDT 차단 — 24h +7.6% < 15%
#     [RT_REENTRY]         🚨 skip: _create_auto_bb_strategy None 반환!
#
# 왜 이중 필터인가: 재진입 워커는 **자기 판정(OBV 반전·RSI 반전·10% 이동)을 통과한
# 심볼만** 여기로 보낸다. 그 위에 신규 진입용 추세 게이트를 또 걸면 「손절 후
# 좋은 자리에 다시 진입」(사장님 사양)이 구조적으로 불가능해진다.
# 게다가 `_create_auto_bb_strategy` 안에서 `strategy_type_suffix` 가 쓰이는 곳이
# 게이트들보다 **뒤**에 있어 면제 자체가 코드상 불가능했다.
#
# 🚨 전부 면제하는 것이 아니다 — 아래는 재진입에도 **그대로 건다**:
#   · Fix 168 동시보유 상한 / 심볼 검증 / Fix 303 제외 심볼 (안전장치)
#   · Fix 251 되돌림 ≥ 1.0 (원점 회귀 = 6건 -1,845) — 손절 뒤 원점까지 밀린
#     자리는 재진입에서 **더** 위험하다
#
# 🚨 되돌리기: `trend_4h_reentry_exempt = 0` / `confluence_reentry_exempt = 0` /
#             `long_surge_reentry_exempt = 0`
# ══════════════════════════════════════════════════════════════════════

SETTING_REENTRY_EXEMPT = "trend_4h_reentry_exempt"    # 기본 ON
REENTRY_MARKER = "_REENTRY"


def is_reentry_strategy(strategy_type_or_suffix: object) -> bool:
    """손절 후 **재진입**(`_reentry1`, `_reentry2`, …)인가.

    🚨 판정은 **이 함수 하나**에만 둔다. 게이트마다 따로 문자열 비교를 하면
       한쪽만 고치는 사고가 난다 (Fix 318→319 의 교훈). 테스트가 단일 정의를 강제한다.
    """
    return REENTRY_MARKER in str(strategy_type_or_suffix or "").upper()


def reentry_exempt_enabled(db, key: str = SETTING_REENTRY_EXEMPT) -> bool:
    """재진입에서 이 게이트를 참고로만 쓸 것인가 (기본 ON).

    `key` 를 바꿔 다른 게이트(합의·LONG 급등)의 스위치로도 쓴다 — 읽는 방식이 같다.
    """
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, key)
        if row is None or row.value is None or not str(row.value).strip():
            return True
        return str(row.value).strip().lower() in ("1", "true", "on", "yes")
    except Exception as e:
        logger.warning("[Fix334] %s 조회 실패 → 기본 ON: %s", key, e)
        return True


def gate_exempt(db, strategy_kind: object, *, reentry_key: str = SETTING_REENTRY_EXEMPT,
                reversal: bool = True) -> tuple[bool, str]:
    """이 전략 종류가 「신규 진입 추세 게이트」를 **참고로만** 써야 하는가.

    Returns:
        (면제, 사유). 반전(Fix 330)과 재진입(Fix 334)을 **한 곳에서** 판정한다.
    """
    if db is None or strategy_kind is None:
        return False, ""
    if reversal and is_reversal_strategy(strategy_kind) and reversal_exempt_enabled(db):
        return True, "반전 전략 (Fix 330)"
    if is_reentry_strategy(strategy_kind) and reentry_exempt_enabled(db, reentry_key):
        return True, "손절 후 재진입 (Fix 334)"
    return False, ""


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


def check_trend_4h(bc, symbol: str, side: str, *,
                   db=None, strategy_kind: object = None) -> tuple[bool, str, dict[str, Any]]:
    """4H 흐름이 이 방향을 지지하는가.

    Args:
        strategy_kind: 전략 종류(또는 접미사). **반전 계열이면 막지 않고 참고만 한다**
            (Fix 330 — 사장님 "15분이 기준이고 4시간을 참고"). `db` 를 함께 넘겨야
            설정으로 끌 수 있다. 둘 중 하나라도 없으면 기존 동작(통과 조건)이다.

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

        # 🚨 Fix 330: 반전 전략이면 **막지 않고 참고만** 한다.
        #   정점 SHORT 는 정의상 4H 가 아직 안 꺾인 자리를 잡는다 —
        #   여기서 막으면 사장님 사상 ①이 통째로 실행되지 않는다.
        # Fix 330(반전) + Fix 334(재진입) 을 한 곳에서 판정한다
        _exempt, _exempt_why = gate_exempt(db, strategy_kind)
        d["reversal_exempt"] = _exempt
        d["exempt_why"] = _exempt_why

        _fail = None
        if not rising:
            _fail = "4H MACD hist 가 내 편으로 상승 중이 아님"
        elif now_v <= 0:
            _fail = "4H MACD hist 가 아직 내 편 부호가 아님"

        if _fail is None:
            return True, "4H 흐름 지지 (hist 상승 + 내 편 부호)", d
        if _exempt:
            # 참고만 — 통과시키되 「4H 는 아직 내 편이 아니다」를 기록으로 남긴다.
            d["ref_note"] = _fail
            return True, f"4H 참고: {_fail} ({_exempt_why} — 막지 않음)", d
        return False, _fail, d
    except Exception as e:
        # fail-open — 필터가 매매를 멈추게 하지 않는다
        logger.debug("[Fix270] %s %s 4H 판정 실패 (fail-open): %s", symbol, side, e)
        d["error"] = str(e)[:200]
        return True, f"판정 실패 (fail-open): {e}", d


# ══════════════════════════════════════════════════════════════════════
# 💉 Fix 273 (2026-09-01 사장님): 피라미딩용 「계속 상승 중인가」
#
# 사장님 원 요청:
#   "익절구간에서 **계속 상승하는 차트와 보조지표**면 300usdt 씩 최대 2번 진입을 하고
#    tp1 단계 익절을 할수 있게 요청했다고 기억하는데"
#
# 코드에는 **차트(가격)만** 있었다 — peak 되돌림 2.5% / 시작가 대비 지속 0.5%.
# **보조지표 조건이 통째로 빠져 있었다** (RSI·CCI·OBV 를 학습 기록에 None 으로
# 저장만 하고 판정에 안 썼다). 사장님 요청의 절반만 구현돼 있던 것이다.
#
# 실측 (추가 시점 88건, 그 전략의 최종 손익으로 판정):
#     조건 없음(현행)          88건 승률 20.5%  **-5,832.19**  건당 -66.27
#     4H hist 상승중           54건      31.5%    +1,217.21       +22.54
#     **4H AND 15m 둘 다 상승** 45건    33.3%  **+1,359.23**    **+30.21**  <- 채택
#     4H hist 상승 **아님**     34건      2.9%    -7,049.40      -207.34   <- 이게 손실원
#
#   과적합 검사: 최근 절반 -871 -> +234 / 이전 절반 -4,961 -> +1,125 (양쪽 다 양수)
#
# 🚨 진입 선정용 게이트(Fix 270)와 **조건이 다르다**:
#    진입에서는 `hist 상승 AND hist>0` 이 최고였는데(+5.56/건),
#    피라미딩에서 `hist>0` 을 더하면 +22.54 -> **+0.31** 로 무너진다.
#    「같은 지표라도 용도가 다르면 결과가 다르다」의 세 번째 사례다.
#    -> 여기서는 **방향(상승 중)만** 본다.
#
# ⚠️ 방향별로 효과가 갈린다 (사장님께 보고 필요):
#     SHORT  조건없음 -91.32/건 -> 지표조건 **+99.28/건** (승률 34.8% -> 66.7%)
#     LONG   조건없음 -38.84/건 -> 지표조건  -30.23/건   (**여전히 적자**)
# ══════════════════════════════════════════════════════════════════════

PYRAMID_TFS: tuple[str, ...] = ("4h", "15m")


def check_hist_rising(bc, symbol: str, side: str, tf: str,
                      *, use_completed: bool = False) -> tuple[bool | None, dict[str, Any]]:
    """해당 봉의 MACD hist 가 **내 편 방향으로 상승 중**인가.

    Returns:
        (rising, detail). 판정 불가면 rising=None (호출자가 막지 않는다).
    """
    d: dict[str, Any] = {"tf": tf}
    try:
        kl = bc.get_klines(symbol=symbol, interval=tf, limit=LIMIT)
        if not kl or len(kl) < 40:
            d["reason"] = "봉 부족"
            return None, d
        # 🚨 Fix 291 (감사 발견): use_completed=True 면 **진행 중 봉을 잘라낸다**.
        #   15분 트리거는 완료봉만 쓰는데(Fix 216) 게이트만 진행 중 봉을 보면,
        #   봉 중간에 판정이 뒤집혀 측정과 다른 표본에서 주문이 나간다.
        #   ⚠️ 기본값은 False = **기존 호출자(Fix 270/273) 동작 무변경**.
        #      그쪽도 같은 어긋남이 있지만, 켜진 전략의 동작을 재측정 없이 바꾸지 않는다.
        _kl = kl[:-1] if (use_completed and len(kl) > 40) else kl
        h = _macd_hist([float(k[4]) for k in _kl])
        if h is None or len(h) < 2:
            d["reason"] = "MACD 계산 불가"
            return None, d
        sgn = 1.0 if str(side).upper() == "LONG" else -1.0
        delta = (h[-1] - h[-2]) * sgn
        d.update(delta=delta, hist_signed=h[-1] * sgn)
        return delta > 0, d
    except Exception as e:
        d["reason"] = f"조회 실패: {e}"
        return None, d


SETTING_PYRAMID_4H_VETO = "pyramid_4h_veto_enabled"   # Fix 345: 기본 OFF = 4H 는 참고만


def _pyramid_4h_veto_enabled(db) -> bool:
    """4H 를 피라미딩 **거부권**으로 쓸 것인가. 기본 **아니오** (사장님 「15분이 기준, 4시간은 참고」)."""
    if db is None:
        return False
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, SETTING_PYRAMID_4H_VETO)
        if row is None or row.value is None or not str(row.value).strip():
            return False
        return str(row.value).strip().lower() in ("1", "true", "on", "yes")
    except Exception as e:
        logger.warning("[Fix345] %s 조회 실패 → 참고만: %s", SETTING_PYRAMID_4H_VETO, e)
        return False


def check_pyramid_trend(bc, symbol: str, side: str, *, db=None) -> tuple[bool, str, dict[str, Any]]:
    """「계속 상승하는 차트와 **보조지표**」 — **15m hist 가 내 편으로 상승 중**인가 (4H 는 참고).

    🎯 Fix 345 (2026-09-04 사장님): "이건 왜 포지션 추가 진입이 없는거죠 문제가 있는것 같아"
       #2690 LPTUSDT SHORT 가 ROI +11.77% 로 트리거를 통과하고도 매 30초
       「4h MACD hist 가 내 편으로 상승 중이 아님」(진행중 4H 봉, delta −0.002) 으로 차단됐다.
       옛 판정은 4H·15m **둘 다** AND 였고 4H 를 먼저 봐서 15m 은 평가조차 안 됐다.
       사장님 사상: "**15분이 기준이고 4시간을 참고**하고 … 4시간 차트의 의미는 중단기
       지속적인 흐름을 판단하는 정도 차트" / 추가 조건: "수익중에 차트와 보조지표가
       지속 상승이나 하락이 데이터를 보이면 포지션 추가".
       → 15m = 판정(완성봉), 4H = 참고(완성봉, 로그·detail 에만). 되돌리기: SystemSetting
         pyramid_4h_veto_enabled = 1 이면 옛 AND 로 복귀.
       진행중 봉을 쓰지 않는다 — 4H 진행중 봉은 첫 25% 구간에서 부호가 뒤집힌다(2026-09-03 실측).

    ⚠️ **fail-open** — 판정 불가(데이터 없음)면 통과시킨다.
       이건 좋은 자리를 고르는 필터이지 안전장치가 아니다.
       (자본을 늘리는 판정이라 fail-closed 로 하고 싶지만, 그러면 API 한 번 실패에
        피라미딩이 통째로 멈춘다 — Fix 252 의 교훈. 대신 사유를 반드시 로그에 남긴다.)
    """
    det: dict[str, Any] = {}
    veto_4h = _pyramid_4h_veto_enabled(db)
    det["4h_role"] = "veto" if veto_4h else "reference"
    # ① 15m = 기준 (완성봉)
    rising15, d15 = check_hist_rising(bc, symbol, side, "15m", use_completed=True)
    det["15m"] = d15
    if rising15 is None:
        return True, f"15m 판정 불가 (fail-open): {d15.get('reason')}", det
    if not rising15:
        return False, "15m MACD hist 가 내 편으로 상승 중이 아님", det
    # ② 4H = 참고 (완성봉). 기본은 막지 않고 detail 에만 남긴다.
    rising4, d4 = check_hist_rising(bc, symbol, side, "4h", use_completed=True)
    det["4h"] = d4
    if rising4 is None:
        return True, f"15m 상승 중 · 4H 판정 불가 (참고): {d4.get('reason')}", det
    if not rising4 and veto_4h:
        return False, "4h MACD hist 가 내 편으로 상승 중이 아님 (pyramid_4h_veto_enabled=1)", det
    return True, ("15m 상승 중 · 4H 도 상승 중" if rising4 else "15m 상승 중 · 4H 는 아님 (참고만)"), det
