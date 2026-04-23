from decimal import Decimal
from app.services.strategy_calculator import StrategyCalculator, SymbolRule, StrategyTemplate

def test_short_strategy_preview():
    calculator = StrategyCalculator(SymbolRule(symbol="BTCUSDT", tick_size=Decimal("0.1"), step_size=Decimal("0.001"), min_qty=Decimal("0.001"), price_precision=1, quantity_precision=3))
    template = StrategyTemplate(name="short_2x_trend", side="SHORT", leverage=2, total_capital=Decimal("1100"), stage1_capital=Decimal("100"), stage2_capital=Decimal("200"), stage3_capital=Decimal("300"), stage4_capital=Decimal("500"), stage2_trigger_percent=Decimal("10"), stage3_trigger_percent=Decimal("20"), stage4_trigger_mode="LIQUIDATION_BUFFER", stage4_trigger_percent=Decimal("5"), tp1_percent=Decimal("10"), tp2_percent=Decimal("20"), tp3_percent=Decimal("30"), tp1_qty_ratio=Decimal("25"), tp2_qty_ratio=Decimal("50"), tp3_qty_ratio=Decimal("25"), stop_loss_percent_of_capital=Decimal("50"))
    preview = calculator.calculate_preview(symbol="BTCUSDT", side="SHORT", start_price=Decimal("100000"), template=template)
    assert preview.leverage == 2
    assert preview.stages[0].trigger_price == Decimal("100000.0")
