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
            raise ValueError("⚠️ 전략 템플릿 또는 심볼 정보를 찾을 수 없습니다. 운영자에게 문의하세요.")

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
            raise ValueError("⚠️ 전략 템플릿 또는 심볼 정보를 찾을 수 없습니다. 운영자에게 문의하세요.")
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
        # 2026-05-10 (사용자 요청): 같은 심볼+방향 중복 차단을 env 토글로 비활성 가능.
        # ALLOW_DUPLICATE_SYMBOL_STRATEGIES=true 면 차단 skip — 사용자가 위험 감수.
        _CLOSED_STATUSES = TERMINAL_STATUSES
        from app.core.config import settings as _settings_dup
        _allow_dup = getattr(_settings_dup, "allow_duplicate_symbol_strategies", False)
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
        if existing and not _allow_dup:
            # 2026-05-04 fix: STOPPING 인 경우 사용자가 어떻게 해결할지 명확한 가이드 제공.
            # 2026-05-15 fix (사용자 #57 MLNUSDT 보고): STOPPING 5분 이상 stuck 시
            # 「30초 안에 자동」 안내가 부정확 → 경과 시간 표시 + force-stop endpoint 명시.
            # 2026-05-21 Phase 2 (사장님 요구): MANUAL_CLEANUP_REQUIRED 별도 가이드.
            if existing.status == "MANUAL_CLEANUP_REQUIRED":
                hint = (
                    f"\n\n🆘 전략 #{existing.id} 는 「수동 청산 요청」 상태입니다. "
                    f"이전 청산이 거래소에서 거절돼 사장님이 직접 처리해야 합니다.\n\n"
                    f"💡 해결:\n"
                    f"  1) Binance 거래소 UI 에서 {symbol} {side} 포지션 직접 청산\n"
                    f"  2) 대시보드에서 #{existing.id} 의 「✅ 처리 완료」 클릭 → STOPPED 전환\n"
                    f"  3) 그 후 새 전략 시작 가능\n\n"
                    f"※ 자동 STOPPED 전환 차단된 상태 — 명시적 ack 필수."
                )
            elif existing.status == "STOPPING":
                from datetime import datetime as _dt, timezone as _tz
                stopping_since = existing.stopped_at or existing.updated_at
                elapsed_min = None
                if stopping_since:
                    # sqlite/postgres tz-aware/naive 호환 — naive 면 utc 로 가정.
                    if stopping_since.tzinfo is None:
                        stopping_since = stopping_since.replace(tzinfo=_tz.utc)
                    elapsed_sec = (_dt.now(_tz.utc) - stopping_since).total_seconds()
                    elapsed_min = int(elapsed_sec / 60)
                # 5분 이상이면 stuck 가능성 높음 → force-stop 명시 안내
                if elapsed_min is not None and elapsed_min >= 5:
                    hint = (
                        f"\n\n🚨 전략 #{existing.id} 가 「청산 중」 상태로 {elapsed_min}분째 stuck — "
                        f"reconcile 자동 정리 실패 의심.\n\n"
                        f"💡 해결 (택1):\n"
                        f"  • POST /api/v1/strategies/{existing.id}/force-stop  (DB 만 STOPPED 마킹, 거래소 호출 X)\n"
                        f"  • 거래소에서 직접 잔량/미체결 확인 후 정리\n"
                        f"  • 「📦 보관 보기」 + 🗑 archive 후 재시도\n\n"
                        f"⚠️ force-stop 후 거래소에 잔량 있으면 「⚠️ archive 시 거래소 잔량 의심」 CRITICAL 알림 즉시 발송됩니다 (5-15 fix)."
                    )
                else:
                    elapsed_label = f" ({elapsed_min}분 경과)" if elapsed_min is not None else ""
                    hint = (
                        f"\n\n📌 전략 #{existing.id} 가 「청산 중」 상태{elapsed_label}. "
                        f"reconcile 가 1분~30초마다 자동 정리 시도 중 — 잠시 후 재시도하세요.\n"
                        f"5분 이상 stuck 시 force-stop endpoint 사용 가능."
                    )
            else:
                hint = (
                    "\n\n💡 해결 (택1):"
                    "\n  • 「⏸ 정지」 또는 「🛑 긴급 종료」 로 기존 전략 닫은 후 다시 시작"
                    "\n  • 다른 심볼/방향으로 진행"
                    "\n  • 차단 자체 해제 — .env 에 ALLOW_DUPLICATE_SYMBOL_STRATEGIES=true (위험 감수)"
                )
            raise ValueError(
                f"⚠️ {symbol} {side} 전략이 이미 진행 중입니다 (#{existing.id}). "
                f"Binance 는 한 종목/방향에 하나의 통합 포지션만 허용합니다. 중복 시 익절/손절이 충돌해 손실 위험이 큽니다."
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
                f"🔒 거래소 계정 #{exchange_account_id} 의 Kill-Switch 가 활성화돼 신규 거래가 차단됐습니다.\n\n"
                "💡 해결: 대시보드 상단의 빨간 배너에서 「🔓 해제」 버튼을 클릭한 후 다시 시도하세요. "
                "(보통 일일 손실 한도 도달 시 자동 발동됩니다.)"
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
                    f"⚠️ 레버리지가 너무 높습니다: {effective_lev_check}x (한도 {max_lev}x).\n\n"
                    f"💡 해결: 「레버리지」 입력값을 {max_lev}x 이하로 낮춰주세요. "
                    "높은 레버리지는 작은 가격 변동에도 강제 청산될 위험이 큽니다."
                )

        # 0-A) 심볼 화이트리스트 (MAINNET-CHECKLIST 3-3, 2026-05-07).
        # 2-단계 검사: env 에 list 있고 + DB toggle 가 enabled (또는 env 만 있고 toggle 없으면 default ON).
        # 운영자가 UI 체크박스로 .env 재시작 없이 on/off 가능 (system_settings.whitelist_enabled).
        allowed = _settings.allowed_symbols_set
        if allowed:
            from app.services.system_settings_service import SystemSettingsService
            wl_enabled = SystemSettingsService(self.db).is_whitelist_enabled(
                default_from_env=True  # env 에 값 있으면 default ON
            )
            if wl_enabled and symbol.upper() not in allowed:
                allowed_str = ", ".join(sorted(allowed))
                raise ValueError(
                    f"🚫 심볼 「{symbol}」 는 현재 허용되지 않습니다.\n\n"
                    f"📋 허용 심볼: {allowed_str}\n\n"
                    "💡 해결 (택1):\n"
                    f"  • 위 심볼 중 하나로 변경 (예: {sorted(allowed)[0]})\n"
                    "  • 「💼 계정」 모달의 「🔒 심볼 화이트리스트 적용」 체크 해제 (모든 심볼 허용)"
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
                f"⚠️ 이 거래소 계정에 이미 진행 중인 전략이 {len(active_count)}개 — 동시 운영 한도 ({max_concurrent}개) 입니다.\n\n"
                "💡 해결: 활성 전략 중 하나를 「⏸ 정지」 또는 「🛑 긴급 종료」 한 후 다시 시도하세요."
            )

        ex_account = self.db.get(_EA, exchange_account_id)
        if not ex_account:
            raise ValueError(
                f"⚠️ 거래소 계정 #{exchange_account_id} 를 찾을 수 없습니다.\n\n"
                "💡 해결: 「💼 계정」 모달에서 등록된 계정을 확인하세요."
            )

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
                f"⚠️ 거래소 (Binance) 와 통신 실패 — 안전을 위해 신규 전략 생성을 차단했습니다.\n\n"
                f"📋 상세: {e}\n\n"
                "💡 해결:\n"
                "  • 잠시 후 다시 시도\n"
                "  • API 키 만료/IP 변경 여부 확인 (「💼 계정」 → 「🔑 키 변경」)\n"
                "  • Binance 거래소 상태 페이지 확인"
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
                        f"⚠️ Binance 거래소에 {symbol} {side} 포지션 {p.get('positionAmt')} 가 이미 있습니다.\n\n"
                        "📌 우리 시스템에 활성 전략이 없어도, 거래소에 잔재 포지션이 있으면 중복 위험으로 차단됩니다.\n\n"
                        "💡 해결: Binance 웹 또는 앱에서 해당 포지션을 직접 정리한 후 다시 시도하세요."
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

        # 2026-05-11 (사용자 요청): 단계별 추가 증거금 합도 잔액 필요량에 포함.
        # stages_config.additional_margins 가 있으면 그 합을 required_margin 에 더함.
        # 진입 시점에 entry 마진 + 추가 증거금 모두 잠겨야 하므로.
        cfg_dict = template_model.stages_config or {}
        add_margins_raw = cfg_dict.get("additional_margins") or []
        try:
            additional_margin_sum = sum(
                (D(str(m)) for m in add_margins_raw if m and D(str(m)) > 0),
                D("0"),
            )
        except Exception:
            additional_margin_sum = D("0")
        required_margin_total = (required_margin + additional_margin_sum).quantize(D("0.01"))

        # 0-C) 전체 계획자본 예약 체크 (2026-05-19 사용자 요청 + 2026-06-01 자본 기준 강화).
        # 문제: availableBalance 는 「이미 진입한 단계」 마진만 반영. 기존 활성
        # 전략들의 미래 단계(미진입 2~N)는 미반영 → 생성 시점엔 잔액 넉넉해
        # 보여 다수 전략이 다 통과 → 나중 단계 트리거 누적 → Binance -2019.
        #
        # 2026-06-01 사장님 핵심 사상 강화: "거래소 잔액 기준으로 모든게 운영되어야 해.
        # 증거금 추가도, 포지션 추가도, 다음단계 진입도, 전략 세울 때 모든 걸 잔액 기준."
        # → 마진 기준 (capital/leverage) 이 아닌 「자본 절대값」 기준으로 검증 (더 엄격).
        # 효과: 레버리지 효과로 잔액 시뮬레이션 큰 영향 X. 사장님 자본 100% 보호.
        # 화면 「예약 X USDT」 표시 (exchange_accounts.py 의 reserved_for_strategies) 와
        # 동일한 기준 → UI 와 검증 일치.
        from app.models.strategy_template import StrategyTemplate as _ST
        from app.models.strategy_stage_plan import StrategyStagePlan as _SSP
        _active_rows = self.db.execute(
            select(StrategyInstance, _ST)
            .join(_ST, StrategyInstance.strategy_template_id == _ST.id)
            .where(StrategyInstance.exchange_account_id == exchange_account_id)
            .where(StrategyInstance.status.notin_(_CLOSED_STATUSES))
            .where(StrategyInstance.is_archived.is_(False))
        ).all()
        # 🚨 2026-06-09 사장님 critical silent bug fix v2:
        # 사장님 명시: "1000 입력 = 마진 500 = 사장님 자금. wallet 와 비교 = 마진 단위!"
        # = wallet validation = 자본 합 (notional) X = 마진 합 (= 자본 / leverage)
        #
        # 옛 v1 (잘못): existing_capital_reserved = stage_plans 합 (notional)
        # = 자본 3000 vs wallet 5500 = 단위 불일치 silent bug
        #
        # 신 v2 (정확): existing_margin_reserved = (stage_plans / leverage) 합 (margin)
        # = 마진 1500 + 신 마진 300 = 1800 vs wallet 5500 = 통과! ✅
        # = 사장님 자본 보호 = wallet 단위 일관성
        existing_margin_reserved = D("0")
        # stage_plans 일괄 조회 (= N+1 회피)
        _strategy_ids = [_si.id for _si, _ in _active_rows]
        _plans_sum_by_strategy: dict[int, D] = {}
        if _strategy_ids:
            _all_plans = self.db.execute(
                select(_SSP)
                .where(_SSP.strategy_instance_id.in_(_strategy_ids))
                .where(_SSP.is_enabled.is_(True))
            ).scalars().all()
            for _p in _all_plans:
                prev = _plans_sum_by_strategy.get(_p.strategy_instance_id, D("0"))
                _plans_sum_by_strategy[_p.strategy_instance_id] = (
                    prev + D(str(_p.planned_capital or 0))
                )
        for _si, _st in _active_rows:
            # 1순위: stage_plans 합 (= 사장님 본인 데이터, 영구)
            _capital = _plans_sum_by_strategy.get(_si.id, D("0"))
            if _capital <= 0:
                # 2순위: template.stages_config.capitals 합
                if _st.stages_config and isinstance(_st.stages_config, dict):
                    _capitals = _st.stages_config.get("capitals") or []
                    for _c in _capitals:
                        if _c is None:
                            continue
                        try:
                            _capital += D(str(_c))
                        except Exception:
                            continue
            if _capital <= 0:
                # 3순위: total_capital (= legacy)
                _capital = D(str(_st.total_capital or 0))
            # 🌟 마진 단위 변환 (= 사장님 사상: wallet 와 같은 단위)
            _lev = D(str(_st.leverage or _si.leverage or 1))
            _margin = _capital / _lev if _lev > 0 else _capital
            existing_margin_reserved += _margin
        existing_capital_reserved = existing_margin_reserved.quantize(D("0.01"))
        total_wallet = D(str(
            acct.get("totalWalletBalance")
            or acct.get("totalMarginBalance", "0")
        ))
        # 🌟 2026-06-09 사장님 사상 정확: 신 strategy 자본 = 마진 단위로 변환
        new_capital_notional = D(str(template_model.total_capital or 0))
        new_margin = (new_capital_notional / D(str(effective_lev or 1))).quantize(D("0.01"))
        projected_capital_total = (existing_capital_reserved + new_margin).quantize(D("0.01"))
        # 🌟 2026-06-09 v17 Phase 3: 단일 진실 모듈 사용 (= 사장님 헌법 6번)
        from app.services.capital_calculator import calc_wallet_limit
        wallet_limit_130 = calc_wallet_limit(total_wallet).quantize(D("0.01"))
        if total_wallet > 0 and projected_capital_total > wallet_limit_130:
            raise ValueError(
                f"💰 마진 예약 130% 초과 — 사장님 안전 사상.\n\n"
                f"📌 계산 (마진 = 사장님 자금 = 자본 / 레버리지):\n"
                f"  • 기존 활성 전략 {len(_active_rows)}개 마진 합 = {existing_capital_reserved:.2f} USDT\n"
                f"  • + 신규 전략 마진 = {new_margin:.2f} USDT (자본 {new_capital_notional:.2f} / {effective_lev}x)\n"
                f"  • = 총 마진 {projected_capital_total:.2f} USDT  >  130% 한도 {wallet_limit_130:.2f} USDT\n"
                f"     (지갑 잔액 {total_wallet:.2f} × 1.30 = 130% 마진 한도)\n\n"
                f"📖 의미: 사장님 신 정책 (2026-06-09):\n"
                f"  • 전체 마진 합 ≤ wallet × 130% = 신 전략 세팅 가능\n"
                f"  • 부족한 30% = 모든 strategy 진입 완료 시 = 「💉 포지션 추가」/증거금 자동 차단\n"
                f"  • = 사장님 자율 + 신축적 운영 (= 옛 100% 보다 30% 더 자유)\n\n"
                "💡 해결 (택1):\n"
                "  • 활성 전략 일부 정리 (포지션 청산) — 예약 마진 회수\n"
                "  • 거래소 USDT 입금\n"
                "  • 신규 전략의 단계별 자본 축소 (전체 합이 가용 잔액 이내)"
            )

        # 1) 가용 잔액 체크 (entry 마진 + 추가 증거금 합)
        if required_margin_total > available:
            raise ValueError(
                f"💰 잔액 부족 — 필요한 마진 {required_margin_total:.2f} USDT > 가용 잔액 {available:.2f} USDT\n\n"
                f"📌 계산: 자본 {template_model.total_capital} USDT ÷ 레버리지 {effective_lev}x = entry 마진 {required_margin:.2f}\n"
                f"        + 단계별 추가 증거금 합 {additional_margin_sum:.2f} USDT\n"
                f"        = 총 필요 마진 {required_margin_total:.2f}\n\n"
                "💡 해결 (택1):\n"
                "  • Binance 거래소에 USDT 추가 입금\n"
                "  • 자본 또는 단계별 추가 증거금을 줄여 다시 시도\n"
                "  • 레버리지를 높여 entry 마진 감소 (단, 청산 위험 ↑)"
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
                    f"⚠️ 청산가가 너무 가까워 위험합니다.\n\n"
                    f"📌 레버리지 {effective_lev_check}x 일 때 진입가에서 약 {distance_pct_est}% 만 움직여도 강제 청산. "
                    f"운영 정책상 최소 {min_liq_dist}% 이상 거리가 필요합니다.\n\n"
                    "💡 해결: 「레버리지」 를 낮춰주세요. (예: 5x → 거리 ≈ 19.9%, 10x → ≈ 9.95%)"
                )

        # 1-A) 단일 strategy 자본 상한 % — 사용자 요청으로 정책 비활성 (2026-05-10).
        # 이전엔 settings.max_strategy_capital_pct_of_balance 가 set 되면 잔액의 N%
        # 초과 시 거부 (mainnet 안전 가드). 사용자 의사결정으로 100% 까지 허용:
        # max_pct >= 100 일 때만 검증. 그 외 (None / 0 / 음수 / 100 미만) 모두 통과.
        # 즉 .env 의 어떤 설정이든 자동으로 비활성. 100% 까지 자본 집중 가능.
        max_pct = _settings.max_strategy_capital_pct_of_balance
        if max_pct and max_pct >= 100 and available > 0:
            cap_limit = (available * D(str(max_pct)) / D("100")).quantize(D("0.01"))
            tpl_cap = D(str(template_model.total_capital))
            if tpl_cap > cap_limit:
                raise ValueError(
                    f"💰 한 전략의 자본이 가용 잔액 ({available:.2f} USDT) 을 초과합니다 — {tpl_cap:.2f} USDT.\n\n"
                    "💡 해결: 자본을 가용 잔액 이내로 줄이거나 거래소 입금하세요."
                )

        # 2) 마진 비율 한도 (현재 + 새 전략 후 예상)
        if total_margin > 0:
            current_ratio_pct = (total_maint / total_margin * 100).quantize(D("0.01"))
            # 청산 위험 차단: 현재 비율이 이미 80% 넘으면 신규 진입 거부
            MAX_MARGIN_RATIO_PCT = D("80")
            if current_ratio_pct > MAX_MARGIN_RATIO_PCT:
                raise ValueError(
                    f"⚠️ 거래소 마진 사용율이 {current_ratio_pct}% 로 청산 위험 영역 ({MAX_MARGIN_RATIO_PCT}% 한도) 입니다.\n\n"
                    "📌 이미 보유한 포지션이 청산가에 가까워 신규 진입을 차단했습니다.\n\n"
                    "💡 해결 (택1):\n"
                    "  • Binance 에서 일부 포지션 정리\n"
                    "  • USDT 추가 입금으로 마진 여유 확보"
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
        plans = [StrategyStagePlan(
            strategy_instance_id=instance.id,
            stage_no=s.stage_no,
            side=side,
            trigger_mode=s.trigger_mode,
            trigger_percent=s.trigger_percent,
            trigger_price=s.trigger_price,
            planned_capital=s.planned_capital,
            planned_qty=s.planned_qty,
            # 2026-05-11 (사용자 요청): 단계별 추가 증거금 — preview 에서 전달받음
            additional_margin_usdt=s.additional_margin_usdt,
        ) for s in preview.stages]
        self.repo.create_stage_plans(plans)
        self.db.commit()
        self.db.refresh(instance)
        return instance
