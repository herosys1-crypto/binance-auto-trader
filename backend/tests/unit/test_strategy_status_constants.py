"""TERMINAL_STATUSES 상수 일치성 회귀.

audit 발견 (2026-05-04): 같은 의미의 set 이 5+ 곳에 inline 으로 반복되고
일부는 항목 누락 / STOPPING 포함 여부가 달라 미묘한 버그 유발.

이 테스트는:
- TERMINAL_STATUSES 가 정확히 정의된 7개 status 만 포함
- STOPPING 이 의도적으로 제외됨 (포지션 잔재 가능)
- 사용자 (admin.py / strategies.py / strategy_service.py) 가 같은 값 참조
"""
from __future__ import annotations

from app.core.strategy_status import DELETABLE_STATUSES, TERMINAL_STATUSES


class TestTerminalStatusesContent:
    def test_exactly_seven_statuses(self) -> None:
        assert len(TERMINAL_STATUSES) == 7

    def test_contains_canonical_terminals(self) -> None:
        expected = {
            "STOPPED", "COMPLETED", "CLOSED",
            "CLOSED_BY_TP", "CLOSED_BY_SL",
            "REENTRY_READY", "KILL_SWITCH_TRIGGERED",
        }
        assert set(TERMINAL_STATUSES) == expected

    def test_stopping_is_intentionally_excluded(self) -> None:
        """STOPPING 은 closing-in-progress — 포지션 잔재 가능 → terminal 아님."""
        assert "STOPPING" not in TERMINAL_STATUSES

    def test_active_open_statuses_excluded(self) -> None:
        for n in range(1, 11):
            assert f"STAGE{n}_OPEN" not in TERMINAL_STATUSES
            assert f"STAGE{n}_OPEN_PENDING" not in TERMINAL_STATUSES

    def test_tp_partial_excluded(self) -> None:
        for n in range(1, 6):
            assert f"TP{n}_DONE_PARTIAL" not in TERMINAL_STATUSES

    def test_deletable_matches_terminal(self) -> None:
        """DELETE 가능 set 은 TERMINAL 과 동일."""
        assert DELETABLE_STATUSES == TERMINAL_STATUSES

    def test_immutable_frozenset(self) -> None:
        """frozenset 이라 실수로 수정 불가."""
        import pytest
        with pytest.raises(AttributeError):
            TERMINAL_STATUSES.add("BOGUS")  # type: ignore[attr-defined]


class TestUsersReferenceSameSet:
    """admin.py / strategies.py / strategy_service.py 의 import 가 같은 set 참조."""

    def test_admin_imports_terminal_statuses(self) -> None:
        from app.api.v1 import admin
        # module 의 import 가 같은 frozenset
        assert admin.TERMINAL_STATUSES is TERMINAL_STATUSES

    def test_strategies_imports_terminal_statuses(self) -> None:
        from app.api.v1 import strategies
        assert strategies.TERMINAL_STATUSES is TERMINAL_STATUSES

    def test_strategy_service_imports_terminal_statuses(self) -> None:
        from app.services import strategy_service
        assert strategy_service.TERMINAL_STATUSES is TERMINAL_STATUSES
