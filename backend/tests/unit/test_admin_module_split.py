"""Lint 테스트 — admin 모듈 분할 회귀 방지 (2026-05-14 Phase 4).

배경:
- 기존 admin.py 1,360 줄 monolith → 5 모듈 분할 (templates / export / monitoring / operations / system)
- 분할 후 누군가 1) 새 endpoint 를 잘못된 위치에 추가, 2) 기존 import 경로를 깨뜨리면 catch
- 운영 중인 frontend / 외부 테스트가 사용하는 backward compat alias 모두 검증

이 테스트는 분할 구조 + backward compat 의 single source 역할.
"""
from __future__ import annotations

from pathlib import Path


def _admin_pkg() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "app" / "api" / "v1" / "admin"


class TestAdminModuleSplit:
    """admin/ 패키지가 5 모듈 + __init__.py 로 구성됐는지 검증."""

    def test_admin_is_package_not_file(self):
        """app/api/v1/admin 은 디렉토리 (package), 단일 파일 admin.py 가 아니어야."""
        admin_path = _admin_pkg()
        assert admin_path.is_dir(), "admin 은 package (디렉토리) 여야"

        # admin.py 가 다시 생기면 (분할 깨짐) 실패
        single_file = admin_path.parent / "admin.py"
        assert not single_file.exists(), (
            "app/api/v1/admin.py 가 다시 생김 — 분할 구조 깨짐. "
            "새 endpoint 는 admin/ 패키지 내부 적절한 모듈에 추가하세요."
        )

    def test_all_5_submodules_exist(self):
        """templates / export / monitoring / operations / system 모듈 모두 존재."""
        expected = ["__init__.py", "templates.py", "export.py", "monitoring.py", "operations.py", "system.py"]
        admin_path = _admin_pkg()
        existing = {f.name for f in admin_path.iterdir() if f.is_file()}
        missing = set(expected) - existing
        assert not missing, f"admin/ 모듈 누락: {missing}"

    def test_each_submodule_defines_router(self):
        """각 submodule 은 `router = APIRouter(prefix='/admin', ...)` 정의 필수."""
        from app.api.v1.admin import templates, export, monitoring, operations, system
        from fastapi import APIRouter

        for mod in [templates, export, monitoring, operations, system]:
            assert hasattr(mod, "router"), f"{mod.__name__} 에 router 없음"
            assert isinstance(mod.router, APIRouter), f"{mod.__name__}.router 가 APIRouter 가 아님"

    def test_aggregate_router_has_all_endpoints(self):
        """__init__.py 의 통합 router 가 19 endpoints 모두 포함."""
        from app.api.v1.admin import router

        # 각 submodule routes 합 계산
        from app.api.v1.admin.templates import router as t
        from app.api.v1.admin.export import router as e
        from app.api.v1.admin.monitoring import router as m
        from app.api.v1.admin.operations import router as o
        from app.api.v1.admin.system import router as s

        expected_total = sum(len(r.routes) for r in [t, e, m, o, s])
        actual_total = len(router.routes)
        assert actual_total == expected_total, (
            f"통합 router 의 endpoint 수 ({actual_total}) ≠ 5 submodule 합계 ({expected_total})"
        )
        assert actual_total > 0, "통합 router 가 비어있음"

    def test_backward_compat_imports_from_admin_package(self):
        """기존 `from app.api.v1.admin import X` 가 모두 작동.

        분할 전 admin.py 의 module-level public symbol 들이 __init__.py 에서
        re-export 돼야 함. 누락되면 외부 테스트 / 외부 코드 깨짐.
        """
        from app.api.v1 import admin  # noqa: F401

        required_symbols = [
            # router
            "router",
            # templates
            "StrategyTemplateCreate",
            "StrategyTemplateResponse",
            "create_strategy_template",
            "list_strategy_templates",
            "delete_strategy_template",
            "cleanup_quick_templates",
            # export
            "export_strategies_csv",
            "export_orders_csv",
            # monitoring
            "get_system_health",
            "get_notifications_by_title",
            "get_recent_activity",
            "get_operation_stats",
            "get_stats_breakdown",
            # operations
            "test_telegram",
            "symbol_sync",
            "_verify_account_ownership",
            "WhitelistSettingResponse",
            "WhitelistSettingUpdate",
            "get_whitelist_setting",
            "update_whitelist_setting",
            "enable_kill_switch",
            "disable_kill_switch",
            # system
            "get_system_status",
            "get_health_dashboard",
            # backward compat: TERMINAL_STATUSES re-export (test_strategy_status_constants 사용)
            "TERMINAL_STATUSES",
        ]
        missing = [s for s in required_symbols if not hasattr(admin, s)]
        assert not missing, (
            f"app.api.v1.admin 누락 symbols: {missing}\n"
            "→ admin/__init__.py 에 re-export 추가 필요"
        )

    def test_endpoint_paths_preserved(self):
        """분할 후에도 모든 endpoint URL 경로가 그대로 유지돼야 (frontend 호환).

        URL 변경 = production frontend / 외부 호출자 깨짐 → critical.
        """
        from app.api.v1.admin import router

        actual_paths = {r.path for r in router.routes}
        # 분할 전 admin.py 가 가지고 있던 모든 endpoint 경로
        expected_paths = {
            # templates
            "/admin/strategy-templates",
            "/admin/strategy-templates/{template_id}",
            "/admin/strategy-templates/cleanup-quick",
            # export
            "/admin/export/strategies",
            "/admin/export/orders",
            # monitoring
            "/admin/system-health",
            "/admin/notifications-by-title",
            "/admin/recent-activity",
            "/admin/stats",
            "/admin/stats/breakdown",
            # operations
            "/admin/test-telegram",
            "/admin/symbol-sync",
            "/admin/settings/whitelist",
            "/admin/kill-switch/{exchange_account_id}/enable",
            "/admin/kill-switch/{exchange_account_id}/disable",
            # system
            "/admin/system-status",
            "/admin/health/dashboard",
        }
        missing = expected_paths - actual_paths
        assert not missing, (
            f"분할 후 누락된 endpoint URL: {missing}\n"
            "→ frontend / 외부 호출자가 404 받을 위험"
        )

    def test_router_registered_in_main_app(self):
        """app.main 의 FastAPI app 에 admin router 가 정상 mount 됐는지."""
        from app.main import app

        admin_paths = [r.path for r in app.routes if "/admin/" in r.path]
        assert len(admin_paths) >= 17, (
            f"main app 에 admin endpoint {len(admin_paths)} 개만 등록됨 — 17+ 기대. "
            "app.api.router 의 include 가 깨졌을 가능성."
        )
