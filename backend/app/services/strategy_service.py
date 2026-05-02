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
        # 중복 방지 (Critical): Binance 는 같은 심볼+방향에 대해 통합 포지션으로만 관리.
        # 같은 계정/심볼/방향 활성 전략이 있으면 새 전략 생성을 거부 (TP/SL 충돌, qty 추적 오류 회피).
        # 종료된 상태 (STOPPED/COMPLETED/CLOSED/REENTRY_READY) 는 제외 — 새로 시작 가능.
        from sqlalchemy import select
        _CLOSED_STATUSES = {"STOPPED", "COMPLETED", "CLOSED", "REENTRY_READY"}
        existing = self.db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.exchange_account_id == exchange_account_id)
            .where(StrategyInstance.symbol == symbol)
            .where(StrategyInstance.side == side)
            .where(StrategyInstance.status.notin_(_CLOSED_STATUSES))
            .limit(1)
        ).scalar_one_or_none()
        if existing:
            raise ValueError(
                f"같은 거래소/심볼/방향 ({symbol} {side}) 으로 활성 전략 #{existing.id} ({existing.status}) 가 이미 있습니다. "
                "Binance 는 통합 포지션으로만 관리하므로 중복 전략은 TP/SL 충돌을 일으킵니다. "
                "기존 전략을 종료한 후 새로 시작하시거나, 다른 심볼/방향을 선택해 주세요."
            )
        # 잔액 사전 체크 (2026-05-03 추가):
        # 새 전략의 총 자본이 거래소 가용 잔액 (availableBalance) 을 초과하면 거부.
        # mainnet 에서 자본 부족 진입은 거래소가 -2019 (Margin is insufficient) 로 거절하고
        # 우리 시스템은 STAGE1_OPEN_PENDING 좀비로 빠짐 → 사전 차단이 안전.
        # 마진 = total_capital / leverage 기준으로 계산.
        try:
            from app.integrations.binance.client import BinanceClient
            from app.core.crypto import decrypt_text
            from decimal import Decimal as D
            ex_account = self.db.get(self.repo.ExchangeAccount, exchange_account_id) if hasattr(self.repo, "ExchangeAccount") else None
            from app.models.exchange_account import ExchangeAccount as _EA
            ex_account = self.db.get(_EA, exchange_account_id)
            if ex_account:
                client = BinanceClient(
                    api_key=decrypt_text(ex_account.api_key_enc),
                    api_secret=decrypt_text(ex_account.api_secret_enc),
                    is_testnet=ex_account.is_testnet,
                )
                acct = client.get_account()
                available = D(str(acct.get("availableBalance", "0")))
                lev = D(str(template_model.leverage)) if template_model.leverage else D("1")
                required_margin = (D(str(template_model.total_capital)) / lev).quantize(D("0.01"))
                if required_margin > available:
                    raise ValueError(
                        f"잔액 부족: 필요 마진 {required_margin} USDT > 가용 잔액 {available} USDT. "
                        f"(자본 {template_model.total_capital} ÷ 레버리지 {lev}x). "
                        "거래소에 입금하거나 자본을 줄이세요."
                    )
        except ValueError:
            raise
        except Exception as e:
            # 거래소 API 일시적 장애는 무시 (warn 만), 거래 차단 안 함
            import logging
            logging.getLogger(__name__).warning("balance pre-check failed (skipping): %s", e)
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
