import logging
from decimal import Decimal
from uuid import uuid4
from app.core.redis_client import get_redis_client
from app.core.redis_lock import redis_lock, RedisLockError
from app.integrations.binance.client import BinanceClient
from app.integrations.binance.futures_trade import BinanceFuturesTradeClient
from app.integrations.binance.execution.router import ExecutionAdapterRouter
from app.integrations.binance.execution.plain_order_adapter import PlainOrderAdapter
from app.models.order import Order
from app.models.risk_event import RiskEvent
from app.repositories.order_repository import OrderRepository
from app.repositories.strategy_repository import StrategyRepository
from app.services.account_kill_switch_service import AccountKillSwitchService
from app.core.sentry import capture_strategy_event

logger = logging.getLogger(__name__)


class EmergencyCloseInProgress(Exception):
    """다른 caller 가 같은 strategy 의 emergency_close 를 처리 중 — 중복 발사 방지."""
    pass

class ExecutionService:
    def __init__(self, db, *, api_key: str, api_secret: str, is_testnet: bool = False) -> None:
        self.db = db
        self.strategy_repo = StrategyRepository(db)
        self.order_repo = OrderRepository(db)
        self.client = BinanceClient(api_key=api_key, api_secret=api_secret, is_testnet=is_testnet)
        self.trade_client = BinanceFuturesTradeClient(self.client)
        self.execution_router = ExecutionAdapterRouter(plain_adapter=PlainOrderAdapter(self.client), algo_adapter=None)

    def apply_leverage(self, strategy):
        return self.client.change_leverage(symbol=strategy.symbol, leverage=strategy.leverage)

    def ensure_isolated_margin(self, strategy) -> None:
        """심볼의 마진 모드를 ISOLATED 로 강제 설정 (사용자 결정 2026-05-06).

        모든 신규 strategy 가 ISOLATED 로 진입해야 「💰 증거금 추가」 사용 가능.
        Binance 정책: 빈 포지션일 때만 변경 가능. 포지션 보유 중 호출 시 -4048 거부.
        이미 ISOLATED 면 -4046 ("No need to change margin type") 응답 — 무시 (idempotent).

        호출 위치: 진입 직전 (start_stage1 / enter_stage_at_market / add_position_now).
        실패 시: warning 로그만 (본 진입 흐름은 진행). CROSS 로 진입되더라도 거래는
        가능하지만 「증거금 추가」 만 못 함.
        """
        try:
            self.client.change_margin_type(symbol=strategy.symbol, margin_type="ISOLATED")
            logger.info("ensure_isolated_margin OK strategy=%s symbol=%s", strategy.id, strategy.symbol)
        except Exception as e:
            err_msg = str(e)
            # -4046: 이미 같은 마진 모드 (idempotent OK)
            if "-4046" in err_msg or "no need" in err_msg.lower():
                logger.info("ensure_isolated_margin already ISOLATED (idempotent) strategy=%s symbol=%s",
                            strategy.id, strategy.symbol)
                return
            # -4048: 포지션 보유 중 변경 불가 — warning 만 (강제 진행)
            # 다른 에러 — warning 만 (본 진입 흐름 막지 않음)
            logger.warning(
                "ensure_isolated_margin failed (continuing anyway): strategy=%s symbol=%s error=%s",
                strategy.id, strategy.symbol, e,
            )

    def start_stage1(self, strategy_id: int) -> Order:
        strategy = self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            raise ValueError("Strategy not found")
        if AccountKillSwitchService(self.db).is_enabled(strategy.exchange_account_id):
            raise ValueError("Account kill-switch is enabled; new orders are blocked")
        stage_plan = next((p for p in strategy.stage_plans if p.stage_no == 1), None)
        if not stage_plan:
            raise ValueError("Stage 1 plan not found")
        self.ensure_isolated_margin(strategy)  # 2026-05-06 (사용자 결정): 모든 거래 ISOLATED
        self.apply_leverage(strategy)
        order = self._place_stage_entry_order(strategy, stage_plan)
        strategy.status = "STAGE1_OPEN_PENDING"
        strategy.current_stage = 1
        self.db.commit()
        self.db.refresh(order)
        # 2026-05-11 (사용자 요청): 단계 1 진입 시 추가 증거금 자동 투입 (옵션).
        # additional_margin_usdt > 0 이면 add_position_margin 호출. 실패해도 entry 자체는
        # 정상 진행 — 사용자에게 RiskEvent + Telegram 알림. 호출자(API) 가 그 처리.
        add_m = stage_plan.additional_margin_usdt
        if add_m and Decimal(str(add_m)) > 0:
            try:
                self.add_position_margin(strategy_id, amount=Decimal(str(add_m)))
                logger.info(
                    "start_stage1: additional margin +%s USDT applied to strategy=%s symbol=%s",
                    add_m, strategy_id, strategy.symbol,
                )
            except Exception as e:
                logger.warning(
                    "start_stage1: additional margin failed strategy=%s: %s (entry already placed)",
                    strategy_id, e,
                )
                # entry 는 정상이라 raise 안 함 — 별도 RiskEvent 만 기록
                self.db.add(RiskEvent(
                    strategy_instance_id=strategy_id,
                    event_type="STAGE_ADDITIONAL_MARGIN_FAILED",
                    severity="WARN",
                    title="⚠️ 단계 1 추가 증거금 투입 실패 (entry 는 정상)",
                    message=f"단계 1 entry 정상 발사. 추가 증거금 {add_m} USDT 투입 실패: {e}. 수동 처리 필요.",
                    event_payload={"strategy_id": strategy_id, "stage_no": 1, "amount": str(add_m), "error": str(e)},
                ))
                self.db.commit()
        return order

    def trigger_next_stage(self, strategy_id: int, stage_no: int) -> Order:
        strategy = self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            raise ValueError("Strategy not found")
        # 2026-05-04 fix: kill-switch 가 stage 1 (start_stage1) 에만 체크되던 버그.
        # stage 2~10 자동 진입은 신규 거래임에도 차단 안 돼 kill-switch 안전장치 부분 무력.
        # 이제는 모든 stage 진입에서 차단.
        if AccountKillSwitchService(self.db).is_enabled(strategy.exchange_account_id):
            raise ValueError(
                f"Account kill-switch is enabled; stage {stage_no} entry blocked. "
                "Kill-switch 를 해제한 후 재시도하세요."
            )
        stage_plan = next((p for p in strategy.stage_plans if p.stage_no == stage_no), None)
        if not stage_plan:
            raise ValueError(f"Stage {stage_no} plan not found")
        order = self._place_stage_entry_order(strategy, stage_plan)
        strategy.current_stage = stage_no
        # 2026-05-04 fix: 옵션 C 1~10단계 동적 — 이전엔 2/3/4 만 dict 있어 5+ stage 진입 시
        # status 변경 안 됨. f-string 으로 N단계 모두 STAGE{N}_OPEN_PENDING 처리.
        if 2 <= stage_no <= 10:
            strategy.status = f"STAGE{stage_no}_OPEN_PENDING"
        self.db.commit()
        self.db.refresh(order)
        return order

    def emergency_close_position(self, strategy_id: int, *, quantity: Decimal) -> Order:
        # 2026-05-08 (사용자 #120 DYDXUSDT orphan 사례): emergency_close_position 이
        # 같은 strategy 에 대해 동시 다발 호출되면 (manual stop API + tp_sl_orchestrator
        # + admin cleanup 등) 같은 양 (예: 245 DYDX) 이 여러 번 청산되어 거래소-DB
        # 불일치 → orphan → KS 발동. caller 측 락이 다 따로라 함수 자체에 idempotency
        # 락 추가. TTL 5s — 중복 차단엔 충분, 정상 retry 는 통과 가능.
        redis_client = get_redis_client()
        lock_key = f"lock:strategy:{strategy_id}:emergency_close"
        try:
            with redis_lock(redis_client, lock_key, ttl_seconds=5, wait_timeout_seconds=0):
                return self._emergency_close_position_locked(strategy_id, quantity=quantity)
        except RedisLockError:
            logger.warning(
                "emergency_close_position skipped — duplicate call within 5s window: strategy_id=%s qty=%s",
                strategy_id, quantity,
            )
            raise EmergencyCloseInProgress(
                f"strategy_id={strategy_id} 의 청산이 이미 진행 중 — 중복 호출 차단"
            )

    def _emergency_close_position_locked(self, strategy_id: int, *, quantity: Decimal) -> Order:
        strategy = self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            raise ValueError("Strategy not found")
        # Bug #8 fix (2026-04-29): 포지션이 0 인 전략에 대한 reduceOnly 주문은
        # Binance 가 -2022 "ReduceOnly Order is rejected" 로 거절.
        # Bug #8 강화 (2026-04-29 PM): DB 의 quantity 가 stale 일 수 있어 (예: REENTRY_READY
        # 상태인데 current_position_qty 가 옛값) 진짜 거래소 포지션을 먼저 확인.
        # 거래소가 0 이면 미체결 주문만 취소하고 STOPPED 마킹.
        try:
            position_risk = self.client.get_position_risk(symbol=strategy.symbol)
            if isinstance(position_risk, dict):
                position_risk = [position_risk]
            actual_position = Decimal("0")
            for item in position_risk:
                if item.get("symbol") == strategy.symbol and item.get("positionSide") == strategy.side:
                    actual_position = abs(Decimal(str(item.get("positionAmt", "0"))))
                    break
        except Exception:
            actual_position = abs(Decimal(str(quantity))) if quantity else Decimal("0")
        if actual_position == 0:
            # 거래소에 포지션 없음 — 미체결 주문 취소만 + STOPPED
            try:
                self.client.cancel_all_orders(symbol=strategy.symbol)
            except Exception:
                pass
            strategy.status = "STOPPED"
            strategy.current_position_qty = Decimal("0")
            self.db.commit()
            raise ValueError(
                f"Exchange has no {strategy.side} position for {strategy.symbol}; "
                "cancelled pending orders and marked STOPPED. No reduceOnly market order sent."
            )
        # 거래소 실 포지션과 비교하여 cap 만 함 (요청 qty 가 더 크면 거래소 값으로 줄임).
        # 이전 버전은 무조건 quantity = actual_position 으로 덮어쓰는 critical bug:
        # 부분 TP1 요청 (25% = 199) 도 거래소 풀 포지션 (798) 으로 닫혀버림.
        # 부분 TP/SL 정상 동작을 위해 over-close 만 방지하는 cap 으로 변경.
        try:
            req_qty = abs(Decimal(str(quantity))) if quantity else Decimal("0")
        except Exception:
            req_qty = Decimal("0")
        if req_qty <= 0 or req_qty > actual_position:
            quantity = actual_position  # 요청 없거나 실 포지션 초과 시 풀 청산
        else:
            quantity = req_qty  # 부분 청산 정상 진행 (TP1 25% 등)
        side = "SELL" if strategy.side == "LONG" else "BUY"
        position_side = strategy.side
        client_order_id = self._new_client_order_id(strategy.symbol, "EXIT")
        # Bug fix (2026-05-02 evening, #79 race condition 사례):
        # 이전 흐름:
        #   1) place_market_order → 즉시 체결 + Binance stream EXIT FILLED 이벤트 발송
        #   2) Order DB 추가
        #   3) strategy.status = STOPPING
        #   4) commit
        # user-stream worker 가 1)의 stream event 를 받았을 때 우리 transaction 이
        # 4)의 commit 전이라 다른 session 에서는 옛 status (예: TP3_DONE_PARTIAL) 를 봄
        # → stream_service 의 STOPPING 분기 못 타고 else (REENTRY_READY) 로 잘못 빠짐.
        # 새 흐름: status 변경을 먼저 commit 해서 외부 worker 에게 노출한 뒤 거래소 호출.
        # 단, _execute_take_profit 에서 호출되는 경우 status 가 이미 TP/COMPLETED 로 갔으므로
        # 무조건 STOPPING 으로 덮어쓰지 않게 — current status 가 STAGE_X_OPEN 류일 때만.
        # 2026-05-06: TP1~10_DONE_PARTIAL 모두 보호 (10단계 익절 확장).
        _TP_PARTIAL_SET = {f"TP{n}_DONE_PARTIAL" for n in range(1, 11)}
        if strategy.status not in ({"COMPLETED", "REENTRY_READY", "STOPPED"} | _TP_PARTIAL_SET):
            strategy.status = "STOPPING"
        self.db.commit()
        # A03 fix (audit 2026-05-02): 거래소 호출 실패 시 명시적 로깅 + RiskEvent 기록.
        try:
            response = self.trade_client.place_market_order(symbol=strategy.symbol, side=side, position_side=position_side, quantity=quantity, new_client_order_id=client_order_id)
        except Exception as e:
            logger.error(
                "emergency_close place_market_order failed: strategy_id=%s symbol=%s qty=%s side=%s error=%s",
                strategy.id, strategy.symbol, quantity, side, e,
            )
            self.db.add(RiskEvent(
                strategy_instance_id=strategy.id,
                event_type="EMERGENCY_CLOSE_PLACE_FAILED",
                severity="ERROR",
                title="Emergency close 시장가 주문 발송 실패",
                message=f"symbol={strategy.symbol} qty={quantity} side={side} error={e}",
                event_payload={"strategy_id": strategy.id, "quantity": str(quantity), "side": side, "error": str(e)},
            ))
            self.db.commit()
            capture_strategy_event(
                "emergency_close place_market_order failed",
                level="error",
                strategy_id=strategy.id, symbol=strategy.symbol, side=strategy.side,
                account_id=strategy.exchange_account_id, error=e,
                extras={"quantity": str(quantity), "exit_side": side},
                tags={"event_type": "EMERGENCY_CLOSE_PLACE_FAILED"},
            )
            raise
        order = Order(strategy_instance_id=strategy.id, stage_no=None, purpose="EXIT", symbol=strategy.symbol, side=side, position_side=position_side, order_type="MARKET", time_in_force=None, client_order_id=client_order_id, exchange_order_id=response.get("orderId"), trigger_price=None, price=Decimal(str(response.get("avgPrice"))) if response.get("avgPrice") else None, orig_qty=quantity, executed_qty=Decimal(str(response.get("executedQty", "0"))), avg_price=Decimal(str(response.get("avgPrice"))) if response.get("avgPrice") else None, status=response.get("status", "NEW"), raw_request={"symbol": strategy.symbol, "side": side, "positionSide": position_side, "type": "MARKET", "quantity": str(quantity), "newClientOrderId": client_order_id}, raw_response=response)
        self.order_repo.create(order)
        self.db.commit()
        return order

    def cancel_exchange_order(self, *, symbol: str, order_id: int | None = None, orig_client_order_id: str | None = None) -> dict:
        return self.client.cancel_order(symbol=symbol, order_id=order_id, orig_client_order_id=orig_client_order_id)

    def add_position_margin(self, strategy_id: int, *, amount: Decimal) -> dict:
        """ISOLATED 모드 포지션에 증거금 추가.

        검증:
        - strategy 존재 + 포지션 보유 (qty != 0)
        - amount > 0
        - 거래소 호출 실패 시 명확한 에러 메시지 (CROSS 모드면 -4046 에러)

        성공 시 RiskEvent + Telegram 알림 발송.
        """
        if amount is None or amount <= 0:
            raise ValueError(f"증거금 추가 금액은 양수여야 합니다 (입력: {amount})")
        strategy = self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            raise ValueError("Strategy not found")
        current_qty = abs(Decimal(str(strategy.current_position_qty or 0)))
        if current_qty == 0:
            raise ValueError(
                f"포지션 없음 (qty=0) — 증거금 추가 불가. "
                f"strategy={strategy.id} status={strategy.status}"
            )
        try:
            response = self.client.add_position_margin(
                symbol=strategy.symbol,
                position_side=strategy.side,  # hedge mode: LONG/SHORT
                amount=str(amount.quantize(Decimal("0.00000001"))),
                margin_type=1,  # 1 = add
            )
        except Exception as e:
            err_msg = str(e)
            # 흔한 에러 친절 매핑
            # 2026-05-06 사용자 보고 fix: -4096 도 동일 의미 매핑.
            # -4046: "No need to change margin type" (이미 같은 모드)
            # -4096: "Add margin only support for isolated position" (CROSS 거부 — 가장 일반적)
            # "isolated" / "marginType" / "CROSS" 키워드 fallback.
            if (
                "-4046" in err_msg or "-4096" in err_msg
                or "marginType" in err_msg.lower() or "CROSS" in err_msg.upper()
                or "isolated" in err_msg.lower()
            ):
                hint = (
                    " (CROSS 모드 포지션은 증거금 직접 추가 불가. "
                    "→ Binance UI 에서 해당 심볼을 ISOLATED 모드로 변경하거나, "
                    "현재 포지션을 종료 후 신규 strategy 시작 시 ISOLATED 로 진입하세요. "
                    "포지션 보유 중엔 마진 모드 변경 불가)"
                )
            elif "-2027" in err_msg or "margin balance" in err_msg.lower():
                hint = " (지갑 잔액 부족 — Binance 계정에 USDT 입금 필요)"
            else:
                hint = ""
            logger.error(
                "add_position_margin failed: strategy=%s symbol=%s amount=%s error=%s",
                strategy.id, strategy.symbol, amount, e,
            )
            self.db.add(RiskEvent(
                strategy_instance_id=strategy.id,
                event_type="ADD_MARGIN_FAILED",
                severity="ERROR",
                title="🛡 증거금 추가 실패",
                message=f"symbol={strategy.symbol} amount={amount} error={e}{hint}",
                event_payload={"amount": str(amount), "error": str(e)},
            ))
            self.db.commit()
            capture_strategy_event(
                "add_position_margin failed",
                level="error",
                strategy_id=strategy.id, symbol=strategy.symbol, side=strategy.side,
                account_id=strategy.exchange_account_id, error=e,
                extras={"amount": str(amount)},
                tags={"event_type": "ADD_MARGIN_FAILED"},
            )
            raise ValueError(f"증거금 추가 실패: {e}{hint}") from e

        # 성공 — RiskEvent + Telegram 알림
        self.db.add(RiskEvent(
            strategy_instance_id=strategy.id,
            event_type="ADD_MARGIN_SUCCESS",
            severity="INFO",
            title="🛡 증거금 추가 완료",
            message=(
                f"{strategy.symbol} {strategy.side} 포지션에 {amount} USDT 추가 — "
                f"청산가 완화 효과."
            ),
            event_payload={
                "amount": str(amount),
                "exchange_response": response,
            },
        ))
        self.db.commit()
        # Telegram (실패해도 거래 흐름 영향 없음)
        try:
            from app.services.notification_service import NotificationService
            NotificationService(self.db).send_margin_added_alert(
                strategy_instance_id=strategy.id,
                symbol=strategy.symbol,
                side=strategy.side,
                amount=amount,
            )
        except Exception:
            pass
        return response

    def _place_stage_entry_order(self, strategy, stage_plan) -> Order:
        if stage_plan.planned_qty is None or stage_plan.trigger_price is None:
            raise ValueError(f"Stage {stage_plan.stage_no} planned_qty/trigger_price is missing")
        side = "BUY" if strategy.side == "LONG" else "SELL"
        position_side = strategy.side
        client_order_id = self._new_client_order_id(strategy.symbol, f"ENTRY{stage_plan.stage_no}")
        payload = {"symbol": strategy.symbol, "side": side, "positionSide": position_side, "type": "LIMIT", "quantity": str(stage_plan.planned_qty), "price": str(stage_plan.trigger_price), "timeInForce": "GTC", "newClientOrderId": client_order_id}
        adapter = self.execution_router.route_for_type(payload["type"])
        response = adapter.place_order(payload)
        order = Order(strategy_instance_id=strategy.id, stage_no=stage_plan.stage_no, purpose="ENTRY", symbol=strategy.symbol, side=side, position_side=position_side, order_type="LIMIT", time_in_force="GTC", client_order_id=client_order_id, exchange_order_id=response.get("orderId"), trigger_price=stage_plan.trigger_price, price=stage_plan.trigger_price, orig_qty=stage_plan.planned_qty, executed_qty=Decimal(str(response.get("executedQty", "0"))), avg_price=Decimal(str(response.get("avgPrice"))) if response.get("avgPrice") else None, status=response.get("status", "NEW"), raw_request=payload, raw_response=response)
        self.order_repo.create(order)
        return order

    # 2026-05-04 (사용자 요청): 수동 「▶ 다음 단계」 = 시장가 즉시 진입.
    # 기존 trigger_next_stage 는 LIMIT @ trigger_price 라서 자동 워커와 동일 — 수동의 의미 없음.
    # 새 메서드: 현재가에 MARKET 주문 + planned_capital 기준 수량 재계산 + stage_plan.is_triggered=True.
    def enter_stage_at_market(self, strategy_id: int, stage_no: int) -> Order:
        """수동 ▶: 트리거 비율 무시, planned_capital 로 현재가 시장가 즉시 진입.

        검증/효과:
        - kill-switch 차단 (trigger_next_stage 동일)
        - stage_plan 존재 + is_triggered=False
        - 거래소 ticker 에서 현재가 조회 → qty = planned_capital × leverage / current_price (step_size 절사)
        - MARKET 주문 (price 필드 없음, GTC 무관)
        - stage_plan.is_triggered = True (trigger_price 무시 표시)
        - strategy.current_stage = stage_no, status = STAGE{n}_OPEN_PENDING
        """
        strategy = self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            raise ValueError("Strategy not found")
        if AccountKillSwitchService(self.db).is_enabled(strategy.exchange_account_id):
            raise ValueError(
                f"Account kill-switch is enabled; stage {stage_no} entry blocked. "
                "Kill-switch 를 해제한 후 재시도하세요."
            )
        stage_plan = next((p for p in strategy.stage_plans if p.stage_no == stage_no), None)
        if not stage_plan:
            raise ValueError(f"Stage {stage_no} plan not found")
        if stage_plan.planned_capital is None:
            raise ValueError(f"Stage {stage_no} planned_capital is missing")
        # 2026-05-06 (사용자 결정): 모든 거래 ISOLATED. 빈 포지션이면 변경, 보유 중이면 noop.
        self.ensure_isolated_margin(strategy)
        # 현재가 조회 + 수량 계산
        current_price = self._fetch_current_mark_price(strategy.symbol)
        leverage = Decimal(str(strategy.leverage or 1))
        capital = Decimal(str(stage_plan.planned_capital))
        raw_qty = (capital * leverage) / current_price
        qty = self._floor_qty_to_step(strategy.symbol, raw_qty)
        if qty <= 0:
            raise ValueError(
                f"계산된 수량이 0 — capital={capital} USDT, current_price={current_price}, leverage={leverage}x. "
                "더 큰 자본 입력 필요."
            )
        order = self._place_market_entry(
            strategy,
            stage_no=stage_no,
            qty=qty,
            current_price=current_price,
            suffix=f"ENTRY{stage_no}M",  # M = market
        )
        # stage_plan 갱신: trigger 비율 무시 → is_triggered=True 마킹.
        stage_plan.is_triggered = True
        strategy.current_stage = stage_no
        if 2 <= stage_no <= 10:
            strategy.status = f"STAGE{stage_no}_OPEN_PENDING"
        elif stage_no == 1:
            strategy.status = "STAGE1_OPEN_PENDING"
        self.db.commit()
        self.db.refresh(order)
        # 2026-05-12 fix (사용자 #21 SAGAUSDT 4단계 보고): 「수동 ▶ 다음 단계 진입」 에서
        # additional_margin_usdt 자동 투입 코드 누락. start_stage1 + stage_trigger_worker
        # 두 자동 경로엔 있는데 수동만 빠져 사용자가 설정한 증거금이 안 들어감. 동일 패턴 추가.
        # 실패해도 entry 는 정상 (try/except + RiskEvent 기록).
        add_m = stage_plan.additional_margin_usdt
        if add_m and Decimal(str(add_m)) > 0:
            try:
                self.add_position_margin(strategy.id, amount=Decimal(str(add_m)))
                logger.info(
                    f"[manual ▶] additional margin +{add_m} USDT applied to #{strategy.id} stage{stage_no}"
                )
            except Exception as e:
                logger.warning(
                    f"[manual ▶] additional margin failed for #{strategy.id} stage{stage_no}: {e}"
                )
                # entry 자체는 정상 — 사용자에게 알림 (수동 보충 안내).
                try:
                    from app.services.notification_service import NotificationService
                    NotificationService(self.db).send_system_alert(
                        title=f"⚠️ [추가 증거금 실패 — 수동진입] #{strategy.id} {strategy.symbol} 단계{stage_no}",
                        body=(
                            f"수동 ▶ {stage_no}단계 entry 는 정상. 그러나 추가 증거금 {add_m} USDT 투입 실패.\n"
                            f"원인: {e}\n\n"
                            "💡 수동 보충: 「💰 증거금 추가」 버튼 또는 Binance UI 에서 직접 증거금 추가."
                        ),
                    )
                except Exception:
                    pass
        return order

    # 2026-05-04 (사용자 요청): 「💉 포지션 추가」 — ad-hoc 자유 금액 진입.
    # stage_plans 와 무관하게 사용자가 즉시 추가 자본 투입.
    # MARKET (현재가) 또는 LIMIT (지정가) 선택. stream_service 가 평단/qty 자동 갱신.
    def add_position_now(
        self,
        strategy_id: int,
        *,
        amount_usdt: Decimal,
        order_type: str,
        limit_price: Decimal | None = None,
    ) -> Order:
        """사용자 지정 USDT 금액으로 즉시 포지션 추가.

        Args:
            amount_usdt: 추가 자본 (margin, USDT). 양수.
            order_type: "MARKET" 또는 "LIMIT".
            limit_price: order_type=LIMIT 일 때 지정가. MARKET 이면 무시.

        효과:
            - qty = amount_usdt × leverage / price (MARKET 은 현재가, LIMIT 은 지정가)
            - 주문 발송 (MARKET 또는 LIMIT GTC)
            - stage_no=NULL (ad-hoc 표시), purpose='ENTRY'
            - 체결 시 stream_service 가 strategy.current_position_qty/avg_entry_price 자동 갱신
        """
        strategy = self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            raise ValueError("Strategy not found")
        if AccountKillSwitchService(self.db).is_enabled(strategy.exchange_account_id):
            raise ValueError(
                "Account kill-switch is enabled; new position entry blocked. "
                "Kill-switch 를 해제한 후 재시도하세요."
            )
        if amount_usdt is None or Decimal(str(amount_usdt)) <= 0:
            raise ValueError(f"amount_usdt must be > 0, got {amount_usdt}")
        order_type_u = (order_type or "").upper()
        if order_type_u not in ("MARKET", "LIMIT"):
            raise ValueError(f"order_type must be MARKET or LIMIT, got {order_type}")
        # 2026-05-06 (사용자 결정): 모든 거래 ISOLATED. 빈 포지션이면 변경, 보유 중이면 noop.
        self.ensure_isolated_margin(strategy)
        # 가격 결정
        if order_type_u == "LIMIT":
            if limit_price is None or Decimal(str(limit_price)) <= 0:
                raise ValueError("LIMIT 주문에는 limit_price (양수) 가 필요합니다")
            ref_price = Decimal(str(limit_price))
        else:
            ref_price = self._fetch_current_mark_price(strategy.symbol)
        # 수량 계산
        leverage = Decimal(str(strategy.leverage or 1))
        amount = Decimal(str(amount_usdt))
        raw_qty = (amount * leverage) / ref_price
        qty = self._floor_qty_to_step(strategy.symbol, raw_qty)
        if qty <= 0:
            raise ValueError(
                f"계산된 수량이 0 — amount={amount} USDT, price={ref_price}, leverage={leverage}x. "
                "더 큰 자본 입력 필요."
            )
        if order_type_u == "MARKET":
            order = self._place_market_entry(
                strategy,
                stage_no=None,  # ad-hoc — stage_no 없음
                qty=qty,
                current_price=ref_price,
                suffix="ADHOC_M",
            )
        else:
            order = self._place_limit_entry(
                strategy,
                stage_no=None,  # ad-hoc
                qty=qty,
                limit_price=ref_price,
                suffix="ADHOC_L",
            )
        self.db.commit()
        self.db.refresh(order)
        return order

    # ───────── 내부 헬퍼 ─────────
    def _fetch_current_mark_price(self, symbol: str) -> Decimal:
        """거래소에서 현재 mark price 조회 — get_position_risk 의 markPrice 사용 (인증 + 인스턴스용).

        Binance fapi/v1/positionRisk 는 markPrice 를 항상 반환하므로 ticker 별도 호출 불필요.
        포지션이 없어도 markPrice 는 받음.
        """
        try:
            position_risk = self.client.get_position_risk(symbol=symbol)
            if isinstance(position_risk, dict):
                position_risk = [position_risk]
            for item in position_risk:
                if item.get("symbol") == symbol:
                    mark = item.get("markPrice")
                    if mark and Decimal(str(mark)) > 0:
                        return Decimal(str(mark))
            raise ValueError(f"markPrice not found in position_risk response for {symbol}")
        except Exception as e:
            raise ValueError(f"현재가 조회 실패 ({symbol}): {e}") from e

    def _floor_qty_to_step(self, symbol: str, raw_qty: Decimal) -> Decimal:
        """심볼 step_size 로 qty 절사. step_size 못 찾으면 0.001 fallback."""
        from app.models.symbol import Symbol
        from sqlalchemy import select
        sym = self.db.execute(select(Symbol).where(Symbol.symbol == symbol)).scalars().first()
        step = Decimal(str(sym.step_size)) if sym and sym.step_size and Decimal(str(sym.step_size)) > 0 else Decimal("0.001")
        return (raw_qty // step) * step

    def _place_market_entry(self, strategy, *, stage_no: int | None, qty: Decimal, current_price: Decimal, suffix: str) -> Order:
        """공통 MARKET 진입 주문 (stage 또는 ad-hoc)."""
        side = "BUY" if strategy.side == "LONG" else "SELL"
        position_side = strategy.side
        client_order_id = self._new_client_order_id(strategy.symbol, suffix)
        payload = {
            "symbol": strategy.symbol,
            "side": side,
            "positionSide": position_side,
            "type": "MARKET",
            "quantity": str(qty),
            "newClientOrderId": client_order_id,
        }
        adapter = self.execution_router.route_for_type(payload["type"])
        response = adapter.place_order(payload)
        order = Order(
            strategy_instance_id=strategy.id,
            stage_no=stage_no,
            purpose="ENTRY",
            symbol=strategy.symbol,
            side=side,
            position_side=position_side,
            order_type="MARKET",
            time_in_force=None,
            client_order_id=client_order_id,
            exchange_order_id=response.get("orderId"),
            trigger_price=None,
            price=current_price,  # 참고용 (체결가는 avg_price 가 정확)
            orig_qty=qty,
            executed_qty=Decimal(str(response.get("executedQty", "0"))),
            avg_price=Decimal(str(response.get("avgPrice"))) if response.get("avgPrice") else None,
            status=response.get("status", "NEW"),
            raw_request=payload,
            raw_response=response,
        )
        self.order_repo.create(order)
        return order

    def _place_limit_entry(self, strategy, *, stage_no: int | None, qty: Decimal, limit_price: Decimal, suffix: str) -> Order:
        """공통 LIMIT 진입 주문 (ad-hoc 지정가 진입용)."""
        side = "BUY" if strategy.side == "LONG" else "SELL"
        position_side = strategy.side
        client_order_id = self._new_client_order_id(strategy.symbol, suffix)
        payload = {
            "symbol": strategy.symbol,
            "side": side,
            "positionSide": position_side,
            "type": "LIMIT",
            "quantity": str(qty),
            "price": str(limit_price),
            "timeInForce": "GTC",
            "newClientOrderId": client_order_id,
        }
        adapter = self.execution_router.route_for_type(payload["type"])
        response = adapter.place_order(payload)
        order = Order(
            strategy_instance_id=strategy.id,
            stage_no=stage_no,
            purpose="ENTRY",
            symbol=strategy.symbol,
            side=side,
            position_side=position_side,
            order_type="LIMIT",
            time_in_force="GTC",
            client_order_id=client_order_id,
            exchange_order_id=response.get("orderId"),
            trigger_price=limit_price,
            price=limit_price,
            orig_qty=qty,
            executed_qty=Decimal(str(response.get("executedQty", "0"))),
            avg_price=Decimal(str(response.get("avgPrice"))) if response.get("avgPrice") else None,
            status=response.get("status", "NEW"),
            raw_request=payload,
            raw_response=response,
        )
        self.order_repo.create(order)
        return order

    @staticmethod
    def _new_client_order_id(symbol: str, suffix: str) -> str:
        """Binance newClientOrderId 36자 제한 — 항상 35자 이하 보장.

        2026-05-12 fix (사용자 보고 #-4015 에러):
        Binance API: "Client order id length should be less than 36 chars" (strict <).
        이전 포맷 `{symbol}-{suffix}-{uuid18}` 는 symbol_len + suffix_len + 20.
        - 8자 symbol + ENTRY10M (8자) suffix = 36자 → -4015 reject
        - 9자 symbol + ENTRY10M = 37자 → -4015 reject
        Fix: uuid 길이를 가용 공간에 맞게 동적 (선호 18자, 최소 8자 = 32bit).
        symbol/suffix 가 매우 길어 8자도 안 들어가면 전체 35자로 강제 truncate.
        """
        MAX_LEN = 35              # Binance limit < 36 → 최대 35
        PREFERRED_UUID = 18       # 충분한 충돌 방지 (72 bits)
        MIN_UUID = 8              # 최소 충돌 방지 (32 bits — 일 단위 운영 충분)
        base_len = len(symbol) + 1 + len(suffix) + 1  # symbol + "-" + suffix + "-"
        uuid_len = max(MIN_UUID, min(PREFERRED_UUID, MAX_LEN - base_len))
        cid = f"{symbol}-{suffix}-{uuid4().hex[:uuid_len]}"
        return cid[:MAX_LEN]      # 안전장치 — 어떤 입력에도 35자 보장
