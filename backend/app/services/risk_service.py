from datetime import datetime, timezone
from decimal import Decimal

from app.core.redis_client import get_redis_client
from app.models.risk_event import RiskEvent
from app.observability.metrics import strategy_stop_loss_total
from app.repositories.position_repository import PositionRepository
from app.repositories.strategy_repository import StrategyRepository
from app.services.strategy_calculator import StrategyCalculator, SymbolRule

# 트레일링 익절 임계치 (정상 모드)
# 사용자 기획 (2026-04-30): "익절을 단계별로 진행하는 중에 -5% 하락하면 모두 청산익절".
# 기존엔 절대 임계치 (피크 ≥ 20% AND 현재 ≤ 20%) 였으나, 사용자 기획대로
# 피크 대비 -5% 회귀 (relative drop) 로 변경. TP1 발동 후부터 활성화.
TRAILING_TP_PEAK_THRESHOLD = Decimal("5")    # 피크가 이 % 이상 도달했어야 트레일링 활성화 (TP1+5% 시점)
TRAILING_TP_RETRACE_AMOUNT = Decimal("5")    # 피크 대비 이 % 만큼 하락하면 발동 (예: peak 25% → 20% 시 청산)
PEAK_REDIS_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days

# 크라이시스 복구 모드 임계치
CRISIS_MIN_STAGE = 5                # 5단계 이상 진입
CRISIS_MAX_LOSS_THRESHOLD = Decimal("-30")  # 누적 최대 손실 -30% 이하 도달
CRISIS_TP1_THRESHOLD = Decimal("5")         # 크라이시스 모드 첫 TP +5%
CRISIS_TRAILING_DROP = Decimal("5")         # 첫 TP 후 피크 -5% 회귀 시 전량 청산
CRISIS_HARD_SL_THRESHOLD = Decimal("-1")    # 첫 TP 후 PnL -1% 이하 시 전량 손절

# 손실 알림 임계 (2026-05-04 신규) — 강제 청산 (-50%) 도달 시 1회 알림.
# 도달 = max_loss_pct 가 처음 이 임계 이하로 내려가는 사이클.
# 상태는 strategy.max_loss_pct 의 prev/new 비교로 판정 (별도 컬럼 불필요).
LOSS_ALERT_THRESHOLD = Decimal("-50")

