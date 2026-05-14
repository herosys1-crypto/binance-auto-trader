"""Admin API package — 5 모듈로 분할 (2026-05-14 Phase 4).

이전 `app/api/v1/admin.py` (단일 1,360 줄 파일) 에서 분리:
  - templates.py    : Strategy template CRUD (~325 줄)
  - export.py       : CSV export (~110 줄)
  - monitoring.py   : Read-only — health/notifications/recent-activity/stats (~430 줄)
  - operations.py   : Write actions — KS/Whitelist/test-telegram/symbol-sync (~210 줄)
  - system.py       : Dashboard banner + health/dashboard (~230 줄)

이 `__init__.py` 의 두 가지 역할:
  1. Router 통합: 모든 submodule router 를 단일 `router` 로 포함 → app.api.router 가 변경 없이 사용
  2. Backward compat re-export: 기존 테스트/외부 코드가
     `from app.api.v1.admin import disable_kill_switch` 같은 import 를 그대로 쓸 수 있도록
     모든 public 함수/클래스를 노출.

새 코드 작성 시 직접 submodule 경로 권장:
  ✅ from app.api.v1.admin.operations import disable_kill_switch
  ⚠️ from app.api.v1.admin import disable_kill_switch  (기존 호환 유지용)
"""
from __future__ import annotations

from fastapi import APIRouter

# Backward compat — 이전 admin.py 가 module-level 에서 `from app.core.strategy_status import TERMINAL_STATUSES`
# 했으므로 `app.api.v1.admin.TERMINAL_STATUSES` 가 expected. test_strategy_status_constants 가 의존.
from app.core.strategy_status import TERMINAL_STATUSES  # noqa: F401

# Submodule routers
from app.api.v1.admin.templates import router as _templates_router
from app.api.v1.admin.export import router as _export_router
from app.api.v1.admin.monitoring import router as _monitoring_router
from app.api.v1.admin.operations import router as _operations_router
from app.api.v1.admin.system import router as _system_router

# 통합 router — app.api.router 가 import 하는 단일 진입점.
# 각 submodule 이 prefix="/admin" 을 이미 가지므로 추가 prefix 없이 include.
router = APIRouter()
router.include_router(_templates_router)
router.include_router(_export_router)
router.include_router(_monitoring_router)
router.include_router(_operations_router)
router.include_router(_system_router)


# ============================================================================
# Backward compat re-exports — 기존 테스트/코드의 import 경로 유지.
# 분리 전엔 모두 admin.py 의 module-level symbol 이었음.
# ============================================================================

# templates.py
from app.api.v1.admin.templates import (  # noqa: E402, F401
    StrategyTemplateCreate,
    StrategyTemplateResponse,
    cleanup_quick_templates,
    create_strategy_template,
    delete_strategy_template,
    list_strategy_templates,
)

# export.py
from app.api.v1.admin.export import (  # noqa: E402, F401
    export_orders_csv,
    export_strategies_csv,
)

# monitoring.py
from app.api.v1.admin.monitoring import (  # noqa: E402, F401
    get_notifications_by_title,
    get_operation_stats,
    get_recent_activity,
    get_stats_breakdown,
    get_system_health,
)

# operations.py
from app.api.v1.admin.operations import (  # noqa: E402, F401
    WhitelistSettingResponse,
    WhitelistSettingUpdate,
    _verify_account_ownership,
    disable_kill_switch,
    enable_kill_switch,
    get_whitelist_setting,
    symbol_sync,
    test_telegram,
    update_whitelist_setting,
)

# system.py
from app.api.v1.admin.system import (  # noqa: E402, F401
    get_health_dashboard,
    get_system_status,
)


__all__ = [
    "router",
    "TERMINAL_STATUSES",  # backward compat (test_strategy_status_constants)
    # templates
    "StrategyTemplateCreate",
    "StrategyTemplateResponse",
    "cleanup_quick_templates",
    "create_strategy_template",
    "delete_strategy_template",
    "list_strategy_templates",
    # export
    "export_orders_csv",
    "export_strategies_csv",
    # monitoring
    "get_notifications_by_title",
    "get_operation_stats",
    "get_recent_activity",
    "get_stats_breakdown",
    "get_system_health",
    # operations
    "WhitelistSettingResponse",
    "WhitelistSettingUpdate",
    "_verify_account_ownership",
    "disable_kill_switch",
    "enable_kill_switch",
    "get_whitelist_setting",
    "symbol_sync",
    "test_telegram",
    "update_whitelist_setting",
    # system
    "get_health_dashboard",
    "get_system_status",
]
