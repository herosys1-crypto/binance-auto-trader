"""✂️ 단계 전환 시 「10 USDT 만 남기고 청산」 — 사장님 2026-09-03 지시 (Fix 304).

## 사장님 원문

    "1단계 100이든 1000이든 10usdt 남기고, 모든 단계에서 청산은 10usdt 만 남기고
     모두 청산하고 다음 단계 진입하게 해줘"

    "기본전략과 같이 10usdt 남기고 청산하고 다음단계 진입하는 걸로 해줘
     전략 인스턴스에 남겨둬야 겠어"

## 지금과 무엇이 다른가

    지금 (trigger_mode=PRICE_DOWN_PCT):
      트리거 도달 → 기존 포지션을 **그대로 두고** 다음 단계를 추가한다.
      → 평단이 섞인다. 실측 #2032 AKEUSDT:
         0.01550 → 0.01743 → 0.01957 → 0.02230 → 0.02531
         5단계 손실률 **-88.17%** / -969.92 USDT.   = 물타기

    사장님 사양 (이 모듈):
      트리거 도달 → **10 USDT 만 남기고 청산** → 다음 단계 진입.
      → 평단이 리셋된다. 각 단계 손실이 독립적으로 제한된다.

## 왜 0 이 아니라 10 USDT 를 남기는가

사장님: **"전략 인스턴스에 남겨둬야 겠어"**

전량 청산하면 포지션이 사라지고 전략이 종료 처리되어 화면에서 없어진다.
잔량을 남기면 전략·포지션이 살아 있어 단계 감시가 이어지고 사장님이 계속 본다.

🚨 **잔량은 「나중에 팔 수 있는 크기」여야 한다.** 거래소 `MIN_NOTIONAL`(대개 5.00)
   미만으로 남기면 reduceOnly 주문이 거부되어 **영원히 청산할 수 없는 dust** 가 된다.
   이 저장소는 dust orphan 하나로 계정 전체가 막힌 전력이 있다.
   그래서 목표 잔량에 여유(1.1배)를 두고, 그래도 안 되면 **전량 청산으로 떨어진다.**

## 754심볼 전수 검산 (2026-09-03, 실시세)

    ✅ 10 USDT 잔량 그대로 가능      743개  (98.5%)
    ⚠️ MIN_NOTIONAL > 10              9개  (1.2%)  → Fix 303 으로 자동매매 제외
    ⚠️ stepSize 로 10 을 못 맞춤       2개  (0.3%)  → 같이 제외

## 안전 확인 (실측)

- `reconcile_worker.py:330` 의 고아 정리는 `exchange_position_amt == 0` **정확히 0**
  일 때만 발동한다. → 잔량 1%~10USDT 는 **자동 정리에 걸리지 않는다.**
- `execution_service.emergency_close_position(quantity=부분)` 은 2026-06-08 수정으로
  **부분 청산 시 옛 status 를 유지**하고 미체결 주문도 취소하지 않는다.
  → 전략이 살아 있는 채로 잔량만 남길 수 있다.
"""
from __future__ import annotations

import logging
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

logger = logging.getLogger(__name__)

__all__ = [
    "SETTING_ENABLED", "SETTING_KEEP_NOTIONAL",
    "KEEP_NOTIONAL_DEFAULT", "MIN_NOTIONAL_SAFETY",
    "SETTING_MAX_CUM_LOSS", "SETTING_MIN_TRIM_RATIO", "MIN_TRIM_RATIO_DEFAULT",
    "trim_enabled", "keep_notional", "compute_trim", "cumulative_loss_exceeded",
]

SETTING_ENABLED = "stage_trim_before_next_enabled"   # 기본 OFF (헌법 161)
SETTING_KEEP_NOTIONAL = "stage_keep_notional_usdt"   # 사장님 「10 usdt」
SETTING_MAX_CUM_LOSS = "stage_max_cumulative_loss_usdt"   # Fix 306: 누적 손실 상한
SETTING_MIN_TRIM_RATIO = "stage_min_trim_ratio"           # Fix 311: 청산분/잔량 최소 배수

