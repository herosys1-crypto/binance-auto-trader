"""RiskService._update_pnl_extremes 회귀 테스트.

배경: 2026-04-30 #54 AIOTUSDT, #55 SKYAIUSDT 에서 max_loss_pct == max_profit_pct 양수
같은 값으로 들어가는 패턴 발견. 원인은 첫 호출 시 None 체크가 OR 조건이라 양수 pnl 도
max_loss_pct 에 들어가는 버그. fix 후엔 의미상 음수만 max_loss, 양수만 max_profit 후보.
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.risk_service import RiskService


def _make_service():
    """db 의존성 mock — _update_pnl_extremes 는 self.db 사용 안 하므로 MagicMock 충분."""
    return RiskService(db=MagicMock())


def _strategy(max_loss=None, max_profit=None):
    return SimpleNamespace(max_loss_pct=max_loss, max_profit_pct=max_profit)


class TestUpdatePnlExtremes:
    """음수만 max_loss, 양수만 max_profit 후보."""

    def test_first_positive_pnl_does_not_set_max_loss(self) -> None:
        """첫 호출에 양수 pnl 이 들어와도 max_loss_pct 는 None 유지."""
        s = _strategy()
        _make_service()._update_pnl_extremes(s, Decimal("10.71"))
        assert s.max_loss_pct is None  # 양수 pnl 은 max_loss 후보 아님 ⭐
        assert s.max_profit_pct == Decimal("10.71")

    def test_first_negative_pnl_does_not_set_max_profit(self) -> None:
        """첫 호출에 음수 pnl 이 들어와도 max_profit_pct 는 None 유지."""
        s = _strategy()
        _make_service()._update_pnl_extremes(s, Decimal("-15.50"))
        assert s.max_loss_pct == Decimal("-15.50")
        assert s.max_profit_pct is None  # 음수 pnl 은 max_profit 후보 아님 ⭐

    def test_zero_pnl_does_not_update_either(self) -> None:
        """pnl_ratio = 0 이면 둘 다 갱신 안 함."""
        s = _strategy()
        _make_service()._update_pnl_extremes(s, Decimal("0"))
        assert s.max_loss_pct is None
        assert s.max_profit_pct is None

    def test_max_loss_only_deepens(self) -> None:
        """더 깊은 손실로만 갱신, 얕은 손실로 덮어쓰지 않음."""
        s = _strategy(max_loss=Decimal("-15"), max_profit=Decimal("5"))
        _make_service()._update_pnl_extremes(s, Decimal("-10"))  # 더 얕음
        assert s.max_loss_pct == Decimal("-15")  # 그대로

        _make_service()._update_pnl_extremes(s, Decimal("-20"))  # 더 깊음
        assert s.max_loss_pct == Decimal("-20")  # 갱신

    def test_max_profit_only_grows(self) -> None:
        """더 큰 이익으로만 갱신."""
        s = _strategy(max_loss=Decimal("-15"), max_profit=Decimal("10"))
        _make_service()._update_pnl_extremes(s, Decimal("5"))  # 더 작음
        assert s.max_profit_pct == Decimal("10")  # 그대로

        _make_service()._update_pnl_extremes(s, Decimal("20"))  # 더 큼
        assert s.max_profit_pct == Decimal("20")  # 갱신

    def test_short_winning_scenario_no_loss_ever(self) -> None:
        """SHORT 진입 후 가격 하락만 — #54/#55 시나리오. max_loss 는 None 으로 유지."""
        s = _strategy()
        svc = _make_service()
        # 진입 직후 +5%, +8%, +10.71% (peak), +9% (회귀), +7% (TP1 직전 청산)
        for pnl in [Decimal("5"), Decimal("8"), Decimal("10.71"), Decimal("9"), Decimal("7")]:
            svc._update_pnl_extremes(s, pnl)
        # 한 번도 음수 pnl 없었음 → max_loss_pct = None 유지
        assert s.max_loss_pct is None  # ⭐ 이전 버그에선 +10.71 로 잘못 들어감
        # max_profit_pct 는 peak +10.71% 에서 멈춤
        assert s.max_profit_pct == Decimal("10.71")

    def test_mixed_pnl_correctly_separated(self) -> None:
        """음수/양수 섞여서 와도 각각 정확히 분리 후보."""
        s = _strategy()
        svc = _make_service()
        for pnl in [Decimal("3"), Decimal("-5"), Decimal("8"), Decimal("-12"), Decimal("2"), Decimal("-7")]:
            svc._update_pnl_extremes(s, pnl)
        assert s.max_profit_pct == Decimal("8")  # 양수 중 최대
        assert s.max_loss_pct == Decimal("-12")  # 음수 중 최소 (가장 깊은 손실)
