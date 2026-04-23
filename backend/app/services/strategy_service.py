from decimal import Decimal
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_stage_plan import StrategyStagePlan
from app.repositories.strategy_repository import StrategyRepository
from app.services.strategy_calculator import StrategyCalculator, StrategyTemplate, SymbolRule

class StrategyService:
    def __init__(self, db) -> None:
        self.db = db
        self.repo = StrategyRepository(db)

    def _build_template(self, template_model) -> StrategyTemplate:
        return StrategyTemplate(
            name=template_model.name,
            side=template_model.side,
            leverage=template_model.leverage,
            total_capital=Decimal(template_model.total_capital),
            stage1_capital=Decimal(template_model.stage1_capital),
            stage2_capital=Decimal(template_model.stage2_capital),
            stage3_capital=Decimal(template_model.stage3_capital),
            stage4_capital=Decimal(template_model.stage4_capital),
            stage2_trigger_percent=Decimal(template_model.stage2_trigger_percent),
            stage3_trigger_percent=Decimal(template_model.stage3_trigger_percent),
            stage4_trigger_mode=template_model.stage4_trigger_mode,
            stage4_trigger_percent=Decimal(template_model.stage4_trigger_percent or 0),
            tp1_percent=Decimal(template_model.tp1_percent),
            tp2_percent=Decimal(template_model.tp2_percent),
            tp3_percent=Decimal(template_model.tp3_percent),
            tp1_qty_ratio=Decimal(template_model.tp1_qty_ratio),
            tp2_qty_ratio=Decimal(template_model.tp2_qty_ratio),
            tp3_qty_ratio=Decimal(template_model.tp3_qty_ratio),
            stop_loss_percent_of_capital=Decimal(template_model.stop_loss_percent_of_capital),
            reentry_policy=template_model.reentry_policy,
        )

    def calculate_preview(self, *, symbol: str, side: str, start_price: Decimal, strategy_template_id: int):
        template_model = self.repo.get_template(strategy_template_id)
        symbol_model = self.repo.get_symbol(symbol)
        if not template_model or not symbol_model:
            raise ValueError("Strategy template or symbol not found")
        symbol_rule = SymbolRule(
            symbol=symbol_model.symbol,
            tick_size=Decimal(symbol_model.tick_size or 0),
            step_size=Decimal(symbol_model.step_size or 0),
            min_qty=Decimal(symbol_model.min_qty or 0),
            price_precision=symbol_model.price_precision or 8,
            quantity_precision=symbol_model.quantity_precision or 8,
        )
        calculator = StrategyCalculator(symbol_rule)
        return calculator.calculate_preview(symbol=symbol, side=side, start_price=start_price, template=self._build_template(template_model))

    def create_strategy_instance(self, *, user_id: int, exchange_account_id: int, strategy_template_id: int, symbol: str, side: str, start_price: Decimal) -> StrategyInstance:
        template_model = self.repo.get_template(strategy_template_id)
        symbol_model = self.repo.get_symbol(symbol)
        if not template_model or not symbol_model:
            raise ValueError("Template or symbol not found")
        preview = self.calculate_preview(symbol=symbol, side=side, start_price=start_price, strategy_template_id=strategy_template_id)
        instance = StrategyInstance(
            user_id=user_id,
            exchange_account_id=exchange_account_id,
            strategy_template_id=strategy_template_id,
            symbol_id=symbol_model.id,
            symbol=symbol,
            side=side,
            start_price=start_price,
            leverage=preview.leverage,
            total_capital=template_model.total_capital,
            status="WAITING",
        )
        self.repo.create_strategy_instance(instance)
        plans = [StrategyStagePlan(strategy_instance_id=instance.id, stage_no=s.stage_no, side=side, trigger_mode=s.trigger_mode, trigger_percent=s.trigger_percent, trigger_price=s.trigger_price, planned_capital=s.planned_capital, planned_qty=s.planned_qty) for s in preview.stages]
        self.repo.create_stage_plans(plans)
        self.db.commit()
        self.db.refresh(instance)
        return instance