KEEP_NOTIONAL_DEFAULT = Decimal("10")
# 잔량이 가격 변동으로 MIN_NOTIONAL 아래로 떨어지면 나중에 못 판다.
# 목표 잔량은 그 심볼 최소치의 1.1배 이상으로 잡는다.
MIN_NOTIONAL_SAFETY = Decimal("1.1")

# 🚨 Fix 311 (2026-09-03 사장님): 「첫진입이 10이라 **손절없이 그냥**」
#   1단계 10 USDT x 레버 2 = 명목 20. 여기서 10 을 남기면 **절반만 청산**된다.
#   사장님 사다리(10/300/600)에서 1단계는 「자리 탐색」이라 손절할 것이 없다.
#   청산분이 잔량의 이 배수 미만이면 **아무것도 하지 않는다.**
#     명목  20 / 잔량 10 → 청산 10 = 1.0배 → 스킵 (사장님 뜻)
#     명목 600 / 잔량 10 → 청산 590 = 59배 → 실행
MIN_TRIM_RATIO_DEFAULT = Decimal("2")


def trim_enabled(db) -> bool:
    """기본 OFF. 매매 흐름을 바꾸는 큰 변경이라 명시적으로 켠다 (헌법 161)."""
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, SETTING_ENABLED)
        if row is None or row.value is None:
            return False
        return str(row.value).strip().lower() in ("1", "true", "on", "yes")
    except Exception as e:
        logger.warning("[Fix304] %s 조회 실패 = OFF: %s", SETTING_ENABLED, e)
        return False


def keep_notional(db) -> Decimal:
    """남길 목표 명목가치(USDT). 사장님 기본 10."""
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, SETTING_KEEP_NOTIONAL)
        if row is None or row.value is None or not str(row.value).strip():
            return KEEP_NOTIONAL_DEFAULT
        v = Decimal(str(row.value).strip())
        if v <= 0 or v > Decimal("10000"):
            logger.warning("[Fix304] %s=%s 범위밖 → 기본 %s",
                           SETTING_KEEP_NOTIONAL, v, KEEP_NOTIONAL_DEFAULT)
            return KEEP_NOTIONAL_DEFAULT
        return v
    except Exception as e:
        logger.warning("[Fix304] %s 조회 실패 → 기본 %s: %s",
                       SETTING_KEEP_NOTIONAL, KEEP_NOTIONAL_DEFAULT, e)
        return KEEP_NOTIONAL_DEFAULT


def min_trim_ratio(db) -> Decimal:
    """청산분이 잔량의 몇 배 이상이어야 실행하는가 (Fix 311).

    사장님: "여기는 **첫진입이 10이라 손절없이 그냥** 좋은 포지션에
             2단계 300으로 진입후 손실이면 부분손절후 10 남기고..."

    1단계 10 USDT 는 명목 20 이라 10 을 남기면 절반만 청산된다 — 손절이라 부를
    수 없고, 사장님 사다리에서 1단계는 「자리 탐색」이라 그대로 두는 것이 맞다.
    """
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, SETTING_MIN_TRIM_RATIO)
        if row is None or row.value is None or not str(row.value).strip():
            return MIN_TRIM_RATIO_DEFAULT
        v = Decimal(str(row.value).strip())
        if v < 0 or v > 1000:
            return MIN_TRIM_RATIO_DEFAULT
        return v
    except Exception as e:
        logger.warning("[Fix311] %s 조회 실패 → 기본 %s: %s",
                       SETTING_MIN_TRIM_RATIO, MIN_TRIM_RATIO_DEFAULT, e)
        return MIN_TRIM_RATIO_DEFAULT


