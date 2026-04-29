from decimal import Decimal
from uuid import uuid4
from app.integrations.binance.client import BinanceClient
from app.integrations.binance.futures_trade import BinanceFuturesTradeClient
from app.integrations.binance.execution.router import ExecutionAdapterRouter
from app.integrations.binance.execution.plain_order_adapter import PlainOrderAdapter
from app.models.order import Order
from app.repositories.order_repository import OrderRepository
from app.repositories.strategy_repository import StrategyRepository
from app.services.account_kill_switch_service import AccountKillSwitchService

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
        # 거래소에 실제로 포지션이 있으면 그 양으로 청산 (DB 보다 거래소 신뢰)
        quantity = actual_position
        side = "SELL" if strategy.side == "LONG" else "BUY"
        position_side = strategy.side
        client_order_id = self._new_client_order_id(strategy.symbol, "EXIT")
        response = self.trade_client.place_market_order(symbol=strategy.symbol, side=side, position_side=position_side, quantity=quantity, new_client_order_id=client_order_id)
        order = Order(strategy_instance_id=strategy.id, stage_no=None, purpose="EXIT", symbol=strategy.symbol, side=side, position_side=position_side, order_type="MARKET", time_in_force=None, client_order_id=client_order_id, exchange_order_id=response.get("orderId"), trigger_price=None, price=Decimal(str(response.get("avgPrice"))) if response.get("avgPrice") else None, orig_qty=quantity, executed_qty=Decimal(str(response.get("executedQty", "0"))), avg_price=Decimal(str(response.get("avgPrice"))) if response.get("avgPrice") else None, status=response.get("status", "NEW"), raw_request={"symbol": strategy.symbol, "side": side, "positionSide": position_side, "type": "MARKET", "quantity": str(quantity), "newClientOrderId": client_order_id}, raw_response=response)
        self.order_repo.create(order)
        strategy.status = "STOPPING"
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
