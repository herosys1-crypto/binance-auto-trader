"""tp_sl_orchestrator._resolve_crisis_qty_ratios — JSONB override 머지 회귀.

배경: 2026-05-04 alembic 0009 에서 StrategyTemplate.crisis_qty_ratios JSONB
컬럼을 추가하면서 코드가 이전 hardcoded {25,25,50,100} 대신 template 별
override 를 읽도록 변경됨. 이 테스트는 override 가 일부만/잘못 채워졌을 때도
안전하게 default 로 폴백하는지 보장.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.tp_sl_orchestrator import (
    _CRISIS_QTY_RATIO_DEFAULT,
    _resolve_crisis_qty_ratios,
)


class TestResolveCrisisQtyRatios:
    def test_none_override_returns_full_default(self) -> None:
        out = _resolve_crisis_qty_ratios(None)
        assert out == dict(_CRISIS_QTY_RATIO_DEFAULT)
        assert out["TP1"] == Decimal("25")
        assert out["TP4"] == Decimal("100")

    def test_empty_dict_returns_full_default(self) -> None:
        assert _resolve_crisis_qty_ratios({}) == dict(_CRISIS_QTY_RATIO_DEFAULT)

    def test_full_override_replaces_all_keys(self) -> None:
        out = _resolve_crisis_qty_ratios({"TP1": 30, "TP2": 30, "TP3": 40, "TP4": 100})
        assert out == {
            "TP1": Decimal("30"), "TP2": Decimal("30"),
            "TP3": Decimal("40"), "TP4": Decimal("100"),
        }

    def test_partial_override_keeps_default_for_missing_keys(self) -> None:
        # TP3 만 override → 나머지는 default
        out = _resolve_crisis_qty_ratios({"TP3": 75})
        assert out == {
            "TP1": Decimal("25"), "TP2": Decimal("25"),
            "TP3": Decimal("75"),  # ← override
            "TP4": Decimal("100"),
        }

    def test_string_values_accepted(self) -> None:
        # JSONB 가 numeric 을 string 으로 줄 수도 있음
        out = _resolve_crisis_qty_ratios({"TP1": "33.33", "TP2": "33.33"})
        assert out["TP1"] == Decimal("33.33")
        assert out["TP2"] == Decimal("33.33")
        assert out["TP3"] == Decimal("50")  # default

    def test_invalid_value_falls_back_to_default(self) -> None:
        out = _resolve_crisis_qty_ratios({"TP1": "not_a_number", "TP2": None})
        assert out["TP1"] == Decimal("25")  # default
        assert out["TP2"] == Decimal("25")  # default
        assert out["TP3"] == Decimal("50")
        assert out["TP4"] == Decimal("100")

    def test_negative_value_falls_back_to_default(self) -> None:
        out = _resolve_crisis_qty_ratios({"TP1": -10})
        assert out["TP1"] == Decimal("25")  # default

    def test_value_above_100_falls_back_to_default(self) -> None:
        out = _resolve_crisis_qty_ratios({"TP4": 150})
        assert out["TP4"] == Decimal("100")  # default

    def test_unknown_keys_ignored(self) -> None:
        # TP5/TP6 등 알 수 없는 키는 무시 (크라이시스에서 사용 안 함)
        out = _resolve_crisis_qty_ratios({"TP1": 30, "TP5": 80, "FOO": 10})
        assert out["TP1"] == Decimal("30")
        assert "TP5" not in out
        assert "FOO" not in out
        assert set(out.keys()) == {"TP1", "TP2", "TP3", "TP4"}

    def test_zero_is_valid(self) -> None:
        # 0% 도 유효한 값 — 사용자가 해당 단계 청산 안 함을 의도할 수 있음
        out = _resolve_crisis_qty_ratios({"TP1": 0})
        assert out["TP1"] == Decimal("0")

    def test_exactly_100_is_valid(self) -> None:
        out = _resolve_crisis_qty_ratios({"TP1": 100})
        assert out["TP1"] == Decimal("100")

    def test_non_dict_override_returns_default(self) -> None:
        # 잘못된 type (e.g. list, str) → default 폴백 (방어적)
        for bad in (["TP1", 30], "TP1=30", 42):
            out = _resolve_crisis_qty_ratios(bad)
            assert out == dict(_CRISIS_QTY_RATIO_DEFAULT)

    def test_default_constants_match_user_spec(self) -> None:
        # spec 값 (사용자 기획 2026-04-30): 25/25/50/100
        assert _CRISIS_QTY_RATIO_DEFAULT["TP1"] == Decimal("25")
        assert _CRISIS_QTY_RATIO_DEFAULT["TP2"] == Decimal("25")
        assert _CRISIS_QTY_RATIO_DEFAULT["TP3"] == Decimal("50")
        assert _CRISIS_QTY_RATIO_DEFAULT["TP4"] == Decimal("100")
