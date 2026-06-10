"""Stage Calculator — 사장님 단계 계산 단일 진실 모듈 (Phase 2!).

사장님 사상 = single source of truth!
spec: docs/spec/stage_calculation_spec_2026-06-11.md

= frontend cm-capitals-grid.js _refreshLiveCalc 와 = 100% 동일 logic!
= 사장님 사상 = 영구 보존!

사용 가이드:
1. 신 strategy 만들기 = calculate_stages_new()
2. 수정 모드 「현재가」 클릭 = calculate_stages_edit_mode()

= 사상 = 단 하나 함수 = 어디서든 호출!
"""
from __future__ import annotations
from decimal import Decimal
from typing import List, Sequence, Union

# Type aliases
NumericLike = Union[int, float, str, Decimal]


def _to_decimal(val: NumericLike, default: str = "0") -> Decimal:
    """안전 Decimal 변환."""
    try:
        if val is None or val == "":
            return Decimal(default)
        return Decimal(str(val))
    except Exception:
        return Decimal(default)


def calculate_stages_new(
    start_price: NumericLike,
    triggers: Sequence[NumericLike],
    side: str = "SHORT",
) -> List[Decimal]:
    """신 strategy 단계 계산 (= 사장님 사상!).

    spec:
        1단계 = start_price
        N단계 = (N-1)단계 × (1 ± trigger_N%)

    Args:
        start_price: 시작가 (= 1단계 진입가)
        triggers: 각 단계 trigger% (= [0, 10, 20, 20, ...])
        side: "SHORT" 또는 "LONG"

    Returns:
        각 단계 진입가 리스트 (Decimal)
    """
    sp = _to_decimal(start_price)
    if sp <= 0 or not triggers:
        return []

    side_upper = (side or "SHORT").upper()
    prices: List[Decimal] = []
    prev = sp

    for i, trg in enumerate(triggers):
        if i == 0:
            # 1단계 = 시작가
            prices.append(prev)
            continue
        trg_pct = _to_decimal(trg)
        if side_upper == "SHORT":
            curr = prev * (Decimal("1") + trg_pct / Decimal("100"))
        else:
            curr = prev * (Decimal("1") - trg_pct / Decimal("100"))
        prices.append(curr)
        prev = curr

    return prices


def calculate_stages_edit_mode(
    start_price: NumericLike,
    old_avg: NumericLike,
    triggers: Sequence[NumericLike],
    side: str = "SHORT",
) -> List[Decimal]:
    """수정 모드 + 「현재가」 클릭 = 사장님 사상!

    spec:
        1단계 = old_avg (= 옛 평단 보존!)
        2단계 = start_price × (1 ± trigger_2%) (= 신 startPrice 기준!)
        N단계 = (N-1)단계 × (1 ± trigger_N%)

    = v40 fix 사장님 사상!

    Args:
        start_price: 신 시작가 (= 현재가)
        old_avg: 옛 평단 (= 사장님 진입 보존!)
        triggers: 각 단계 trigger% (= [0, 10, 20, ...])
        side: "SHORT" 또는 "LONG"

    Returns:
        각 단계 진입가 리스트 (Decimal)
    """
    sp = _to_decimal(start_price)
    oa = _to_decimal(old_avg)
    if sp <= 0 or oa <= 0 or not triggers:
        return []

    side_upper = (side or "SHORT").upper()
    prices: List[Decimal] = []
    prev = sp  # 2단계 기준!

    for i, trg in enumerate(triggers):
        if i == 0:
            # 1단계 = 옛 평단 보존!
            prices.append(oa)
            continue
        trg_pct = _to_decimal(trg)
        if side_upper == "SHORT":
            curr = prev * (Decimal("1") + trg_pct / Decimal("100"))
        else:
            curr = prev * (Decimal("1") - trg_pct / Decimal("100"))
        prices.append(curr)
        prev = curr

    return prices


def validate_stage_order(
    stages: Sequence[Decimal],
    side: str = "SHORT",
) -> bool:
    """단계 순서 사상 검증.

    spec:
        SHORT: 단계 진입가 오름차순!
        LONG:  단계 진입가 내림차순!

    1단계 (= 옛 평단) 는 = 다음 단계와 같은 방향이 아닐 수 있음 (= 수정 모드)
    = 2단계 이상 = 순서 검증

    Returns:
        True = 정상, False = 위배!
    """
    if len(stages) < 3:
        return True

    side_upper = (side or "SHORT").upper()
    # 2단계 부터 검증 (= 1단계는 수정 모드 시 다를 수 있음)
    for i in range(2, len(stages)):
        if side_upper == "SHORT":
            if stages[i] <= stages[i - 1]:
                return False
        else:
            if stages[i] >= stages[i - 1]:
                return False
    return True
