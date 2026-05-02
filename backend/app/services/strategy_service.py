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
        # 종료된 상태 (모두 _CLOSED_STATUSES 에 포함) 는 제외 — 새로 시작 가능.
        # 2026-05-03 강화: STOPPING / CLOSED_BY_TP/SL / KILL_SWITCH_TRIGGERED 도 종료 분류 추가.
        from sqlalchemy import select
        _CLOSED_STATUSES = {
            "STOPPED", "STOPPING", "COMPLETED", "CLOSED",
            "CLOSED_BY_TP", "CLOSED_BY_SL", "REENTRY_READY",
            "KILL_SWITCH_TRIGGERED",
        }
        existing = self.db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.exchange_account_id == exchange_account_id)
            .where(StrategyInstance.symbol == symbol)
            .where(StrategyInstance.side == side)
            .where(StrategyInstance.status.notin_(_CLOSED_STATUSES))
            .order_by(StrategyInstance.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if existing:
            raise ValueError(
                f"같은 거래소/심볼/방향 ({symbol} {side}) 으로 활성 전략 #{existing.id} ({existing.status}) 가 이미 있습니다. "
                "Binance 는 통합 포지션으로만 관리하므로 중복 전략은 TP/SL 충돌을 일으킵니다. "
                "기존 전략을 종료한 후 새로 시작하시거나, 다른 심볼/방향을 선택해 주세요."
            )
        # 잔액/마진 사전 안전 체크 (2026-05-03 강화):
        # 1) 가용 잔액 < 필요 마진 → 거부 (자본 부족)
        # 2) 마진 비율 > 80% → 거부 (청산 위험)
        # 3) 거래소 API 호출 실패 → 거부 (안전 우선, 이전엔 silent skip 이라 문제)
        # 4) 동시 활성 전략 수 한도 (configurable, 안전장치)
        # 마진 = total_capital / 실효 leverage (override 가 있으면 그것 사용)
        from app.integrations.binance.client import BinanceClient
        from app.core.crypto import decrypt_text
        from app.models.exchange_account import ExchangeAccount as _EA
        from decimal import Decimal as D
        import logging
        _logger = logging.getLogger(__name__)

        # 동시 활성 전략 수 한도 (예: 한 계정당 최대 8개) — 거래소 부담 + 모니터링 단순화
        MAX_CONCURRENT_PER_ACCOUNT = 10
        active_count = self.db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.exchange_account_id == exchange_account_id)
            .where(StrategyInstance.status.notin_(_CLOSED_STATUSES))
        ).all()
        if len(active_count) >= MAX_CONCURRENT_PER_ACCOUNT:
            raise ValueError(
                f"이 거래소 계정의 동시 활성 전략 수 한도 ({MAX_CONCURRENT_PER_ACCOUNT}개) 초과. "
                f"현재 {len(active_count)}개. 일부 전략을 종료한 후 새로 시작하세요."
            )

        ex_account = self.db.get(_EA, exchange_account_id)
        if not ex_account:
            raise ValueError(f"거래소 계정 #{exchange_account_id} 를 찾을 수 없습니다.")

        try:
            client = BinanceClient(
                api_key=decrypt_text(ex_account.api_key_enc),
                api_secret=decrypt_text(ex_account.api_secret_enc),
                is_testnet=ex_account.is_testnet,
            )
            acct = client.get_account()
        except Exception as e:
            # 안전 우선: 거래소 API 호출 실패 시 차단 (이전 silent skip → 사고 가능성)
            _logger.error("balance pre-check Binance call failed: %s", e)
            raise ValueError(
                f"거래소 잔액 확인 실패 (안전상 신규 전략 차단): {e}. "
                "잠시 후 다시 시도하거나 거래소 API 상태를 확인하세요."
            )

        # 거래소 실 포지션 사전 체크 (2026-05-03 강화):
        # DB status race 시 (예: STAGE1_OPEN_PENDING → REENTRY_READY 일시 전환 → 다시 active)
        # 같은 (symbol, position_side) 의 거래소 실 포지션이 있으면 중복 차단.
        # Binance hedge mode 의 통합 포지션 보호 — 가장 강력한 마지막 방어선.
        try:
            positions = acct.get("positions") or []
            for p in positions:
                if (
                    p.get("symbol") == symbol
                    and p.get("positionSide") == side
                    and abs(D(str(p.get("positionAmt", "0")))) > 0
                ):
                    raise ValueError(
                        f"거래소에 이미 {symbol} {side} 포지션 {p.get('positionAmt')} 가 존재합니다. "
                        "(우리 시스템에 활성 strategy 가 없어도 거래소 포지션이 있으면 중복) "
                        "기존 포지션을 정리한 후 새 전략을 시작하세요."
                    )
        except ValueError:
            raise
        except Exception as e:
            _logger.warning("exchange position pre-check failed (proceeding): %s", e)

        available = D(str(acct.get("availableBalance", "0")))
        total_margin = D(str(acct.get("totalMarginBalance", "0")))
        total_maint = D(str(acct.get("totalMaintMargin", "0")))

        # 실효 레버리지 = leverage_override 우선 (없으면 template default)
        effective_lev = D(str(leverage_override)) if leverage_override else D(str(template_model.leverage or 1))
        if effective_lev <= 0:
            effective_lev = D("1")
        required_margin = (D(str(template_model.total_capital)) / effective_lev).quantize(D("0.01"))

        # 1) 가용 잔액 체크
        if required_margin > available:
            raise ValueError(
                f"잔액 부족: 필요 마진 {required_margin} USDT > 가용 잔액 {available} USDT. "
                f"(자본 {template_model.total_capital} ÷ 레버리지 {effective_lev}x). "
                "거래소에 입금하거나 자본을 줄이세요."
            )

        # 2) 마진 비율 한도 (현재 + 새 전략 후 예상)
        if total_margin > 0:
            current_ratio_pct = (total_maint / total_margin * 100).quantize(D("0.01"))
            # 청산 위험 차단: 현재 비율이 이미 80% 넘으면 신규 진입 거부
            MAX_MARGIN_RATIO_PCT = D("80")
            if current_ratio_pct > MAX_MARGIN_RATIO_PCT:
                raise ValueError(
                    f"마진 비율 {current_ratio_pct}% > {MAX_MARGIN_RATIO_PCT}% 한도. 청산 위험. "
                    "기존 포지션을 정리하거나 입금 후 시도하세요."
                )
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
