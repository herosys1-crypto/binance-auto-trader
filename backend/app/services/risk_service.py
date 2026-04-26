from datetime import datetime, timezone
from decimal import Decimal

from app.core.redis_client import get_redis_client
from app.models.risk_event import RiskEvent
from app.observability.metrics import strategy_stop_loss_total
from app.repositories.position_repository import PositionRepository
from app.repositories.strategy_repository import StrategyRepository
from app.services.strategy_calculator import StrategyCalculator, SymbolRule

# 트레일링 익절 임계치 (정상 모드)
TRAILING_TP_PEAK_THRESHOLD = Decimal("20")  # 피크가 이 % 이상 도달했어야 트레일링 활성화
TRAILING_TP_RETRACE_TRIGGER = Decimal("20")  # 현재 PnL% 가 이 값 이하로 내려오면 발동
PEAK_REDIS_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days

# 크라이시스 복구 모드 임계치
CRISIS_MIN_STAGE = 5                # 5단계 이상 진입
CRISIS_MAX_LOSS_THRESHOLD = Decimal("-30")  # 누적 최대 손실 -30% 이하 도달
CRISIS_TP1_THRESHOLD = Decimal("5")         # 크라이시스 모드 첫 TP +5%
CRISIS_TRAILING_DROP = Decimal("5")         # 첫 TP 후 피크 -5% 회귀 시 전량 청산
CRISIS_HARD_SL_THRESHOLD = Decimal("-1")    # 첫 TP 후 PnL -1% 이하 시 전량 손절

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

        # ─────────── PnL 추적 + 크라이시스 모드 검사 (Phase D-1) ───────────
        self._update_pnl_extremes(strategy, pnl_ratio)
        if not strategy.crisis_mode_triggered_at and self._should_trigger_crisis_mode(strategy):
            self._enter_crisis_mode(strategy)

        # ─────────── 크라이시스 모드 활성 시 별도 평가 (Phase D-2) ───────────
        if strategy.crisis_mode_triggered_at:
            crisis_action = self._eval_crisis_mode_tp_sl(strategy, pnl_ratio)
            if crisis_action is not None:
                return crisis_action
            # 크라이시스 액션 없어도 정상 모드의 TP2~5 룰은 평가 가능 (기존 코드로 폴스루)

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

    # ─────────── 크라이시스 복구 모드 + PnL 추적 (Phase D-1) ───────────

    def _update_pnl_extremes(self, strategy, pnl_ratio: Decimal) -> None:
        """매 PnL 평가 시 max_loss/max_profit 갱신. DB commit 은 호출자 또는 다음 commit 시점."""
        if strategy.max_loss_pct is None or pnl_ratio < Decimal(str(strategy.max_loss_pct)):
            strategy.max_loss_pct = pnl_ratio
        if strategy.max_profit_pct is None or pnl_ratio > Decimal(str(strategy.max_profit_pct)):
            strategy.max_profit_pct = pnl_ratio

    def _should_trigger_crisis_mode(self, strategy) -> bool:
        """크라이시스 모드 진입 조건 — (5+ 단계 OR 마지막 단계) AND 누적 최대 손실 ≤ -30%."""
        if strategy.crisis_mode_triggered_at:  # 이미 진입했으면 재트리거 안 함
            return False
        if strategy.max_loss_pct is None:
            return False
        max_loss = Decimal(str(strategy.max_loss_pct))
        if max_loss > CRISIS_MAX_LOSS_THRESHOLD:  # -30% 미만 손실 (즉 -25% 같은 경우)
            return False
        # 5단계 이상 진입했거나 마지막 단계 진입 (단, total_stages 정보가 없으면 5단계 룰만 사용)
        if strategy.current_stage >= CRISIS_MIN_STAGE:
            return True
        # TODO: total_stages 비교 — 템플릿의 stages_config["capitals"] 길이와 비교 가능. 현재는 5단계 룰만.
        return False

    def _enter_crisis_mode(self, strategy) -> None:
        """크라이시스 모드 진입 — 시각 기록 + RiskEvent 생성 + Telegram 알림."""
        strategy.crisis_mode_triggered_at = datetime.now(timezone.utc)
        self.db.add(RiskEvent(
            strategy_instance_id=strategy.id,
            event_type="CRISIS_MODE_TRIGGERED",
            severity="WARNING",
            title="🚨 크라이시스 복구 모드 진입",
            message=f"5+ 단계 진입 + 누적 최대 손실 {strategy.max_loss_pct}% 도달. TP1 임계가 +5% 로 변경됩니다.",
            event_payload={
                "current_stage": strategy.current_stage,
                "max_loss_pct": str(strategy.max_loss_pct),
                "max_profit_pct": str(strategy.max_profit_pct),
            },
        ))
        self.db.flush()
        # Telegram 알림 — 별도 import 로 순환 회피
        try:
            from app.services.notification_service import NotificationService
            NotificationService(self.db).send_crisis_mode_entered(
                strategy_instance_id=strategy.id,
                symbol=strategy.symbol,
                side=strategy.side,
                current_stage=strategy.current_stage,
                max_loss_pct=str(strategy.max_loss_pct),
            )
        except Exception:  # pragma: no cover
            pass

    def _eval_crisis_mode_tp_sl(self, strategy, pnl_ratio: Decimal) -> str | None:
        """크라이시스 복구 모드 TP/SL 평가.

        Stage 1 (첫 TP 미발동):
          - +5% 도달 시 CRISIS_TP1 (25% 청산)
          - 그 외엔 None (정상 모드 SL -50% 룰로 폴스루)

        Stage 2 (첫 TP 발동 후):
          - PnL ≤ -1% → CRISIS_HARD_SL (전량 손절)
          - 피크 ≥ 5% AND 현재 ≤ 피크 -5% → CRISIS_TRAIL_FULL (전량 청산)
          - +10% 이상 → 정상 TP2~5 룰 폴스루
        """
        # Stage 1 — TP1 미발동
        if not strategy.crisis_first_tp_done_at:
            if pnl_ratio >= CRISIS_TP1_THRESHOLD:
                return "CRISIS_TP1"
            return None  # 폴스루 → 정상 모드 SL 검사

        # Stage 2 — TP1 발동 후, 보호 모드 풀가동
        # 피크 PnL 갱신
        prev_peak = Decimal(str(strategy.peak_pnl_pct_after_first_tp)) if strategy.peak_pnl_pct_after_first_tp is not None else pnl_ratio
        new_peak = pnl_ratio if pnl_ratio > prev_peak else prev_peak
        strategy.peak_pnl_pct_after_first_tp = new_peak

        # 우선순위 1 — 빠른 손절 -1% (절대 양보 안 함)
        if pnl_ratio <= CRISIS_HARD_SL_THRESHOLD:
            return "CRISIS_HARD_SL"

        # 우선순위 2 — 트레일링 -5% (피크 대비 -5% 회귀)
        if new_peak >= CRISIS_TP1_THRESHOLD and pnl_ratio <= (new_peak - CRISIS_TRAILING_DROP):
            return "CRISIS_TRAIL_FULL"

        # 우선순위 3 — 폴스루 → 정상 TP2~5 룰 평가
        return None

    def evaluate_stop_loss_crisis_aware(self, strategy_id: int, pnl_ratio: Decimal | None = None) -> bool:
        """크라이시스 Stage 2 (TP1 발동 후) 인 경우 -1% 손절 검사. 그 외엔 기존 -50% 룰 유지.

        호출자는 이 메서드를 evaluate_stop_loss 대신 사용. 기존 evaluate_stop_loss 는
        하위 호환성을 위해 유지.
        """
        strategy = self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            return False
        # Stage 2 — TP1 발동 후 -1% 손절
        if strategy.crisis_first_tp_done_at and pnl_ratio is not None:
            if pnl_ratio <= CRISIS_HARD_SL_THRESHOLD:
                return True
        # 그 외엔 기존 -50% 룰
        return self.evaluate_stop_loss(strategy_id)

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