class RiskService:
    def __init__(self, db) -> None:
        self.db = db
        self.strategy_repo = StrategyRepository(db)
        self.position_repo = PositionRepository(db)

    def _get_total_stages(self, strategy) -> int:
        """Strategy 의 template stages_config 에서 총 단계 수 조회.

        1~10 단계 동적 지원. 비어있는 단계는 capitals 에 없으므로 자동 제외됨.
        Template 가 없거나 stages_config 가 없으면 legacy 4단계로 fallback.
        """
        from app.models.strategy_template import StrategyTemplate
        tpl = self.db.get(StrategyTemplate, strategy.strategy_template_id)
        if not tpl:
            return 4
        cfg = tpl.stages_config or {}
        capitals = cfg.get("capitals") or []
        return len(capitals) if capitals else 4

    def evaluate_stop_loss(self, strategy_id: int) -> bool:
        strategy = self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            raise ValueError("Strategy not found")
        # 사용자 기획: SL 은 모든 단계가 진입된 후에만 발동.
        # 진입할 단계가 남아있으면 추가 진입(평단가 평균화) 기회를 먼저 줌.
        total_stages = self._get_total_stages(strategy)
        if (strategy.current_stage or 0) < total_stages:
            return False
        current_loss_amount = Decimal(str(strategy.realized_pnl)) + Decimal(str(strategy.unrealized_pnl))
        # SL 은 레버리지 적용된 ROI -50% 기준.
        # qty = capital/price (notional 모델) 이므로 raw price -50% = USD 손실 -capital*0.50.
        # 레버리지 적용된 ROI = (USD 손실 / margin) × 100 = (USD 손실 × leverage / capital) × 100.
        # ROI -50% 도달 → USD 손실 = -capital × 0.50 / leverage. (1x:가격-50%, 2x:가격-25%, 5x:가격-10%)
        leverage = Decimal(str(strategy.leverage)) if strategy.leverage else Decimal("1")
        threshold = (Decimal(str(strategy.total_capital)) * Decimal("0.50")) / leverage
        is_stop = current_loss_amount <= (-threshold)
        if is_stop:
            self.db.add(RiskEvent(strategy_instance_id=strategy.id, event_type="STOP_LOSS_TRIGGERED", severity="CRITICAL", title="🛑 손절 발동 (Stop Loss)", message=f"현재 손실 {current_loss_amount} USDT 가 한도 {-threshold} USDT 초과 → 강제 전량 청산", event_payload={"current_loss_amount": str(current_loss_amount), "threshold": str(-threshold)}))
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
        # raw 가격 변동률에 레버리지 곱해서 사용자 실제 ROI 로 변환.
        # 이 한 곳에서 변환하면 TP1~5, 트레일링, 크라이시스, peak 추적, max_loss/profit 모두
        # 자동으로 leveraged ROI 기준으로 동작.
        raw_pnl_pct = ((mark_price - avg_entry) / avg_entry) * Decimal("100") if strategy.side == "LONG" else ((avg_entry - mark_price) / avg_entry) * Decimal("100")
        leverage = Decimal(str(strategy.leverage)) if strategy.leverage else Decimal("1")
        pnl_ratio = raw_pnl_pct * leverage

        # ─────────── PnL 추적 + 크라이시스 모드 검사 (Phase D-1) ───────────
        # 2026-05-04: -50% 임계 알림 — _update_pnl_extremes 가 max_loss_pct 갱신하므로
        # 호출 전 prev 값 캡처해서 임계 교차 (prev > -50, new ≤ -50) 1회 감지.
        prev_max_loss = strategy.max_loss_pct
        self._update_pnl_extremes(strategy, pnl_ratio)
        new_max_loss = strategy.max_loss_pct
        self._maybe_send_loss_threshold_alert(strategy, prev_max_loss, new_max_loss)
        if not strategy.crisis_mode_triggered_at and self._should_trigger_crisis_mode(strategy, pnl_ratio):
            self._enter_crisis_mode(strategy)

        # 피크 갱신 — Redis stored + DB max_profit_pct fallback 중 진정한 max.
        # 2026-05-06 fix (#103): Redis key 휘발 시 DB historical peak 으로 fallback.
        peak = self._update_peak_pnl(strategy_id, pnl_ratio, strategy.max_profit_pct)

        # 템플릿에서 모든 TP 임계치 가져오기
        tpl = self.db.get(StrategyTemplate, strategy.strategy_template_id)
        tp_levels: list[tuple[str, Decimal]] = []
        for label, attr in [("TP5", "tp5_percent"), ("TP4", "tp4_percent"), ("TP3", "tp3_percent"), ("TP2", "tp2_percent"), ("TP1", "tp1_percent")]:
            val = getattr(tpl, attr, None) if tpl else None
            if val is not None:
                tp_levels.append((label, Decimal(str(val))))

        # ─────────── 크라이시스 모드 — TP 임계치 override (사용자 기획) ───────────
        # 정상 모드: TP1/2/3/4 = 10/15/20/30% (템플릿 값 사용)
        # 크라이시스: TP1/2/3/4 = 5/10/15/20% (회복 시점에 더 빨리 익절)
        # TP5 는 크라이시스 모드에서 사용 안 함 (4단계 TP 까지만)
        if strategy.crisis_mode_triggered_at:
            CRISIS_OVERRIDE = {
                "TP1": Decimal("5"), "TP2": Decimal("10"),
                "TP3": Decimal("15"), "TP4": Decimal("20"),
            }
            tp_levels = [(label, CRISIS_OVERRIDE[label]) for label, _ in tp_levels if label in CRISIS_OVERRIDE]
            tp_levels.sort(key=lambda x: x[1], reverse=True)  # 내림차순 (TP4 부터 검사)

        # 2026-05-04 critical fix (사용자 #98 LABUSDT 사례):
        # 트레일링 체크가 TP threshold loop 보다 우선해야 함.
        # 한번 익절 후 가격이 약간 retrace 됐지만 여전히 직전 TP threshold 위에 있는
        # 모든 케이스에서 트레일링 무력화되던 버그 (잔량 영구 보유) fix.
        TRAILING_ARMED_STATUSES = {
            "TP1_DONE_PARTIAL",
            "TP2_DONE_PARTIAL", "TP2_DONE",
            "TP3_DONE_PARTIAL",
            "TP4_DONE_PARTIAL",
            "TRAILING_ARMED",
        }
        if (
            (strategy.status or "").upper() in TRAILING_ARMED_STATUSES
            and peak >= TRAILING_TP_PEAK_THRESHOLD
            and pnl_ratio <= (peak - TRAILING_TP_RETRACE_AMOUNT)
            and pnl_ratio < peak
        ):
            return "TRAILING_TP"

        # 2026-05-04 critical fix #2 (사용자 #98 — TP2 silent skip 사례):
        # 이전 로직은 descending sort 라 한 tick 에 여러 TP 임계 통과 시
        # (e.g. pnl 22% 인데 TP1=10/TP2=15/TP3=20 모두 도달) "TP3" 즉시 반환.
        # orchestrator 가 cur_done_idx (TP1=0) < tp_idx (TP3=2) 면 fire — TP2 skip!
        # → TP2 의 청산 비율 (25%) 영구 누락.
        #
        # Fix: ascending + 다음 미발동 TP 만 반환.
        # status 의 cur_done_idx 를 여기서 직접 참고해 다음 단계 TP 1개씩 반환.
        # 한 tick 1회 발동, 다음 tick 다음 TP — 점진적이지만 누락 없음.
        TP_DONE_INDEX = {
            "TP1_DONE_PARTIAL": 0,
            "TP2_DONE_PARTIAL": 1, "TP2_DONE": 1,
            "TP3_DONE_PARTIAL": 2,
            "TP4_DONE_PARTIAL": 3,
            "TP5_DONE_PARTIAL": 4,
        }
        TP_LABEL_TO_IDX = {"TP1": 0, "TP2": 1, "TP3": 2, "TP4": 3, "TP5": 4}
        cur_done_idx = TP_DONE_INDEX.get((strategy.status or "").upper(), -1)

        # ascending — 가장 낮은 임계 먼저
        for label, threshold in sorted(tp_levels, key=lambda x: x[1]):
            if pnl_ratio >= threshold and TP_LABEL_TO_IDX.get(label, -1) > cur_done_idx:
                return label

        return None

    @staticmethod
    def _peak_redis_key(strategy_id: int) -> str:
        return f"strategy:{strategy_id}:peak_pnl_pct"

    def _update_peak_pnl(
        self,
        strategy_id: int,
        current_pnl_pct: Decimal,
        db_max_profit_pct: Decimal | float | str | None = None,
    ) -> Decimal:
        """Strategy 별 PnL% 피크 갱신 + 진정한 피크 반환.

        2026-05-06 critical fix (사용자 #103 FHEUSDT 사례):
          이전엔 Redis stored 만 봐서, Redis key 가 휘발 (TTL 만료 / 재시작 / evict)
          되면 현재 PnL 이 새 peak 가 되어 trailing 무력화.
          예: 20% 까지 갔다가 7% 회귀 → Redis 사라짐 → 새 peak=7% → trailing 평가
              7 <= 7-5=2 false → 미발동 (실제론 피크 -13% 회귀로 발동했어야).

          Fix: strategy.max_profit_pct 를 fallback 으로 사용 — 진정한 historical
          peak 보존. true_peak = max(current, redis_stored, db_max_profit).
          Redis 가 stale / missing 이면 fallback 으로 갱신.
        """
        fallback = (
            Decimal(str(db_max_profit_pct))
            if db_max_profit_pct is not None
            else Decimal("-9999")
        )
        try:
            client = get_redis_client()
            key = self._peak_redis_key(strategy_id)
            stored = client.get(key)
            stored_dec = (
                Decimal(stored.decode("utf-8") if isinstance(stored, bytes) else stored)
                if stored else Decimal("-9999")
            )
            # 진정한 peak — current, Redis, DB max_profit 셋 중 최대
            true_peak = max(current_pnl_pct, stored_dec, fallback)
            # Redis 가 stale 또는 missing — true_peak 로 갱신
            if true_peak > stored_dec:
                client.set(key, str(true_peak), ex=PEAK_REDIS_TTL_SECONDS)
            return true_peak
        except Exception:  # pragma: no cover - Redis 장애 시에도 익절은 동작해야 함
            # Redis 자체 실패: current vs DB fallback 중 큰 값
            return max(current_pnl_pct, fallback)

    def reset_peak_pnl(self, strategy_id: int) -> None:
        """전략 종료/재진입 시 피크 리셋."""
        try:
            client = get_redis_client()
            client.delete(self._peak_redis_key(strategy_id))
        except Exception:
            pass

    # ─────────── 크라이시스 복구 모드 + PnL 추적 (Phase D-1) ───────────

    def _update_pnl_extremes(self, strategy, pnl_ratio: Decimal) -> None:
        """매 PnL 평가 시 max_loss/max_profit 갱신. DB commit 은 호출자 또는 다음 commit 시점.

        Bug fix (2026-04-30 evening): 이전엔 max_loss_pct is None 인 첫 호출에 양수 pnl 이
        들어가면 max_loss_pct 가 양수로 세팅되는 버그. #54 AIOTUSDT (max_loss=+10.71%) /
        #55 SKYAIUSDT (max_loss=+12.26%) 사례. 의미상 max_loss 는 음수, max_profit 은 양수만.

        - pnl_ratio < 0: max_loss_pct 후보 (더 깊은 손실로만 갱신)
        - pnl_ratio > 0: max_profit_pct 후보 (더 큰 이익으로만 갱신)
        - pnl_ratio == 0: 둘 다 갱신 안 함
        """
        if pnl_ratio < 0:
            if strategy.max_loss_pct is None or pnl_ratio < Decimal(str(strategy.max_loss_pct)):
                strategy.max_loss_pct = pnl_ratio
        elif pnl_ratio > 0:
            if strategy.max_profit_pct is None or pnl_ratio > Decimal(str(strategy.max_profit_pct)):
                strategy.max_profit_pct = pnl_ratio

    def _should_trigger_crisis_mode(self, strategy, current_pnl_pct: Decimal) -> bool:
        """크라이시스 모드 진입 조건 (사용자 기획).

        - 누적 최대 손실 ≤ -30% 도달했음 (max_loss_pct)
        - 그 후 현재 PnL 이 양수 (>0%) 로 전환됨
        - 단계 요구사항 제거 (이전에는 5+ 단계 필요했음)
        """
        if strategy.crisis_mode_triggered_at:  # 이미 진입했으면 재트리거 안 함
            return False
        if strategy.max_loss_pct is None:
            return False
        max_loss = Decimal(str(strategy.max_loss_pct))
        if max_loss > CRISIS_MAX_LOSS_THRESHOLD:  # -30% 미만 손실 (즉 -25% 같은 가벼운 손실)
            return False
        # 손실 -30% 도달 후 현재 양수 PnL 로 전환되었는지 확인 (회복 시점 포착)
        if current_pnl_pct <= 0:
            return False
        return True

    def _maybe_send_loss_threshold_alert(
        self, strategy, prev_max_loss, new_max_loss
    ) -> None:
        """max_loss_pct 가 -50% 임계를 처음 교차한 사이클에 1회 알림.

        prev / new 모두 Decimal 또는 None.
        - prev=None or prev > -50 AND new ≤ -50 → 교차 ✓
        - 이미 교차한 후 (prev ≤ -50) 는 다시 알림 안 함
        - new > -50 이면 미교차 (회복 중)
        """
        if new_max_loss is None:
            return
        new_d = Decimal(str(new_max_loss))
        if new_d > LOSS_ALERT_THRESHOLD:
            return  # 임계 미도달
        # new ≤ -50: 임계 도달. prev 가 None 또는 > -50 인 경우만 첫 교차 → 알림.
        if prev_max_loss is not None:
            try:
                prev_d = Decimal(str(prev_max_loss))
                if prev_d <= LOSS_ALERT_THRESHOLD:
                    return  # 이미 교차한 적 있음 — 재알림 안 함
            except Exception:
                pass

        # 첫 교차 — RiskEvent + Telegram 알림
        try:
            self.db.add(RiskEvent(
                strategy_instance_id=strategy.id,
                event_type="LOSS_THRESHOLD_50PCT_REACHED",
                severity="WARNING",
                title=f"⚠️ 손실 {LOSS_ALERT_THRESHOLD}% 도달 — 강제 청산 임박",
                message=(
                    f"{strategy.symbol} {strategy.side} ROI {new_d}% — "
                    f"임계 {LOSS_ALERT_THRESHOLD}% 도달. 증거금 추가 또는 수동 청산 검토."
                ),
                event_payload={
                    "pnl_pct": str(new_d),
                    "threshold_pct": str(LOSS_ALERT_THRESHOLD),
                },
            ))
            self.db.flush()
        except Exception:
            pass
        try:
            from app.services.notification_service import NotificationService
            NotificationService(self.db).send_loss_threshold_alert(
                strategy_instance_id=strategy.id,
                symbol=strategy.symbol,
                side=strategy.side,
                pnl_pct=str(new_d),
                threshold_pct=str(LOSS_ALERT_THRESHOLD),
            )
        except Exception:
            pass

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
