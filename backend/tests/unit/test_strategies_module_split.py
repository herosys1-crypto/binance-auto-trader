"""Lint 테스트 — strategies 모듈 분할 회귀 방지 (2026-05-14 Phase 4 full).

배경:
- 기존 strategies.py 1,384 줄 monolith → 5 모듈 분할 (helpers / calculate / crud / control / lifecycle)
- 분할 후 누군가 1) 새 endpoint 를 잘못된 위치에 추가, 2) 기존 import 경로를 깨뜨리면 catch
- 6 외부 테스트 파일이 의존하는 backward compat alias 모두 검증

이 테스트는 분할 구조 + backward compat 의 single source 역할.
"""
from __future__ import annotations

from pathlib import Path


def _strategies_pkg() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "app" / "api" / "v1" / "strategies"


class TestStrategiesModuleSplit:
    """app/api/v1/strategies/ 패키지가 5 모듈 + __init__.py 로 구성됐는지 검증."""

    def test_strategies_is_package_not_file(self):
        """app/api/v1/strategies 는 디렉토리 (package) 여야."""
        pkg_path = _strategies_pkg()
        assert pkg_path.is_dir(), "strategies 는 package (디렉토리) 여야"

        # strategies.py 가 다시 생기면 (분할 깨짐) 실패
        single_file = pkg_path.parent / "strategies.py"
        assert not single_file.exists(), (
            "app/api/v1/strategies.py 가 다시 생김 — 분할 구조 깨짐. "
            "새 endpoint 는 strategies/ 패키지 내부 적절한 모듈에 추가하세요."
        )

    def test_all_5_submodules_exist(self):
        """helpers / calculate / crud / control / lifecycle 모듈 모두 존재."""
        expected = ["__init__.py", "helpers.py", "calculate.py", "crud.py", "control.py", "lifecycle.py"]
        pkg_path = _strategies_pkg()
        existing = {f.name for f in pkg_path.iterdir() if f.is_file()}
        missing = set(expected) - existing
        assert not missing, f"strategies/ 모듈 누락: {missing}"

    def test_each_router_submodule_defines_router(self):
        """router 가 있는 4개 submodule 검증 (helpers 는 helper-only)."""
        from app.api.v1.strategies import calculate, crud, control, lifecycle
        from fastapi import APIRouter

        for mod in [calculate, crud, control, lifecycle]:
            assert hasattr(mod, "router"), f"{mod.__name__} 에 router 없음"
            assert isinstance(mod.router, APIRouter), f"{mod.__name__}.router 가 APIRouter 가 아님"

    def test_aggregate_router_has_all_endpoints(self):
        """__init__.py 의 통합 router 가 4 submodule 의 모든 endpoint 포함."""
        from app.api.v1.strategies import router
        from app.api.v1.strategies.calculate import router as c
        from app.api.v1.strategies.crud import router as cr
        from app.api.v1.strategies.control import router as ct
        from app.api.v1.strategies.lifecycle import router as lc

        expected_total = sum(len(r.routes) for r in [c, cr, ct, lc])
        actual_total = len(router.routes)
        assert actual_total == expected_total, (
            f"통합 router endpoint 수 ({actual_total}) ≠ 4 submodule 합계 ({expected_total})"
        )

    def test_backward_compat_imports(self):
        """기존 `from app.api.v1.strategies import X` 가 모두 작동.

        분할 전 strategies.py 의 module-level public symbol 들이 __init__.py 에서
        re-export 돼야 함. 누락되면 외부 테스트 6 파일 깨짐.
        """
        from app.api.v1 import strategies  # noqa: F401

        required_symbols = [
            # router + 공통
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
        missing = [s for s in required_symbols if not hasattr(strategies, s)]
        assert not missing, (
            f"app.api.v1.strategies 누락 symbols: {missing}\n"
            "→ strategies/__init__.py 에 re-export 추가 필요"
        )

    def test_endpoint_paths_preserved(self):
        """분할 후에도 모든 endpoint URL 경로가 그대로 유지돼야 (frontend 호환).

        URL 변경 = production frontend / 외부 호출자 깨짐 → critical.
        """
        from app.api.v1.strategies import router

        actual_paths = {r.path for r in router.routes}
        expected_paths = {
            # CRUD
            "/strategies",
            "/strategies/{strategy_id}",
            # calculate
            "/strategies/preview-inline",
            "/strategies/calculate",
            # crud read views
            "/strategies/{strategy_id}/timeline",
            "/strategies/{strategy_id}/stage-plans",
            "/strategies/{strategy_id}/blueprint",
            # control
            "/strategies/{strategy_id}/start",
            "/strategies/{strategy_id}/settings",
            "/strategies/{strategy_id}/trigger-next-stage",
            # lifecycle
            "/strategies/{strategy_id}/add-margin",
            "/strategies/{strategy_id}/add-position",
            "/strategies/{strategy_id}/force-stop",
            "/strategies/{strategy_id}/restore",
            "/strategies/{strategy_id}/stop",
        }
        missing = expected_paths - actual_paths
        assert not missing, (
            f"분할 후 누락된 endpoint URL: {missing}\n"
            "→ frontend / 외부 호출자가 404 받을 위험"
        )

    def test_router_registered_in_main_app(self):
        """app.main 의 FastAPI app 에 strategies router 가 정상 mount 됐는지."""
        from app.main import app

        strategies_paths = [r.path for r in app.routes if "/strategies" in r.path]
        assert len(strategies_paths) >= 15, (
            f"main app 에 strategies endpoint {len(strategies_paths)} 개만 등록됨 — 15+ 기대"
        )
