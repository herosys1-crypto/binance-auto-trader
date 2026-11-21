"""Fix 492 (2026-11-21 사장님 「증거금을 추가해서 모두 바이낸스 강제청산전까지 우리 시스템에서는 모든 인스턴스에서 청산은 없어」)."""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.risk_service import RiskService


def _svc(added):
    svc = RiskService.__new__(RiskService)
    svc.db = MagicMock()
    svc._added_margin_recorded = MagicMock(return_value=Decimal(str(added)))
    return svc


S = SimpleNamespace(id=4568, symbol="SNXXUSDT")


def test_added_margin_holds():
    assert _svc("10204.28")._margin_added_hold(S, "SL", Decimal("-130")) is True


def test_no_added_margin_does_not_hold():
    assert _svc("0")._margin_added_hold(S, "SL", Decimal("-130")) is False


def test_read_failure_keeps_old_behavior():
    svc = _svc("0")
    svc._added_margin_recorded = MagicMock(side_effect=RuntimeError("db"))
    assert svc._margin_added_hold(S, "SL", Decimal("-130")) is False


def test_property_any_positive_added_holds():
    for amt in ("0.01", "1", "6906.48", "10204.28", "1e6"):
        assert _svc(amt)._margin_added_hold(S, "강제손절", Decimal("0")) is True
    for amt in ("0", "-5"):
        assert _svc(amt)._margin_added_hold(S, "강제손절", Decimal("0")) is False