def _filters(db, symbol: str):
    """(step_size, min_qty, min_notional). 하나라도 없으면 None."""
    try:
        from sqlalchemy import select
        from app.models.symbol import Symbol
        row = db.execute(select(Symbol).where(Symbol.symbol == symbol)).scalar_one_or_none()
        if row is None:
            return None
        step = Decimal(str(row.step_size or 0))
        mq = Decimal(str(row.min_qty or 0))
        mn = Decimal(str(row.min_notional or 0))
        if step <= 0:
            return None
        return step, mq, mn
    except Exception as e:
        logger.warning("[Fix304] %s 거래소 필터 조회 실패: %s", symbol, e)
        return None


def compute_trim(db, symbol: str, position_qty, mark_price) -> tuple:
    """「10 USDT 만 남기고」 청산할 수량을 계산한다.

    Returns:
        (close_qty, keep_qty, why)  — 전부 Decimal / str.
        close_qty == 0 이면 아무것도 하지 않는다 (판정 불가 등).

    🚨 **판정이 불확실하면 아무것도 하지 않는다** (close_qty=0).
       여기서 잘못 청산하면 실제 자금이 사라진다. 되돌릴 수 없다.
       반대로 아무것도 안 하면 지금까지의 동작(물타기)이 유지될 뿐이다.
    """
    zero = Decimal("0")
    try:
        qty = abs(Decimal(str(position_qty or 0)))
        px = Decimal(str(mark_price or 0))
    except Exception:
        return zero, zero, "수량/가격 파싱 실패"
    if qty <= 0 or px <= 0:
        return zero, zero, "포지션 없음 또는 가격 없음"

    f = _filters(db, symbol)
    if f is None:
        return zero, zero, f"{symbol} 거래소 필터 없음 (안전상 미실행)"
    step, min_qty, min_notional = f

    # 목표 잔량 = max(사장님 설정, 그 심볼 최소치 x 여유)
    target = keep_notional(db)
    floor_notional = min_notional * MIN_NOTIONAL_SAFETY
    if floor_notional > target:
        target = floor_notional

    # 잔량 수량 = 올림 (내림하면 목표 아래로 떨어져 못 팔 위험)
    keep_qty = (target / px / step).to_integral_value(rounding=ROUND_CEILING) * step
    if keep_qty < min_qty:
        keep_qty = min_qty

    # 잔량이 보유량 이상이면 남길 것이 없다 → 전량 청산
    #
    # 🚨 Fix 305: 전량 청산도 **발주 가능해야** 한다. 보유 명목이 MIN_NOTIONAL
    #    미만이면 그 주문 자체가 거부되므로 시도하지 않는다 (단위 테스트가 잡음).
    if keep_qty >= qty:
        if qty * px < min_notional:
            return zero, qty, (
                f"보유 명목 {qty * px:.2f} < MIN_NOTIONAL {min_notional} → 청산 불가 (미실행)"
            )
        return qty, zero, (
            f"잔량 목표({target:.2f} USDT = {keep_qty}) >= 보유 {qty} → 전량 청산"
        )

    close_qty = ((qty - keep_qty) / step).to_integral_value(rounding=ROUND_FLOOR) * step
    if close_qty <= 0:
        return zero, qty, "청산 수량이 stepSize 미만 → 미실행"

    # 🚨 청산 주문 자체도 MIN_NOTIONAL 을 넘어야 발주된다.
    #
    #   Fix 305 (2026-09-03): 여기서 그냥 미실행으로 돌려주면 **영구 정지**가 된다.
    #   보유 명목이 「목표 잔량 ~ 목표 잔량 + MIN_NOTIONAL」 구간(대략 11~16 USDT)
    #   이면 매 사이클 이 분기에 걸리고, 호출자는 fail-CLOSED 라 단계 진입을
    #   중단한다. 사다리가 그 심볼에서 영원히 멈춘다.
    #
    #   이 구간은 애초에 「10 을 남길 만큼 크지 않은 포지션」이다. 전량 청산으로
    #   떨어뜨리는 것이 맞다 — 잔량 0 이면 dust 문제도 없다.
    if close_qty * px < min_notional:
        if qty * px >= min_notional:
            return qty, zero, (
                f"청산분 명목 {close_qty * px:.2f} < MIN_NOTIONAL {min_notional} "
                f"→ 잔량을 남길 수 없는 크기 = 전량 청산"
            )
        return zero, qty, (
            f"보유 명목 {qty * px:.2f} < MIN_NOTIONAL {min_notional} → 청산 불가 (미실행)"
        )

    # 🚨 Fix 311: 청산분이 잔량에 비해 너무 작으면 **손절이 아니다** → 미실행.
    #    사장님 사다리 1단계(10 USDT, 명목 20)가 정확히 이 경우다.
    _ratio = min_trim_ratio(db)
    if _ratio > 0 and close_qty < keep_qty * _ratio:
        return zero, qty, (
            f"청산분 {close_qty} < 잔량 {keep_qty} x {_ratio} "
            f"→ 1단계급 소액이라 정리하지 않는다 (사장님 「손절없이 그냥」)"
        )

    return close_qty, keep_qty, (
        f"{close_qty} 청산 / {keep_qty} 잔여 (명목 {keep_qty * px:.2f} USDT, "
        f"목표 {target:.2f}, MIN_NOTIONAL {min_notional})"
    )


