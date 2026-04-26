from decimal import Decimal
from app.core.redis_client import get_redis_client
from app.core.redis_lock import redis_lock, RedisLockError
from app.observability.metrics import strategy_runs_total, strategy_take_profit_total
from app.repositories.strategy_repository import StrategyRepository
from app.services.execution_service import ExecutionService
from app.services.notification_service import NotificationService
from app.services.risk_service import RiskService

class TPSLOrchestratorService:
    def __init__(self, db, *, api_key: str, api_secret: str, is_testnet: bool = False) -> None:
        self.db = db
        self.strategy_repo = StrategyRepository(db)
        self.risk_service = RiskService(db)
        self.notification_service = NotificationService(db)
        self.execution_service = ExecutionService(db, api_key=api_key, api_secret=api_secret, is_testnet=is_testnet)

    def run_for_strategy(self, strategy_id: int) -> None:
        redis_client = get_redis_client()
        try:
            with redis_lock(redis_client, f"lock:strategy:{strategy_id}:tp_sl", ttl_seconds=20, wait_timeout_seconds=0):
                strategy = self.strategy_repo.get_strategy(strategy_id)
                if not strategy or strategy.status in {"WAITING","REENTRY_READY","CLOSED","STOPPING"}:
                    return
                if strategy.current_position_qty is None or Decimal(str(strategy.current_position_qty)) <= 0:
                    return
                strategy_runs_total.labels(side=strategy.side, status=strategy.status).inc()
                if self.risk_service.evaluate_stop_loss(strategy.id):
                    self._execute_stop_loss(strategy)
                    return
                tp_level = self.risk_service.evaluate_take_profit_level(strategy.id)
                if tp_level is None:
                    return
                if tp_level == "TP1" and strategy.status not in {"TP1_DONE_PARTIAL", "TP2_DONE_PARTIAL", "COMPLETED"}:
                    self._execute_take_profit(strategy, "TP1")
                elif tp_level == "TP2" and strategy.status not in {"TP2_DONE_PARTIAL", "COMPLETED"}:
                    self._execute_take_profit(strategy, "TP2")
                elif tp_level == "TP3" and strategy.status != "COMPLETED":
                    self._execute_take_profit(strategy, "TP3")
                elif tp_level == "TRAILING_TP" and strategy.status != "COMPLETED":
                    # 피크 +20% 이상 도달 후 +20% 이하로 회귀 — 남은 전량 청산
                    self._execute_take_profit(strategy, "TRAILING_TP")
        except RedisLockError:
            return

    def _execute_take_profit(self, strategy, level: str) -> None:
        current_qty = Decimal(str(strategy.current_position_qty))
        # TP1/TP2 는 부분 청산, TP3/TRAILING_TP 는 전량 청산
        close_ratio_map = {
            "TP1": Decimal("0.25"),
            "TP2": Decimal("0.50"),
            "TP3": Decimal("1.00"),
            "TRAILING_TP": Decimal("1.00"),
        }
        close_ratio = close_ratio_map[level]
        close_qty = current_qty if close_ratio == Decimal("1.00") else (current_qty * close_ratio).quantize(Decimal("0.00000001"))
        if close_qty <= 0:
            return
        self.execution_service.emergency_close_position(strategy.id, quantity=close_qty)
        if level == "TP1":
            strategy.status = "TP1_DONE_PARTIAL"
        elif level == "TP2":
            strategy.status = "TP2_DONE_PARTIAL"
        elif level == "TP3":
            strategy.status = "COMPLETED"
            strategy.reentry_ready = False
            self.risk_service.reset_peak_pnl(strategy.id)
        else:  # TRAILING_TP
            strategy.status = "COMPLETED"
            strategy.reentry_ready = False
            self.risk_service.reset_peak_pnl(strategy.id)
        self.db.commit()
        strategy_take_profit_total.labels(symbol=strategy.symbol, side=strategy.side, level=level).inc()
        self.notification_service.send_take_profit_alert(strategy_instance_id=strategy.id, symbol=strategy.symbol, side=strategy.side, level=level)

    def _execute_stop_loss(self, strategy) -> None:
        current_qty = Decimal(str(strategy.current_position_qty))
        if current_qty > 0:
            self.execution_service.emergency_close_position(strategy.id, quantity=current_qty)
        strategy.status = "STOPPING"
        self.db.commit()
        self.notification_service.send_stop_loss_alert(strategy_instance_id=strategy.id, symbol=strategy.symbol, side=strategy.side, total_capital=str(strategy.total_capital), current_loss_amount=str(strategy.realized_pnl + strategy.unrealized_pnl))
        self.risk_service.mark_reentry_ready(strategy.id)
