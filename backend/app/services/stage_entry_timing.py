"""⏳ 단계 진입 타이밍 — 「모니터링 후 좋은 포지션에 진입」 (Fix 312).

## 사장님 원문 (2026-09-03)

    "이것이 되면 **v219 자동매매**에서도 부분손절 후 10usdt를 남기고
     **모니터링 후 좋은 포지션에 다음단계 진입**할수 있게 해줘.
     여기는 **첫진입이 10이라 손절없이 그냥 좋은 포지션에 2단계 300으로 진입**후
     손실이면 부분손절후 10 남기고 다음단계 모니터링 해서
     **좋은 포지션에 진입**하는 로직으로 진행하는거지?"

## 🚨 세 방식은 각각 다르다 — 이 모듈은 그중 하나에만 붙는다

    기본방식 (사장님 수동 단계 전략)  → **정해진 트리거 단가에 즉시** 진입
                                        (사장님: "기본전략은 정해진 트리거에
                                         진입하는거야") = 이 모듈 **미적용**
    OBV 자동 (trigger_mode=OBV_REVERSE) → `stage_entry_signal` 이 이미 4중 게이트로
                                        「좋은 자리」를 판정한다 = 이 모듈 **미적용**
                                        (얹으면 Fix 232 가 없앤 중복 게이트가 부활한다)
    **v219 사다리** (auto_bb_break_SAJANGNIM_*, 1단계 자본 10)
                                      → **이 모듈이 적용된다**

실측(2026-09-03) 활성 전략은 전부 v219 사다리였다:
`auto_bb_break_SAJANGNIM_TOP` 7건 / `..._BOTTOM` 2건 (모두 1단계 자본 10).
세 방식 모두 `trigger_mode = PRICE_DOWN_PCT` 라 **trigger_mode 로는 구분되지 않는다.**
그래서 `strategy_type` 접두사로 가른다.

## 실측 — 「기다렸다 들어가면」 얼마나 좋아지나

2단계 트리거(가격이 20% 불리하게 이동) 도달 후, Fix 276 꺾임을 최대 N봉 기다렸다
진입한 경우와 즉시 진입한 경우:

    대기            진입   승률    vs 즉시   과적합
    즉시            151  37.7%      -       -
    최대 8봉(2h)     36  47.2%   +9.5%p   **OK**
    최대 16봉(4h)    36  47.2%   +9.5%p   **OK**
    최대 32봉(8h)    37  45.9%   +8.2%p    X
    최대 64봉(16h)   48  41.7%   +3.9%p    X

    side 별:  SHORT 32.3% → **47.6% (+15.3%p)**
              LONG  48.1% → 46.7% (-1.4%p)

🌟 **SHORT 에서만 효과가 있다.** 사장님 사상과 맞는다 — 급등 정점 SHORT 는
   「꺾임」을 봐야 하고, LONG(급락 후 반등)은 이미 바닥이라 즉시가 낫다.
   그래서 기본 적용 대상은 **SHORT 뿐**이다.

⚠️ 오래 기다릴수록 나빠지지만(64봉 41.7%) 그래도 즉시(37.7%)보다는 낫다.
   그래서 강제 진입 폴백을 두지 않는다 — 꺾임이 올 때까지 기다린다.
   기다리는 동안 노출은 1단계 10 USDT(또는 잔량 10)뿐이라 작다.

## 판정

Fix 276 `evaluate_first_entry` — 「밴드 밖 N봉 지속 → 극값에서 꺾임」.
사장님 원문 "최고점 최저점이라 판단되면 무조건" 이 그대로 들어 있고,
실측에서 SHORT 건당 +0.673 → +1.800 을 만든 바로 그 판정이다.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = [
    "SETTING_ENABLED", "SETTING_SIDES", "SETTING_TYPES", "SETTING_KLINES",
    "SIDES_DEFAULT", "TYPES_DEFAULT", "KLINES_DEFAULT",
    "wait_enabled", "target_sides", "target_type_prefixes", "should_enter_now",
]

SETTING_ENABLED = "stage_wait_for_turn_enabled"     # 기본 OFF (헌법 161)
SETTING_SIDES = "stage_wait_for_turn_sides"         # 적용 방향
SETTING_TYPES = "stage_wait_for_turn_types"         # 적용 strategy_type 접두사
SETTING_KLINES = "stage_wait_for_turn_klines"

SIDES_DEFAULT = "SHORT"                       # 🌟 실측: SHORT +15.3%p / LONG -1.4%p
TYPES_DEFAULT = "auto_bb_break_SAJANGNIM"     # 🚨 v219 사다리에만. 기본방식·OBV 제외
KLINES_DEFAULT = 120


def _setting(db, key: str):
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, key)
        if row is None or row.value is None:
            return None
        return str(row.value).strip() or None
    except Exception as e:
        logger.warning("[Fix312] %s 조회 실패: %s", key, e)
        return None


def wait_enabled(db) -> bool:
    v = _setting(db, SETTING_ENABLED)
    return bool(v) and v.lower() in ("1", "true", "on", "yes")


def target_sides(db) -> frozenset[str]:
    v = _setting(db, SETTING_SIDES) or SIDES_DEFAULT
    return frozenset(x.strip().upper() for x in v.split(",") if x.strip())


def target_type_prefixes(db) -> tuple[str, ...]:
    v = _setting(db, SETTING_TYPES) or TYPES_DEFAULT
    return tuple(x.strip() for x in v.split(",") if x.strip())


def _type_matches(db, strategy_type: object) -> bool:
    st = str(strategy_type or "")
    if not st:
        return False        # 종류를 모르면 적용하지 않는다 (기본 동작 유지)
    return any(st.startswith(p) for p in target_type_prefixes(db))


def should_enter_now(db, bc, symbol: str, side: str, strategy_type: object) -> tuple[bool, str]:
    """지금이 이 단계에 들어갈 「좋은 포지션」인가.

    Returns:
        (진입해도 되는가, 사유)

    🚨 **fail-OPEN 이다.** 판정에 실패하면 진입을 허용한다.
       이 게이트는 「더 좋은 자리를 고르는」 개선이지 안전장치가 아니다.
       fail-closed 하면 캔들 조회가 한 번 실패할 때마다 단계가 멈춘다
       (Fix 305 에서 겪은 「영구 정지」와 같은 함정).
    """
    if not wait_enabled(db):
        return True, ""
    if not _type_matches(db, strategy_type):
        return True, f"{strategy_type} 는 대기 대상 아님 (기본방식/OBV 는 제외)"
    if str(side or "").upper() not in target_sides(db):
        return True, f"{side} 는 대기 대상 아님 (실측상 효과 없음)"

    try:
        n = int(_setting(db, SETTING_KLINES) or KLINES_DEFAULT)
    except (TypeError, ValueError):
        n = KLINES_DEFAULT
    n = max(60, min(n, 500))

    try:
        kl = bc.get_klines(symbol=symbol, interval="15m", limit=n)
        closes = [float(x[4]) for x in (kl or [])]
    except Exception as e:
        logger.warning("[Fix312] %s 캔들 조회 실패 → 진입 허용: %s", symbol, e)
        return True, "캔들 조회 실패 (fail-open)"
    if len(closes) < 40:
        return True, "캔들 부족 (fail-open)"

    try:
        from app.services.bb_entry_rules import evaluate_first_entry
        anchor, path, why, _d = evaluate_first_entry(closes, str(side).upper())
    except Exception as e:
        logger.warning("[Fix312] %s 판정 실패 → 진입 허용: %s", symbol, e)
        return True, "판정 실패 (fail-open)"

    if anchor is not None:
        return True, f"꺾임 확인 ({path}) — 좋은 포지션"
    return False, f"좋은 포지션 대기 중 — {why}"