def cumulative_loss_exceeded(db, strategy) -> tuple[bool, str]:
    """🚨 Fix 306 — 누적 실현 손실이 상한을 넘었는가.

    사장님 2026-09-03: **"손실 그래도 계산되어야 하는거 아닌가?"**

    ## 왜 필요한가

    Fix 304 는 단계마다 청산하고 다음 단계로 넘어간다. 그때 평단이 리셋되므로
    강제 손절 판정(`risk_service`)의 `pnl_ratio = raw_pnl_pct x leverage` 도
    **0 부터 다시 시작**한다. 즉 단계를 거듭할수록 누적 손실은 커지는데
    **손절 판정에는 한 번도 잡히지 않는다.**

    사장님 3단 사다리는 「3번 지면 -60(SHORT)/-120(LONG) 에서 멈춘다」가 전제다.
    그 멈춤을 보장하려면 **누적 실현 손실**을 봐야 한다.

    ## 실측 (2026-09-03)

    `cumulative_realized_loss` 는 `stream_service.py:399` 에서 EXIT 체결마다
    누적되는데, **읽는 곳이 0곳**이었다. 주석은 "UI 표시용" 이라고 적혀 있지만
    화면도 읽지 않았다 — 쓰기만 하는 죽은 필드였다.

    ## 기본은 무제한

    상한값은 전략마다·사장님 사다리마다 다르므로 임의로 정하지 않는다.
    설정 `stage_max_cumulative_loss_usdt` 를 넣어야 작동한다 (기본 없음 = 무제한).
    """
    try:
        cum = abs(Decimal(str(getattr(strategy, "cumulative_realized_loss", 0) or 0)))
    except Exception:
        return False, ""
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, SETTING_MAX_CUM_LOSS)
        if row is None or row.value is None or not str(row.value).strip():
            return False, ""            # 미설정 = 무제한 (기본 동작 불변)
        limit = Decimal(str(row.value).strip())
    except Exception as e:
        logger.warning("[Fix306] %s 조회 실패 → 무제한: %s", SETTING_MAX_CUM_LOSS, e)
        return False, ""
    if limit <= 0:
        return False, ""
    if cum >= limit:
        return True, (
            f"누적 실현 손실 {cum:.2f} USDT >= 상한 {limit:.2f} USDT "
            f"→ 다음 단계 진입 중단"
        )
    return False, f"누적 손실 {cum:.2f} / {limit:.2f} USDT"
