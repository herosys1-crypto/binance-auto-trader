"""Strategies API package — 5 모듈로 분할 (2026-05-14 Phase 4 full).

이전 `app/api/v1/strategies.py` (단일 1,384 줄 파일) 에서 분리:
  - helpers.py    : 공통 helper 함수 (~95 줄)
  - calculate.py  : preview / calculate (~155 줄)
  - crud.py       : create / list / get + timeline / stage-plans / blueprint (~290 줄)
  - control.py    : start / settings PATCH / trigger-next-stage (~540 줄)
  - lifecycle.py  : add-margin / add-position / force-stop / delete / restore / stop (~360 줄)

이 `__init__.py` 의 두 가지 역할:
  1. Router 통합: 모든 submodule router 를 단일 `router` 로 포함 → app.api.router 변경 없이 사용
  2. Backward compat re-export: 기존 테스트/외부 코드가
     `from app.api.v1.strategies import delete_strategy` 같은 import 를 그대로 쓸 수 있도록
     모든 public 함수/클래스/helper 노출.

새 코드 작성 시 직접 submodule 경로 권장:
  ✅ from app.api.v1.strategies.lifecycle import delete_strategy
  ⚠️ from app.api.v1.strategies import delete_strategy  (기존 호환 유지용)
"""
from __future__ import annotations

from fastapi import APIRouter

# Submodule routers
from app.api.v1.strategies.calculate import router as _calculate_router
from app.api.v1.strategies.crud import router as _crud_router
from app.api.v1.strategies.control import router as _control_router
from app.api.v1.strategies.lifecycle import router as _lifecycle_router

# 통합 router — app.api.router 가 import 하는 단일 진입점.
# 각 submodule 이 prefix="/strategies" 를 이미 가지므로 추가 prefix 없이 include.
router = APIRouter()
router.include_router(_calculate_router)
router.include_router(_crud_router)
router.include_router(_control_router)
router.include_router(_lifecycle_router)


# ============================================================================
# Backward compat re-exports — 기존 테스트/코드의 import 경로 유지.
# 분리 전엔 모두 strategies.py 의 module-level symbol 이었음.
# ============================================================================

# helpers.py
from app.api.v1.strategies.helpers import (  # noqa: E402, F401
    _count_active_stages,
    _count_active_tps,
    _enrich_response,
    _fetch_tp_counts_batch,
    _resolve_close_reason,
)

# calculate.py
from app.api.v1.strategies.calculate import (  # noqa: E402, F401
    PreviewInlineRequest,
    calculate_preview,
    preview_inline,
)

# crud.py
from app.api.v1.strategies.crud import (  # noqa: E402, F401
    create_strategy,
    get_strategy,
    get_strategy_blueprint,
    get_strategy_stage_plans,
    get_strategy_timeline,
    list_strategies,
)

# control.py
from app.api.v1.strategies.control import (  # noqa: E402, F401
    AddUntriggeredStagesRequest,
    StrategySettingsUpdate,
    TrailingRetracePctRequest,
    add_untriggered_stages,
    cancel_open_order,
    list_open_orders,
    recalc_untriggered_from_current,
    start_strategy,
    trigger_next_stage_manually,
    update_strategy_settings_in_place,
    update_trailing_retrace,
)

# lifecycle.py
from app.api.v1.strategies.lifecycle import (  # noqa: E402, F401
    AddMarginRequest,
    AddPositionRequest,
    AddPositionWithStageRequest,
    add_margin_to_strategy,
    add_position_to_strategy,
    add_position_with_stage,
    delete_strategy,
    force_stop_strategy,
    restore_strategy,
    stop_strategy,
)

# Backward compat — TERMINAL_STATUSES 직접 re-export (test_strategy_status_constants 사용).
from app.core.strategy_status import TERMINAL_STATUSES  # noqa: E402, F401


__all__ = [
    "router",
    "TERMINAL_STATUSES",
    # helpers
    "_count_active_stages",
    "_count_active_tps",
    "_enrich_response",
    "_fetch_tp_counts_batch",
    "_resolve_close_reason",
    # calculate
    "PreviewInlineRequest",
    "calculate_preview",
    "preview_inline",
    # crud
    "create_strategy",
    "get_strategy",
    "get_strategy_blueprint",
    "get_strategy_stage_plans",
    "get_strategy_timeline",
    "list_strategies",
    # control
    "StrategySettingsUpdate",
    "start_strategy",
    "trigger_next_stage_manually",
    "update_strategy_settings_in_place",
    "recalc_untriggered_from_current",
    "add_untriggered_stages",
    "AddUntriggeredStagesRequest",
    # lifecycle
    "AddMarginRequest",
    "AddPositionRequest",
    "add_margin_to_strategy",
    "add_position_to_strategy",
    "delete_strategy",
    "force_stop_strategy",
    "restore_strategy",
    "stop_strategy",
]
