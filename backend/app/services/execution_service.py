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
        stage_plan = next((p for p in strategy.stage_plans if p.stage_no == stage_no), None)
        if not stage_plan:
            raise ValueError(f"Stage {stage_no} plan not found")
        order = self._place_stage_entry_order(strategy, stage_plan)
        strategy.current_stage = stage_no
        strategy.status = {2: "STAGE2_OPEN_PENDING", 3: "STAGE3_OPEN_PENDING", 4: "STAGE4_OPEN_PENDING"}.get(stage_no, strategy.status)
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
