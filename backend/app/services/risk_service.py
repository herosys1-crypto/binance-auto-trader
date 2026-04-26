from decimal import Decimal

from app.core.redis_client import get_redis_client
from app.models.risk_event import RiskEvent
from app.observability.metrics import strategy_stop_loss_total
from app.repositories.position_repository import PositionRepository
from app.repositories.strategy_repository import StrategyRepository
from app.services.strategy_calculator import StrategyCalculator, SymbolRule

# 트레일링 익절 임계치
TRAILING_TP_PEAK_THRESHOLD = Decimal("20")  # 피크가 이 % 이상 도달했어야 트레일링 활성화
TRAILING_TP_RETRACE_TRIGGER = Decimal("20")  # 현재 PnL% 가 이 값 이하로 내려오면 발동
PEAK_REDIS_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days

class RiskService:
    def __init__(self, db) -> None:
        self.db = db
        self.strategy_repo = StrategyRepository(db)
        self.position_repo = PositionRepository(db)

    def evaluate_stop_loss(self, strategy_id: int) -> bool:
        strategy = self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            raise ValueError("Strategy not found")
        current_loss_amount = Decimal(str(strategy.realized_pnl)) + Decimal(str(strategy.unrealized_pnl))
        threshold = Decimal(str(strategy.total_capital)) * Decimal("0.50")
        is_stop = current_loss_amount <= (-threshold)
        if is_stop:
            self.db.add(RiskEvent(strategy_instance_id=strategy.id, event_type="STOP_LOSS_TRIGGERED", severity="CRITICAL", title="Stop loss triggered", message=f"current_loss_amount={current_loss_amount}, threshold={-threshold}", event_payload={"current_loss_amount": str(current_loss_amount), "threshold": str(-threshold)}))
            strategy_stop_loss_total.labels(symbol=strategy.symbol, side=strategy.side).inc()
            self.db.flush()
        return is_stop

    def evaluate_take_profit_level(self, strategy_id: int) -> str | None:
        """현재 PnL 기준 다음 익절 액션을 결정한다.

        반환 값:
          - "TP1" : +10% 도달
          - "TP2" : +20% 도달
          - "TP3" : +30% 도달 (남은 전량 청산)
          - "TRAILING_TP" : 피크가 +20% 위로 갔다가 다시 +20% 이하로 내려옴 (남은 전량 청산)
          - None : 아직 익절 조건 미달
        """
        strategy = self.strategy_repo.get_strategy(strategy_id)
        latest_position = self.position_repo.latest_by_strategy(strategy_id)
        if not strategy or not latest_position or latest_position.mark_price is None or strategy.avg_entry_price is None:
            return None
        avg_entry = Decimal(str(strategy.avg_entry_price))
        mark_price = Decimal(str(latest_position.mark_price))
        pnl_ratio = ((mark_price - avg_entry) / avg_entry) * Decimal("100") if strategy.side == "LONG" else ((avg_entry - mark_price) / avg_entry) * Decimal("100")

        # 피크 갱신 (Redis 에 strategy 별 최고 PnL% 저장)
        peak = self._update_peak_pnl(strategy_id, pnl_ratio)

        # 우선순위: TP3 > 트레일링 > TP2 > TP1
        if pnl_ratio >= Decimal("30"):
            return "TP3"
        # 트레일링: 피크가 임계치 이상 도달했고, 현재가 회귀 트리거 이하로 내려옴
        if peak >= TRAILING_TP_PEAK_THRESHOLD and pnl_ratio <= TRAILING_TP_RETRACE_TRIGGER and pnl_ratio < peak:
            # 단, 아직 TP1/TP2 조차 안 한 상황은 신규 진입 직후이므로 트레일링 X
            # → TP2_DONE_PARTIAL 이상 단계에서만 트레일링 발동
            if (strategy.status or "").upper() in {"TP2_DONE_PARTIAL", "TP2_DONE", "TRAILING_ARMED"}:
                return "TRAILING_TP"
        if pnl_ratio >= Decimal("20"):
            return "TP2"
        if pnl_ratio >= Decimal("10"):
            return "TP1"
        return None

    @staticmethod
    def _peak_redis_key(strategy_id: int) -> str:
        return f"strategy:{strategy_id}:peak_pnl_pct"

    def _update_peak_pnl(self, strategy_id: int, current_pnl_pct: Decimal) -> Decimal:
        """Redis 에 strategy 별 PnL% 피크 갱신 후 현재 피크 반환."""
        try:
            client = get_redis_client()
            key = self._peak_redis_key(strategy_id)
            stored = client.get(key)
            stored_dec = Decimal(stored.decode("utf-8") if isinstance(stored, bytes) else stored) if stored else Decimal("-9999")
            if current_pnl_pct > stored_dec:
                client.set(key, str(current_pnl_pct), ex=PEAK_REDIS_TTL_SECONDS)
                return current_pnl_pct
            return stored_dec
        except Exception:  # pragma: no cover - Redis 장애 시에도 익절은 동작해야 함
            return current_pnl_pct

    def reset_peak_pnl(self, strategy_id: int) -> None:
        """전략 종료/재진입 시 피크 리셋."""
        try:
            client = get_redis_client()
            client.delete(self._peak_redis_key(strategy_id))
        except Exception:
            pass

    def compute_short_stage4_trigger_price(self, strategy_id: int, symbol_rule: SymbolRule) -> Decimal:
        strategy = self.strategy_repo.get_strategy(strategy_id)
        if not strategy or strategy.side != "SHORT" or strategy.liquidation_price is None:
            raise ValueError("SHORT strategy or liquidation price missing")
        calculator = StrategyCalculator(symbol_rule)
        return calculator.compute_short_stage4_trigger_from_liquidation(Decimal(str(strategy.liquidation_price)))

    def mark_reentry_ready(self, strategy_id: int) -> None:
        strategy = self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            raise ValueError("Strategy not found")
        strategy.reentry_ready = True
        strategy.status = "REENTRY_READY"
        self.db.add(RiskEvent(strategy_instance_id=strategy.id, event_type="REENTRY_READY", severity="INFO", title="Strategy switched to reentry ready", message="Stop loss completed, waiting for manual restart", event_payload=None))
        self.db.commit()
