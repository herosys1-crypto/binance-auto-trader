"""Fix 492b (2026-11-21 사장님: 증거금 추가 인스턴스 = 우리 시스템 청산 없음 · 범위 「익절만 허용」).
모든 청산이 지나는 ExecutionService.emergency_close_position 입구에서 막는다."""
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.services import execution_service as ES


def _svc():
    svc = ES.ExecutionService.__new__(ES.ExecutionService)
    svc.db = MagicMock()
    return svc


def _added(amount):
    return patch("app.services.risk_service.RiskService._added_margin_recorded", return_value=Decimal(str(amount)))


@pytest.mark.parametrize("purpose,amount,blocked", [
    ("auto", "10300", True), ("auto", "0", False),
    ("take_profit", "10300", False), ("human", "10300", False),
    ("stage_trim", "10300", True), ("anything", "0.01", True),
])
def test_blocks_only_auto_with_added_margin(purpose, amount, blocked):
    with _added(amount):
        assert _svc()._margin_added_blocks(4568, purpose) is blocked


def test_read_failure_keeps_old_behavior():
    with patch("app.services.risk_service.RiskService._added_margin_recorded", side_effect=RuntimeError("db")):
        assert _svc()._margin_added_blocks(4568, "auto") is False


def test_emergency_close_raises_before_any_exchange_call():
    svc = _svc()
    svc._emergency_close_position_locked = MagicMock()
    with _added("10300"), patch.object(ES, "get_redis_client") as rc:
        with pytest.raises(ES.CloseBlockedMarginAdded):
            svc.emergency_close_position(4568, quantity=Decimal("0"))
        svc._emergency_close_position_locked.assert_not_called()
        rc.assert_not_called()                                   # 잠금·거래소 호출 전에 막음


def test_take_profit_and_human_pass_through():
    svc = _svc()
    svc._emergency_close_position_locked = MagicMock(return_value="order")
    lock = MagicMock()
    lock.__enter__ = MagicMock(return_value=None)
    lock.__exit__ = MagicMock(return_value=False)
    with _added("10300"), patch.object(ES, "get_redis_client"), patch.object(ES, "redis_lock", return_value=lock):
        assert svc.emergency_close_position(4568, quantity=Decimal("1"), purpose="take_profit") == "order"
        assert svc.emergency_close_position(4568, quantity=Decimal("1"), purpose="human") == "order"


def test_allowed_callers_are_tagged():
    """허용 경로(익절·사장님 조작)는 purpose 를 달고, 자동 청산 경로는 기본값(auto)으로 남아 있어야 한다."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    tagged = {
        "services/tp_sl_orchestrator.py": 'purpose="take_profit"',
        "api/v1/strategies/lifecycle.py": 'purpose="human"',
        "api/v1/admin/templates.py": 'purpose="human"',
    }
    for rel, mark in tagged.items():
        assert mark in (root / rel).read_text(encoding="utf-8"), rel
    for rel in ("services/pump_dump_short_live.py", "workers/bb_mid_line_worker.py", "workers/bb_swing_worker.py",
                "workers/ichikijun_exit_worker.py", "workers/time_reverse_exit_worker.py"):
        txt = (root / rel).read_text(encoding="utf-8")
        assert 'purpose="take_profit"' not in txt and 'purpose="human"' not in txt, rel
