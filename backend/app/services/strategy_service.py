from decimal import Decimal
from typing import Any

from app.models.strategy_instance import StrategyInstance
from app.models.strategy_stage_plan import StrategyStagePlan
from app.repositories.strategy_repository import StrategyRepository
from app.services.strategy_calculator import StrategyCalculator, SymbolRule


class StrategyService:
    def __init__(self, db) -> None:
        self.db = db
        self.repo = StrategyRepository(db)

    @staticmethod
    def _resolve_stages_config(template_model) -> dict[str, Any]:
        """DB 템플릿에서 stages_config 추출. 신규 컬럼 우선, 없으면 구 컬럼에서 변환."""
        if template_model.stages_config:
            return dict(template_model.stages_config)
        # 구 4단계 자동 변환 (마이그레이션이 안 됐던 row 대비)
        return {
            "capitals": [
                template_model.stage1_capital,
                template_model.stage2_capital,
                template_model.stage3_capital,
                template_model.stage4_capital,
            ],
            "trigger_percents": [
                None,
                template_model.stage2_trigger_percent,
                template_model.stage3_trigger_percent,
                None,
            ],
            "last_stage_trigger_mode": template_model.stage4_trigger_mode,
            "last_stage_trigger_percent": template_model.stage4_trigger_percent,
        }

    def calculate_preview(self, *, symbol: str, side: str, start_price: Decimal, strategy_template_id: int, leverage_override: int | None = None):
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
        stages_config = self._resolve_stages_config(template_model)
        # UX #18: leverage_override 가 있으면 그것을, 아니면 템플릿 기본값을 사용.
        effective_leverage = leverage_override if leverage_override is not None else template_model.leverage
        return calculator.calculate_preview(
            symbol=symbol,
            side=side,
            start_price=start_price,
            stages_config=stages_config,
            leverage=effective_leverage,
            total_capital=Decimal(template_model.total_capital),
            tp1_percent=Decimal(template_model.tp1_percent),
            tp2_percent=Decimal(template_model.tp2_percent),
            tp3_percent=Decimal(template_model.tp3_percent),
            stop_loss_percent_of_capital=Decimal(template_model.stop_loss_percent_of_capital),
        )

    def create_strategy_instance(self, *, user_id: int, exchange_account_id: int, strategy_template_id: int, symbol: str, side: str, start_price: Decimal, leverage_override: int | None = None) -> StrategyInstance:
        template_model = self.repo.get_template(strategy_template_id)
        symbol_model = self.repo.get_symbol(symbol)
        if not template_model or not symbol_model:
            raise ValueError("Template or symbol not found")
        preview = self.calculate_preview(symbol=symbol, side=side, start_price=start_price, strategy_template_id=strategy_template_id, leverage_override=leverage_override)
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
