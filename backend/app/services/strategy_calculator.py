from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, getcontext
from typing import Literal

getcontext().prec = 28
Side = Literal["LONG", "SHORT"]

@dataclass(frozen=True)
class SymbolRule:
    symbol: str
    tick_size: Decimal
    step_size: Decimal
    min_qty: Decimal
    price_precision: int
    quantity_precision: int

@dataclass(frozen=True)
class StrategyTemplate:
    name: str
    side: Side
    leverage: int
    total_capital: Decimal
    stage1_capital: Decimal
    stage2_capital: Decimal
    stage3_capital: Decimal
    stage4_capital: Decimal
    stage2_trigger_percent: Decimal
    stage3_trigger_percent: Decimal
    stage4_trigger_mode: str
    stage4_trigger_percent: Decimal | None
    tp1_percent: Decimal
    tp2_percent: Decimal
    tp3_percent: Decimal
    tp1_qty_ratio: Decimal
    tp2_qty_ratio: Decimal
    tp3_qty_ratio: Decimal
    stop_loss_percent_of_capital: Decimal
    reentry_policy: str = "manual_ready"

@dataclass(frozen=True)
class StagePlan:
    stage_no: int
    trigger_mode: str
    planned_capital: Decimal
    trigger_percent: Decimal | None = None
    trigger_price: Decimal | None = None
    planned_qty: Decimal | None = None

@dataclass(frozen=True)
class StrategyPreview:
    symbol: str
    side: Side
    leverage: int
    stages: list[StagePlan]
    tp1_percent: Decimal
    tp2_percent: Decimal
    tp3_percent: Decimal
    stop_loss_amount: Decimal

class StrategyCalculator:
    def __init__(self, symbol_rule: SymbolRule) -> None:
        self.symbol_rule = symbol_rule

    def calculate_preview(self, *, symbol: str, side: Side, start_price: Decimal, template: StrategyTemplate) -> StrategyPreview:
        stage1 = self._stage1(start_price, template.stage1_capital)
        stage2 = self._stage2(side, stage1.trigger_price, template.stage2_capital, template.stage2_trigger_percent)
        stage3 = self._stage3(side, stage2.trigger_price, template.stage3_capital, template.stage3_trigger_percent)
        stage4 = self._stage4(side, stage3.trigger_price, template.stage4_capital, template.stage4_trigger_mode)
        stop_loss_amount = self._quantize_price(template.total_capital * (template.stop_loss_percent_of_capital / Decimal("100")))
        return StrategyPreview(symbol=symbol, side=side, leverage=template.leverage, stages=[stage1, stage2, stage3, stage4], tp1_percent=template.tp1_percent, tp2_percent=template.tp2_percent, tp3_percent=template.tp3_percent, stop_loss_amount=stop_loss_amount)

    def compute_short_stage4_trigger_from_liquidation(self, liquidation_price: Decimal) -> Decimal:
        return self._quantize_price(liquidation_price * Decimal("0.95"))

    def compute_tp_prices(self, *, side: Side, avg_entry_price: Decimal) -> dict[str, Decimal]:
        if side == "LONG":
            vals = [avg_entry_price * Decimal("1.10"), avg_entry_price * Decimal("1.20"), avg_entry_price * Decimal("1.30")]
        else:
            vals = [avg_entry_price * Decimal("0.90"), avg_entry_price * Decimal("0.80"), avg_entry_price * Decimal("0.70")]
        return {"tp1": self._quantize_price(vals[0]), "tp2": self._quantize_price(vals[1]), "tp3": self._quantize_price(vals[2])}

    def compute_qty_from_capital(self, *, capital: Decimal, price: Decimal) -> Decimal:
        qty = self._quantize_qty(capital / price)
        if qty < self.symbol_rule.min_qty:
            raise ValueError("calculated quantity below min_qty")
        return qty

    def _stage1(self, start_price: Decimal, capital: Decimal) -> StagePlan:
        price = self._quantize_price(start_price)
        qty = self.compute_qty_from_capital(capital=capital, price=price)
        return StagePlan(stage_no=1, trigger_mode="IMMEDIATE", trigger_price=price, planned_capital=capital, planned_qty=qty)

    def _stage2(self, side: Side, reference_price: Decimal, capital: Decimal, pct: Decimal) -> StagePlan:
        multiplier = Decimal("1") + (pct/Decimal("100")) if side == "SHORT" else Decimal("1") - (pct/Decimal("100"))
        price = self._quantize_price(reference_price * multiplier)
        qty = self.compute_qty_from_capital(capital=capital, price=price)
        return StagePlan(stage_no=2, trigger_mode="PRICE_UP_PCT" if side == "SHORT" else "PRICE_DOWN_PCT", trigger_percent=pct, trigger_price=price, planned_capital=capital, planned_qty=qty)

    def _stage3(self, side: Side, reference_price: Decimal, capital: Decimal, pct: Decimal) -> StagePlan:
        multiplier = Decimal("1") + (pct/Decimal("100")) if side == "SHORT" else Decimal("1") - (pct/Decimal("100"))
        price = self._quantize_price(reference_price * multiplier)
        qty = self.compute_qty_from_capital(capital=capital, price=price)
        return StagePlan(stage_no=3, trigger_mode="PRICE_UP_PCT" if side == "SHORT" else "PRICE_DOWN_PCT", trigger_percent=pct, trigger_price=price, planned_capital=capital, planned_qty=qty)

    def _stage4(self, side: Side, reference_price: Decimal, capital: Decimal, trigger_mode: str) -> StagePlan:
        if side == "SHORT":
            return StagePlan(stage_no=4, trigger_mode=trigger_mode, trigger_percent=Decimal("5"), trigger_price=None, planned_capital=capital, planned_qty=None)
        price = self._quantize_price(reference_price * Decimal("0.80"))
        qty = self.compute_qty_from_capital(capital=capital, price=price)
        return StagePlan(stage_no=4, trigger_mode="PRICE_DOWN_PCT", trigger_percent=Decimal("20"), trigger_price=price, planned_capital=capital, planned_qty=qty)

    def _quantize_price(self, value: Decimal) -> Decimal:
        if self.symbol_rule.tick_size == 0:
            return value
        return (value // self.symbol_rule.tick_size) * self.symbol_rule.tick_size

    def _quantize_qty(self, value: Decimal) -> Decimal:
        if self.symbol_rule.step_size == 0:
            return value
        return (value // self.symbol_rule.step_size) * self.symbol_rule.step_size
