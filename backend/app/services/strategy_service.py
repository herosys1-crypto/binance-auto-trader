from decimal import Decimal
from typing import Any

from app.core.strategy_status import TERMINAL_STATUSES
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
        # 2026-05-03 강화: CLOSED_BY_TP/SL / KILL_SWITCH_TRIGGERED 도 종료 분류 추가.
        # 2026-05-03 PM 좀비 사례 수정: STOPPING 은 "닫는 중" — 거래소 청산이 아직
        # 진행/완료 미확인 상태이므로 closed 가 아닌 "active" 로 봐야 신규 진입 충돌 방지.
        # (이전엔 STOPPING 을 closed 로 분류 → reconcile 청산 완료 직전 race window 에서
        #  신규 strategy 가 같은 symbol+side 로 진입해 거래소 통합 포지션을 두 strategy 가
        #  점유하는 좀비 발생 — #89/#90 LABUSDT 사례)
        from sqlalchemy import select
        # 2026-05-04: 공통 TERMINAL_STATUSES 사용 (이전엔 inline set 이라 admin.py 와 drift).
        _CLOSED_STATUSES = TERMINAL_STATUSES
        existing = self.db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.exchange_account_id == exchange_account_id)
            .where(StrategyInstance.symbol == symbol)
            .where(StrategyInstance.side == side)
            .where(StrategyInstance.status.notin_(_CLOSED_STATUSES))
            .where(StrategyInstance.is_archived.is_(False))  # 2026-05-06 C-full
            .order_by(StrategyInstance.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if existing:
            # 2026-05-04 fix: STOPPING 인 경우 사용자가 어떻게 해결할지 명확한 가이드 제공.
            # backend 가 STOPPING 을 active 로 분류하는 건 race window 보호 (commit 6133072).
            # 사용자는 reconcile 자동 정리 (30초) 또는 force-stop 으로 즉시 해결 가능.
            if existing.status == "STOPPING":
                hint = (
                    f" 현재 #{existing.id} 는 STOPPING (청산 진행 중) — reconcile_worker 가 30초마다 "
                    f"거래소 포지션 0 확인 시 자동으로 STOPPED 승격합니다. "
                    f"잠시 후 다시 시도하거나, 거래소에 잔재 포지션이 없는 게 확실하면 "
                    f"`POST /api/v1/strategies/{existing.id}/force-stop` 으로 즉시 STOPPED 마킹 가능."
                )
            else:
                hint = " 기존 전략을 종료(/stop) 한 후 새로 시작하시거나, 다른 심볼/방향을 선택해 주세요."
            raise ValueError(
                f"같은 거래소/심볼/방향 ({symbol} {side}) 으로 활성 전략 #{existing.id} ({existing.status}) 가 이미 있습니다. "
                "Binance 는 통합 포지션으로만 관리하므로 중복 전략은 TP/SL 충돌을 일으킵니다."
                + hint
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
        from app.services.account_kill_switch_service import AccountKillSwitchService
        from decimal import Decimal as D
        import logging
        _logger = logging.getLogger(__name__)

        # 0) Kill switch 사전 체크 (2026-05-04 fix):
        # 이전엔 start_stage1 단계에서만 체크 → strategy DB row 가 만들어진 후 차단되어
        # WAITING 상태 잔재 발생. 이제 create 시점에 차단해 DB 깨끗.
        if AccountKillSwitchService(self.db).is_enabled(exchange_account_id):
            raise ValueError(
                f"거래소 계정 #{exchange_account_id} 의 Kill-Switch 가 활성화돼 있습니다. "
                "신규 전략 생성 차단. Kill-Switch 를 해제한 후 재시도하세요."
            )

        # 실효 leverage 산출 (이후 여러 가드에서 공통 사용).
        from app.core.config import settings as _settings
        effective_lev_check = leverage_override if leverage_override is not None else (template_model.leverage or 1)

        # 0-Z) 레버리지 상한 (MAINNET-CHECKLIST 3-4, 2026-05-07).
        # Binance API 는 최대 125x 까지 허용하지만 청산 위험 큼. settings.max_leverage 양수면 가드.
        max_lev = _settings.max_leverage
        if max_lev and max_lev > 0:
            if effective_lev_check > max_lev:
                raise ValueError(
                    f"레버리지 {effective_lev_check}x > 한도 {max_lev}x 초과. "
                    f"운영 정책 (settings.max_leverage) 으로 차단. "
                    "leverage_override 줄이거나 templete.leverage 줄여 재시도하세요."
                )

        # 0-A) 심볼 화이트리스트 (MAINNET-CHECKLIST 3-3, 2026-05-07).
        # mainnet 초기엔 high-liquidity 심볼만 허용 (slippage / liquidity 위험 ↓).
        # settings.allowed_symbols_csv 가 비어 있으면 모든 심볼 허용 (testnet / 개발 default).
        allowed = _settings.allowed_symbols_set
        if allowed and symbol.upper() not in allowed:
            raise ValueError(
                f"심볼 {symbol} 가 허용 목록에 없음. 운영자 설정 (allowed_symbols_csv): "
                f"{sorted(allowed)}. mainnet 초기엔 high-liquidity 심볼만 허용 권장."
            )

        # 0-B) 동시 활성 strategy 수 한도 (계정당). 환경변수로 조정 가능.
        # 거래소 API rate limit 보호 + 모니터링 단순화. 권장: mainnet 초기 3~5개.
        max_concurrent = max(1, _settings.max_concurrent_strategies_per_account)
        active_count = self.db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.exchange_account_id == exchange_account_id)
            .where(StrategyInstance.status.notin_(_CLOSED_STATUSES))
        ).all()
        if len(active_count) >= max_concurrent:
            raise ValueError(
                f"이 거래소 계정의 동시 활성 전략 수 한도 ({max_concurrent}개) 초과. "
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

        # 1-Z) 청산가 안전 거리 가드 (MAINNET-CHECKLIST 3-5, 2026-05-07).
        # 진입 직후 추정 청산가까지의 거리가 너무 가까우면 거부 (작은 가격 변동에 강제 청산 위험).
        # 추정 공식 (Isolated, conservative): SHORT: liq = entry × (1 + (1-mmr)/lev) | LONG: × (1 - ...)
        # mmr (maintenance margin ratio) = 0.5% (작은 포지션, 보수적).
        min_liq_dist = _settings.min_liquidation_distance_pct
        if min_liq_dist and min_liq_dist > 0:
            from decimal import Decimal as _D
            mmr = _D("0.005")
            lev_d = _D(str(effective_lev_check)) if effective_lev_check else _D("1")
            distance_pct_est = ((_D("1") - mmr) / lev_d * _D("100")).quantize(_D("0.01"))
            if distance_pct_est < _D(str(min_liq_dist)):
                raise ValueError(
                    f"청산가 안전 거리 부족: 추정 거리 {distance_pct_est}% < 한도 {min_liq_dist}% "
                    f"(레버리지 {effective_lev_check}x 일 때 추정 거리 ≈ {distance_pct_est}%). "
                    "레버리지를 낮추거나 settings.min_liquidation_distance_pct 를 조정하세요."
                )

        # 1-A) 단일 strategy 자본 상한 % (MAINNET-CHECKLIST 3-3, 2026-05-07).
        # template.total_capital 이 가용 잔액의 N% 초과 시 거부 — 한 전략에 자본 집중 차단.
        # settings.max_strategy_capital_pct_of_balance 가 None / 0 / 음수면 비활성.
        max_pct = _settings.max_strategy_capital_pct_of_balance
        if max_pct and max_pct > 0 and available > 0:
            cap_limit = (available * D(str(max_pct)) / D("100")).quantize(D("0.01"))
            tpl_cap = D(str(template_model.total_capital))
            if tpl_cap > cap_limit:
                raise ValueError(
                    f"단일 전략 자본 상한 초과: {tpl_cap} USDT > {cap_limit} USDT "
                    f"(가용 잔액 {available} 의 {max_pct}%). "
                    "자본을 줄이거나 max_strategy_capital_pct_of_balance 설정을 조정하세요."
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
