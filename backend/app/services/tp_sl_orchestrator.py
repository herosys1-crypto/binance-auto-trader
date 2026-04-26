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
                # 이미 동일 단계 또는 더 높은 단계가 실행됐으면 스킵
                done_levels_progression = ["TP1_DONE_PARTIAL", "TP2_DONE_PARTIAL", "TP3_DONE_PARTIAL", "TP4_DONE_PARTIAL", "COMPLETED"]
                tp_level_index = {"TP1": 0, "TP2": 1, "TP3": 2, "TP4": 3, "TP5": 4}.get(tp_level, -1)
                cur_status = (strategy.status or "").upper()
                cur_index = -1
                for i, lab in enumerate(done_levels_progression):
                    if cur_status == lab:
                        cur_index = i
                        break
                if tp_level == "TRAILING_TP" and strategy.status != "COMPLETED":
                    self._execute_take_profit(strategy, "TRAILING_TP")
                elif tp_level_index >= 0 and tp_level_index > cur_index and strategy.status != "COMPLETED":
                    self._execute_take_profit(strategy, tp_level)
        except RedisLockError:
            return

    def _execute_take_profit(self, strategy, level: str) -> None:
        from app.models.strategy_template import StrategyTemplate

        current_qty = Decimal(str(strategy.current_position_qty))
        tpl = self.db.get(StrategyTemplate, strategy.strategy_template_id)
        # 템플릿의 qty_ratio 우선 사용. 없으면 기본값 폴백.
        ratio_attr = {
            "TP1": "tp1_qty_ratio", "TP2": "tp2_qty_ratio", "TP3": "tp3_qty_ratio",
            "TP4": "tp4_qty_ratio", "TP5": "tp5_qty_ratio",
        }
        default_ratio = {"TP1": Decimal("25"), "TP2": Decimal("50"), "TP3": Decimal("100"), "TP4": Decimal("100"), "TP5": Decimal("100")}
        if level == "TRAILING_TP":
            close_ratio = Decimal("1.00")  # 전량 청산
        else:
            attr = ratio_attr.get(level)
            tpl_val = getattr(tpl, attr, None) if tpl and attr else None
            ratio_pct = Decimal(str(tpl_val)) if tpl_val is not None else default_ratio.get(level, Decimal("100"))
            close_ratio = ratio_pct / Decimal("100")
        close_qty = current_qty if close_ratio >= Decimal("1.00") else (current_qty * close_ratio).quantize(Decimal("0.00000001"))
        if close_qty <= 0:
            return
        self.execution_service.emergency_close_position(strategy.id, quantity=close_qty)
        # 상태 진행
        is_final = (level == "TRAILING_TP" or close_ratio >= Decimal("1.00"))
        if level == "TP1":
            strategy.status = "TP1_DONE_PARTIAL" if not is_final else "COMPLETED"
        elif level == "TP2":
            strategy.status = "TP2_DONE_PARTIAL" if not is_final else "COMPLETED"
        elif level == "TP3":
            strategy.status = "TP3_DONE_PARTIAL" if not is_final else "COMPLETED"
        elif level == "TP4":
            strategy.status = "TP4_DONE_PARTIAL" if not is_final else "COMPLETED"
        elif level == "TP5":
            strategy.status = "COMPLETED"
        else:  # TRAILING_TP
            strategy.status = "COMPLETED"
        if strategy.status == "COMPLETED":
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
