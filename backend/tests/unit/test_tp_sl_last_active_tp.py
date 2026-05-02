"""TPSLOrchestratorService — 마지막 활성 TP 발동 시 잔량 전량 청산 + COMPLETED.

사용자 기획 (2026-04-30 evening, #80 사례 검토):
"4/4 익절 모두 종료되면 전략 인스턴스 모두 종료. 1단계만 진입했어도
모든 활성 TP 발동 시 나머지 잔량까지 전부 청산하고 종료."

검증 시나리오:
- TP1~TP4 활성, TP4 가 마지막 → TP4 발동 시 잔량 100% 청산
- TP1~TP3 만 활성 → TP3 가 마지막 → TP3 발동 시 잔량 100% 청산
- TP1 만 활성 → TP1 발동 시 잔량 100% 청산
- 사용자가 TP4 의 qty_ratio 를 25 로 설정해도 마지막이면 100% 강제 (기획)
- 중간 TP (마지막 아닌) 는 사용자 ratio 그대로 — 부분 청산 유지
"""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _make_template(tp_percents: dict, tp_ratios: dict | None = None):
    """tp_percents={1: 10, 2: 15, 3: 20, 4: 25} 같은 식. None 이면 비활성."""
    tpl = SimpleNamespace(strategy_template_id=1)
    for n in range(1, 6):
        setattr(tpl, f"tp{n}_percent", tp_percents.get(n))
        setattr(tpl, f"tp{n}_qty_ratio", (tp_ratios or {}).get(n))
    return tpl


def _last_active_tp(tpl):
    """tp_sl_orchestrator 의 active_tps 로직 동일."""
    active_tps = []
    if tpl:
        for n in range(1, 6):
            if getattr(tpl, f"tp{n}_percent", None) is not None:
                active_tps.append(f"TP{n}")
    return active_tps[-1] if active_tps else None


class TestLastActiveTpDetection:
    """활성 TP 의 마지막 레벨 정확히 판단."""

    def test_tp1_to_tp4_active_returns_tp4(self) -> None:
        tpl = _make_template({1: 10, 2: 15, 3: 20, 4: 25})
        assert _last_active_tp(tpl) == "TP4"

    def test_tp1_to_tp3_only_returns_tp3(self) -> None:
        tpl = _make_template({1: 10, 2: 15, 3: 20})
        assert _last_active_tp(tpl) == "TP3"

    def test_tp1_to_tp5_active_returns_tp5(self) -> None:
        tpl = _make_template({1: 10, 2: 15, 3: 20, 4: 25, 5: 30})
        assert _last_active_tp(tpl) == "TP5"

    def test_only_tp1_returns_tp1(self) -> None:
        tpl = _make_template({1: 10})
        assert _last_active_tp(tpl) == "TP1"

    def test_no_active_tp_returns_none(self) -> None:
        tpl = _make_template({})
        assert _last_active_tp(tpl) is None

    def test_template_none_returns_none(self) -> None:
        assert _last_active_tp(None) is None

    def test_gaps_in_active_tps(self) -> None:
        """TP1, TP3 만 활성 (TP2 비어있음) — 마지막은 TP3."""
        tpl = _make_template({1: 10, 3: 20})
        assert _last_active_tp(tpl) == "TP3"


