"""StrategyCalculator V2 (동적 N단계) 단위 테스트."""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.strategy_calculator import StrategyCalculator, SymbolRule


def _btc_rule() -> SymbolRule:
    return SymbolRule(
        symbol="BTCUSDT",
        tick_size=Decimal("0.1"),
        step_size=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        price_precision=1,
        quantity_precision=3,
    )


def _common_kwargs(start_price="100000", side="SHORT"):
    return {
        "symbol": "BTCUSDT",
        "side": side,
        "start_price": Decimal(start_price),
        "leverage": 2,
        "total_capital": Decimal("10000"),
        "tp1_percent": Decimal("10"),
        "tp2_percent": Decimal("20"),
        "tp3_percent": Decimal("30"),
        "stop_loss_percent_of_capital": Decimal("50"),
    }


class TestThreeStages:
    def test_3_stage_short(self) -> None:
        calc = StrategyCalculator(_btc_rule())
        preview = calc.calculate_preview(
            **_common_kwargs(),
            stages_config={
                "capitals": ["100", "200", "350"],
                "last_stage_trigger_mode": "LIQUIDATION_BUFFER",
                "last_stage_trigger_percent": "5",
            },
        )
        assert len(preview.stages) == 3
        # 1단계: IMMEDIATE @ 100000
        s1 = preview.stages[0]
        assert s1.trigger_mode == "IMMEDIATE"
        assert s1.trigger_price == Decimal("100000.0")
        assert s1.planned_capital == Decimal("100")
        # 2단계: PRICE_UP_PCT 10% from 100000 → 110000
        s2 = preview.stages[1]
        assert s2.trigger_mode == "PRICE_UP_PCT"
        assert s2.trigger_percent == Decimal("10")
        assert s2.trigger_price == Decimal("110000.0")
        # 3단계 (마지막): LIQUIDATION_BUFFER 5%, trigger_price=None
        s3 = preview.stages[2]
        assert s3.trigger_mode == "LIQUIDATION_BUFFER"
        assert s3.trigger_percent == Decimal("5")
        assert s3.trigger_price is None
        assert s3.planned_capital == Decimal("350")


class TestFiveStages:
    def test_5_stage_short_with_per_stage_trigger_pct(self) -> None:
        calc = StrategyCalculator(_btc_rule())
        preview = calc.calculate_preview(
            **_common_kwargs(),
            stages_config={
                "capitals": ["300", "500", "700", "900", "1200"],
                "trigger_percents": [None, 8, 12, 15, None],
                "last_stage_trigger_mode": "LIQUIDATION_BUFFER",
                "last_stage_trigger_percent": "5",
            },
        )
        assert len(preview.stages) == 5
        # stage 2: +8%
        assert preview.stages[1].trigger_percent == Decimal("8")
        # stage 3: +12%
        assert preview.stages[2].trigger_percent == Decimal("12")
        # stage 4: +15%
        assert preview.stages[3].trigger_percent == Decimal("15")
        # stage 5: LIQUIDATION_BUFFER
        assert preview.stages[4].trigger_mode == "LIQUIDATION_BUFFER"


class TestTenStages:
    def test_10_stage_short_default_pct(self) -> None:
        calc = StrategyCalculator(_btc_rule())
        capitals = ["1000", "3000", "5000", "9000", "12000", "15000", "20000", "30000", "40000", "70000"]
        preview = calc.calculate_preview(
            **_common_kwargs(start_price="100000"),
            stages_config={"capitals": capitals},
        )
        assert len(preview.stages) == 10
        # 1: IMMEDIATE
        assert preview.stages[0].trigger_mode == "IMMEDIATE"
        # 2~9: PRICE_UP_PCT default 10%
        for i in range(1, 9):
            assert preview.stages[i].trigger_mode == "PRICE_UP_PCT"
            assert preview.stages[i].trigger_percent == Decimal("10")
        # 10: 마지막은 LIQUIDATION_BUFFER (default for SHORT)
        assert preview.stages[9].trigger_mode == "LIQUIDATION_BUFFER"
        assert preview.stages[9].trigger_price is None


class TestLongSide:
    def test_long_default_last_stage_is_price_down_20pct(self) -> None:
        calc = StrategyCalculator(_btc_rule())
        preview = calc.calculate_preview(
            **_common_kwargs(start_price="100000", side="LONG"),
            stages_config={"capitals": ["100", "200", "300"]},
        )
        # 마지막 단계 (LONG): PRICE_DOWN_PCT 20%
        last = preview.stages[-1]
        assert last.trigger_mode == "PRICE_DOWN_PCT"
        assert last.trigger_percent == Decimal("20")
        # 가격이 산출되어 있어야 함 (LIQUIDATION_BUFFER 가 아니므로)
        assert last.trigger_price is not None


class TestValidation:
    def test_empty_stages_raises(self) -> None:
        calc = StrategyCalculator(_btc_rule())
        with pytest.raises(ValueError, match="capitals"):
            calc.calculate_preview(**_common_kwargs(), stages_config={"capitals": []})

    def test_too_many_stages_raises(self) -> None:
        calc = StrategyCalculator(_btc_rule())
        with pytest.raises(ValueError, match="stages count"):
            calc.calculate_preview(
                **_common_kwargs(),
                stages_config={"capitals": ["100"] * 11},
            )

    def test_zero_capital_raises(self) -> None:
        calc = StrategyCalculator(_btc_rule())
        with pytest.raises(ValueError, match="must be > 0"):
            calc.calculate_preview(
                **_common_kwargs(),
                stages_config={"capitals": ["100", "0", "200"]},
            )


class TestSingleStage:
    def test_single_stage_is_immediate_only(self) -> None:
        calc = StrategyCalculator(_btc_rule())
        preview = calc.calculate_preview(
            **_common_kwargs(),
            stages_config={"capitals": ["1000"]},
        )
        # 1단계만 있는 경우 — first 와 last 가 같으므로 마지막 단계 규칙 적용
        # 우리 로직상 첫 단계가 우선 처리되므로 IMMEDIATE
        assert len(preview.stages) == 1
        assert preview.stages[0].trigger_mode == "IMMEDIATE"
