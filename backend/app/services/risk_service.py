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
          - "TP1"~"TP5" : 해당 단계 PnL% 도달
          - "TRAILING_TP" : 피크가 +20% 위로 갔다가 다시 +20% 이하로 내려옴
          - None : 아직 익절 조건 미달

        TP1~3 은 template 에 항상 채워져 있고, TP4/5 는 nullable — NULL 이면 미사용.
        평가 우선순위: 가장 높은 % (TP5→TP4→TP3→...) 부터 검사.
        """
        from app.models.strategy_template import StrategyTemplate

        strategy = self.strategy_repo.get_strategy(strategy_id)
        latest_position = self.position_repo.latest_by_strategy(strategy_id)
        if not strategy or not latest_position or latest_position.mark_price is None or strategy.avg_entry_price is None:
            return None
        avg_entry = Decimal(str(strategy.avg_entry_price))
        mark_price = Decimal(str(latest_position.mark_price))
        pnl_ratio = ((mark_price - avg_entry) / avg_entry) * Decimal("100") if strategy.side == "LONG" else ((avg_entry - mark_price) / avg_entry) * Decimal("100")

        # 피크 갱신 (Redis 에 strategy 별 최고 PnL% 저장)
        peak = self._update_peak_pnl(strategy_id, pnl_ratio)

        # 템플릿에서 모든 TP 임계치 가져오기
        tpl = self.db.get(StrategyTemplate, strategy.strategy_template_id)
        tp_levels: list[tuple[str, Decimal]] = []
        for label, attr in [("TP5", "tp5_percent"), ("TP4", "tp4_percent"), ("TP3", "tp3_percent"), ("TP2", "tp2_percent"), ("TP1", "tp1_percent")]:
            val = getattr(tpl, attr, None) if tpl else None
            if val is not None:
                tp_levels.append((label, Decimal(str(val))))

        # 가장 높은 도달 단계 선정 (descending sort 후 첫 번째 도달)
        for label, threshold in tp_levels:
            if pnl_ratio >= threshold:
                return label

        # 트레일링: 피크가 임계치 이상 도달했고, 현재가 회귀 트리거 이하로 내려옴
        if peak >= TRAILING_TP_PEAK_THRESHOLD and pnl_ratio <= TRAILING_TP_RETRACE_TRIGGER and pnl_ratio < peak:
            if (strategy.status or "").upper() in {"TP2_DONE_PARTIAL", "TP2_DONE", "TP3_DONE_PARTIAL", "TP4_DONE_PARTIAL", "TRAILING_ARMED"}:
                return "TRAILING_TP"
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
