"""Current Price Action — 사장님 「현재가」 클릭 단일 진실 모듈 (Phase 2!).

사장님 사상 = single source of truth!
spec: docs/spec/current_price_action_spec_2026-06-11.md

사장님 「현재가」 버튼 클릭 동작:
1. 시작가 = 신 현재가
2. (수정 모드 + 옛 평단 있음) → 1단계 = 옛 평단 보존
3. (그 외) → 1단계 = 시작가
4. 2단계+ = 누적 (= 이전 단계 × (1 ± trigger%))

= 사장님 헌법 14번 영구 보존!
= v40 + v43 사상!
"""
from __future__ import annotations
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

from app.services.stage_calculator import (
    calculate_stages_new,
    calculate_stages_edit_mode,
)
from app.services.edit_mode_service import should_preserve_old_avg


def calculate_stages_after_current_price_click(
    blueprint: Optional[Dict[str, Any]],
    new_start_price: Any,
    triggers: Sequence[Any],
    side: str = "SHORT",
    editing_strategy_id: Optional[int] = None,
) -> List[Decimal]:
    """사장님 「현재가」 클릭 후 = 단계별 진입가 계산!

    스마트 분기:
    - 수정 모드 + 옛 평단 보존 조건 만족 → calculate_stages_edit_mode
    - 그 외 → calculate_stages_new

    Args:
        blueprint: backend response (= 수정 모드 시!)
        new_start_price: 사장님이 클릭한 = 신 시작가 (= 현재가)
        triggers: 단계별 trigger%
        side: "SHORT" 또는 "LONG"
        editing_strategy_id: 수정 모드 시 = strategy_id

    Returns:
        각 단계 진입가 리스트
    """
    # 수정 모드 + 옛 평단 보존 조건!
    if blueprint and editing_strategy_id and should_preserve_old_avg(
        blueprint, new_start_price, editing_strategy_id
    ):
        old_avg = blueprint.get("avg_entry_price")
        return calculate_stages_edit_mode(
            start_price=new_start_price,
            old_avg=old_avg,
            triggers=triggers,
            side=side,
        )

    # 그 외 = 신 strategy 또는 = 단순 수정 모드
    return calculate_stages_new(
        start_price=new_start_price,
        triggers=triggers,
        side=side,
    )