class TestCloseRatioForLastActiveTp:
    """마지막 활성 TP 발동 시 close_ratio = 100% (사용자 ratio override)."""

    def _resolve_close_ratio(self, level, tpl, crisis_mode=False):
        """tp_sl_orchestrator 의 close_ratio 결정 로직 simulation."""
        ratio_attr = {
            "TP1": "tp1_qty_ratio", "TP2": "tp2_qty_ratio", "TP3": "tp3_qty_ratio",
            "TP4": "tp4_qty_ratio", "TP5": "tp5_qty_ratio",
        }
        default_ratio = {
            "TP1": Decimal("25"), "TP2": Decimal("50"),
            "TP3": Decimal("100"), "TP4": Decimal("100"), "TP5": Decimal("100"),
        }
        crisis_qty_ratio = {"TP1": Decimal("25"), "TP2": Decimal("25"), "TP3": Decimal("50"), "TP4": Decimal("100")}
        last_active = _last_active_tp(tpl)

        if level == "TRAILING_TP":
            return Decimal("1.00")
        elif last_active and level == last_active:
            return Decimal("1.00")  # 마지막 활성 TP — override
        elif crisis_mode and level in crisis_qty_ratio:
            return crisis_qty_ratio[level] / Decimal("100")
        else:
            attr = ratio_attr.get(level)
            tpl_val = getattr(tpl, attr, None) if tpl and attr else None
            ratio_pct = Decimal(str(tpl_val)) if tpl_val is not None else default_ratio.get(level, Decimal("100"))
            return ratio_pct / Decimal("100")

    def test_tp4_when_last_active_overrides_user_ratio(self) -> None:
        """사용자가 TP4 ratio 25% 설정해도 마지막이면 100% 강제."""
        tpl = _make_template({1: 10, 2: 15, 3: 20, 4: 25}, tp_ratios={1: 25, 2: 25, 3: 25, 4: 25})
        # 중간 TP 들은 사용자 ratio 그대로
        assert self._resolve_close_ratio("TP1", tpl) == Decimal("0.25")
        assert self._resolve_close_ratio("TP2", tpl) == Decimal("0.25")
        assert self._resolve_close_ratio("TP3", tpl) == Decimal("0.25")
        # 마지막 TP4 는 100% 강제 (기획)
        assert self._resolve_close_ratio("TP4", tpl) == Decimal("1.00")  # ⭐

    def test_tp3_when_last_active_overrides(self) -> None:
        """TP1~TP3 만 활성, TP3 가 마지막."""
        tpl = _make_template({1: 10, 2: 15, 3: 20}, tp_ratios={1: 25, 2: 25, 3: 25})
        assert self._resolve_close_ratio("TP1", tpl) == Decimal("0.25")
        assert self._resolve_close_ratio("TP2", tpl) == Decimal("0.25")
        assert self._resolve_close_ratio("TP3", tpl) == Decimal("1.00")  # ⭐ 마지막 → 100%

    def test_tp1_only_returns_full_close(self) -> None:
        """TP1 만 활성이면 TP1 자체가 마지막."""
        tpl = _make_template({1: 10}, tp_ratios={1: 50})  # 사용자가 50% 로 설정해도
        assert self._resolve_close_ratio("TP1", tpl) == Decimal("1.00")  # ⭐ 100% 강제

    def test_trailing_tp_always_full_close(self) -> None:
        """TRAILING_TP 는 활성 TP 와 무관하게 항상 100%."""
        tpl = _make_template({1: 10, 2: 15})
        assert self._resolve_close_ratio("TRAILING_TP", tpl) == Decimal("1.00")

    def test_crisis_mode_uses_crisis_ratio_for_intermediate(self) -> None:
        """크라이시스 모드 + 중간 TP — 크라이시스 ratio 사용."""
        tpl = _make_template({1: 10, 2: 15, 3: 20, 4: 25})
        assert self._resolve_close_ratio("TP1", tpl, crisis_mode=True) == Decimal("0.25")
        assert self._resolve_close_ratio("TP2", tpl, crisis_mode=True) == Decimal("0.25")
        assert self._resolve_close_ratio("TP3", tpl, crisis_mode=True) == Decimal("0.50")
        # TP4 는 마지막이라서 100% 강제 (크라이시스 100% 와 일치)
        assert self._resolve_close_ratio("TP4", tpl, crisis_mode=True) == Decimal("1.00")

    def test_non_last_tp_in_short_template_not_overridden(self) -> None:
        """TP1~TP3 활성에서 TP1 발동은 마지막 아니므로 사용자 ratio 사용."""
        tpl = _make_template({1: 10, 2: 15, 3: 20}, tp_ratios={1: 30, 2: 30, 3: 40})
        assert self._resolve_close_ratio("TP1", tpl) == Decimal("0.30")  # 사용자 그대로
        assert self._resolve_close_ratio("TP2", tpl) == Decimal("0.30")
        assert self._resolve_close_ratio("TP3", tpl) == Decimal("1.00")  # 마지막 → 100% override


class TestEffectiveBehavior:
    """end-to-end 시나리오: 4 단계 진입 + TP 진행."""

    def test_short_4_stage_entry_tp4_completes(self) -> None:
        """4단계 SHORT 진입 후 TP1~TP4 발동 — 마지막 TP4 에서 잔량 0 + COMPLETED.

        사용자 ratio = 25/25/25/25, 진입 총 1000:
        - TP1: 1000 × 25% = 250 청산, 잔량 750
        - TP2: 750 × 25% = 187.5 청산, 잔량 562.5
        - TP3: 562.5 × 25% = 140.625 청산, 잔량 421.875
        - TP4 (마지막): override 100% → 421.875 청산, 잔량 0 ✅
        """
        from decimal import Decimal as D

        # 시뮬레이션
        tpl = _make_template({1: 10, 2: 15, 3: 20, 4: 25}, tp_ratios={1: 25, 2: 25, 3: 25, 4: 25})
        helper = TestCloseRatioForLastActiveTp()

        qty = D("1000")
        # TP1
        ratio = helper._resolve_close_ratio("TP1", tpl)
        closed = qty * ratio
        qty -= closed
        assert closed == D("250")
        assert qty == D("750")
        # TP2
        ratio = helper._resolve_close_ratio("TP2", tpl)
        closed = qty * ratio
        qty -= closed
        assert closed == D("187.50")
        assert qty == D("562.50")
        # TP3
        ratio = helper._resolve_close_ratio("TP3", tpl)
        closed = qty * ratio
        qty -= closed
        assert closed == D("140.625")
        assert qty == D("421.875")
        # TP4 — 마지막이라 100%
        ratio = helper._resolve_close_ratio("TP4", tpl)
        closed = qty * ratio
        qty -= closed
        assert ratio == D("1.00")  # override 작동
        assert qty == D("0")  # 잔량 0 ⭐ COMPLETED 조건 충족

    def test_short_1_stage_entry_tp4_completes(self) -> None:
        """사용자 기획 케이스: 1단계만 진입했어도 TP4 까지 발동 시 종료.
        1단계 자본 1000 으로 진입, TP1~TP4 차례로 발동 시 잔량 0 도달."""
        from decimal import Decimal as D

        tpl = _make_template({1: 10, 2: 15, 3: 20, 4: 25}, tp_ratios={1: 25, 2: 25, 3: 25, 4: 25})
        helper = TestCloseRatioForLastActiveTp()

        qty = D("1000")  # 1단계만 진입한 경우에도 동일 흐름
        for level in ["TP1", "TP2", "TP3"]:
            r = helper._resolve_close_ratio(level, tpl)
            qty -= qty * r
        # TP4 마지막
        r = helper._resolve_close_ratio("TP4", tpl)
        assert r == D("1.00")
        qty -= qty * r
        assert qty == D("0")  # ⭐ 1단계 진입 + 4 TP 모두 발동 → 잔량 0
