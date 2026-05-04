import logging
from decimal import Decimal
from uuid import uuid4
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

    def start_stage1(self, strategy_id: int) -> Order:
        strategy = self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            raise ValueError("Strategy not found")
        if AccountKillSwitchService(self.db).is_enabled(strategy.exchange_account_id):
            raise ValueError("Account kill-switch is enabled; new orders are blocked")
        stage_plan = next((p for p in strategy.stage_plans if p.stage_no == 1), None)
        if not stage_plan:
            raise ValueError("Stage 1 plan not found")
        self.apply_leverage(strategy)
        order = self._place_stage_entry_order(strategy, stage_plan)
        strategy.status = "STAGE1_OPEN_PENDING"
        strategy.current_stage = 1
        self.db.commit()
        self.db.refresh(order)
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
        if strategy.status not in ("COMPLETED", "REENTRY_READY", "STOPPED",
                                    "TP1_DONE_PARTIAL", "TP2_DONE_PARTIAL", "TP3_DONE_PARTIAL",
                                    "TP4_DONE_PARTIAL", "TP5_DONE_PARTIAL"):
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
            if "-4046" in err_msg or "marginType" in err_msg.lower() or "CROSS" in err_msg.upper():
                hint = " (CROSS 모드 포지션은 증거금 직접 추가 불가 — Binance UI 또는 별도 절차로 ISOLATED 변경 필요)"
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

    @staticmethod
    def _new_client_order_id(symbol: str, suffix: str) -> str:
        return f"{symbol}-{suffix}-{uuid4().hex[:18]}"
