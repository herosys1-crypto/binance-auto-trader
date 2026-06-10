"""Edit Mode Service — 사장님 「수정 모드」 단일 진실 모듈 (Phase 2!).

사장님 사상 = single source of truth!
spec: docs/spec/edit_mode_spec_2026-06-11.md

사장님 「수정 모드」 4 옵션:
1. 「취소」 - 모달 닫기 (= 옛 strategy 그대로)
2. 「✓ 설정만 수정」 - TP/SL 즉시 갱신 (= 거래소 호출 X)
3. 「✏️ 종료 후 새로 시작」 - 미체결 취소 + 1단계 새로!
4. 「↻ 미진입 단계 재설정」 - 진입 단계 보존 + 미진입 재계산

= 사장님 헌법 13번 영구 보존!
"""
from __future__ import annotations
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional


class EditModeOption(str, Enum):
    """사장님 「수정 모드」 4 옵션."""
    CANCEL = "cancel"
    SETTINGS_ONLY = "settings_only"  # = 「✓ 설정만 수정」
    RESTART = "restart"               # = 「✏️ 종료 후 새로 시작」
    UNFILLED_ONLY = "unfilled_only"   # = 「↻ 미진입 단계 재설정」


def get_old_start_price(blueprint: Dict[str, Any]) -> str:
    """v41 fix: bp.start_price NULL = avg_entry_price fallback.

    사장님 사상: 「수정 모드」 = 옛 strategy 그대로!
    옛 strategy.start_price 가 NULL 가능 = avg_entry_price fallback!

    Args:
        blueprint: backend response (= strategies/{id}/blueprint)

    Returns:
        시작가 문자열 (= 사장님 옛 시작가 또는 평단)
    """
    start_price = blueprint.get("start_price")
    if start_price and str(start_price) not in ("0", "None", ""):
        return str(start_price)
    # v41 fallback
    avg_entry = blueprint.get("avg_entry_price")
    if avg_entry and str(avg_entry) not in ("0", "None", ""):
        return str(avg_entry)
    return ""


def is_start_price_changed(
    blueprint: Dict[str, Any],
    new_start_price: Any,
    tolerance_pct: float = 0.1,
) -> bool:
    """사장님 「현재가」 클릭 감지.

    = 시작가 변경 여부 = old vs new = 차이 > tolerance%

    Args:
        blueprint: backend response
        new_start_price: 신 입력 시작가
        tolerance_pct: 차이 임계 (= default 0.1%)

    Returns:
        True = 사장님 「현재가」 클릭 = 신 가격!
    """
    old = get_old_start_price(blueprint)
    if not old or not new_start_price:
        return False
    try:
        old_val = Decimal(old)
        new_val = Decimal(str(new_start_price))
        if old_val <= 0:
            return False
        diff_pct = abs(new_val - old_val) / old_val * Decimal("100")
        return diff_pct > Decimal(str(tolerance_pct))
    except Exception:
        return False


def should_preserve_old_avg(
    blueprint: Dict[str, Any],
    new_start_price: Any,
    editing_strategy_id: Optional[int],
) -> bool:
    """v40 사장님 사상: 1단계 = 옛 평단 보존?

    조건:
    1. 수정 모드 (= editing_strategy_id 있음)
    2. 시작가 변경 (= 사장님 「현재가」 클릭)
    3. 옛 평단 (= avg_entry_price) 존재

    = 1단계 = 옛 평단 보존!
    = 2단계+ = 신 시작가 누적!
    """
    if not editing_strategy_id:
        return False
    if not is_start_price_changed(blueprint, new_start_price):
        return False
    old_avg = blueprint.get("avg_entry_price")
    return bool(old_avg and str(old_avg) not in ("0", "None", ""))
