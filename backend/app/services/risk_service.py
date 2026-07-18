import logging
from datetime import datetime, timezone
from decimal import Decimal

from app.core.redis_client import get_redis_client

logger = logging.getLogger(__name__)
from app.models.risk_event import RiskEvent
from app.observability.metrics import strategy_stop_loss_total
from app.repositories.position_repository import PositionRepository
from app.repositories.strategy_repository import StrategyRepository
from app.services.strategy_calculator import StrategyCalculator, SymbolRule

# 트레일링 익절 / 크라이시스 / 손실 알림 정책 상수 — 2026-05-14 Phase 2 centralize.
# 정책 변경 시 app/core/risk_constants.py 만 수정 → 모든 사용처 자동 반영.
# 이 모듈은 backward compat 을 위해 재export (외부 import 경로 유지).
#
# 정책 history (참조):
# - 트레일링 v5 (2026-05-12): TP3+ AND stage>=3 두 조건 동시 만족
# - 크라이시스 v2 (2026-05-07): -50% 손실 + 모든 단계 진입 후 +5% 부터 회복
# - 5-14: template.crisis_max_loss_threshold 사용자 정의 가능 (-100=비활성)
from app.core.risk_constants import (
    CRISIS_HARD_SL_THRESHOLD_PCT as CRISIS_HARD_SL_THRESHOLD,
    CRISIS_MAX_LOSS_THRESHOLD_DEFAULT as CRISIS_MAX_LOSS_THRESHOLD,
    CRISIS_TP1_THRESHOLD_PCT as CRISIS_TP1_THRESHOLD,
    CRISIS_TRAILING_DROP_PCT as CRISIS_TRAILING_DROP,
    LOSS_ALERT_THRESHOLD_PCT as LOSS_ALERT_THRESHOLD,
    PEAK_REDIS_TTL_SECONDS,
    TRAILING_MIN_STAGE,
    TRAILING_MIN_TP_INDEX,
    TRAILING_PEAK_THRESHOLD_PCT as TRAILING_TP_PEAK_THRESHOLD,
    TRAILING_RETRACE_PCT as TRAILING_TP_RETRACE_AMOUNT,
)

def force_sl_should_trigger(
    *,
    side: str,
    avg_entry: Decimal | float | str | None,
    mark_price: Decimal | float | str | None,
    leverage: Decimal | float | str | None,
    enabled: bool,
    threshold: Decimal | float | str | None,
) -> bool:
    """손실 한도 강제 청산 ROI 판정 (순수 함수 — DB 무관, 테스트 가능).

    FORCE_SL_LOSS_LIMIT_SPEC 2026-06-24. 기존 SL 과 ROI 계산 동일:
      LONG:  (mark - avg) / avg × 100 × lev
      SHORT: (avg - mark) / avg × 100 × lev
    `enabled` False 거나 threshold<=0 거나 가격 없음 → False (= 청산 금지, 안전 최우선).
    threshold 는 양수 (예: 10). ROI <= -threshold 이면 True.
    """
    from app.core.risk_constants import LEVERAGE_FALLBACK, PERCENT_DENOMINATOR
    if not enabled:
        return False
    if threshold is None:
        return False
    thr = Decimal(str(threshold))
    if thr <= 0:
        return False
    if avg_entry is None or mark_price is None:
        return False
    avg = Decimal(str(avg_entry))
    mark = Decimal(str(mark_price))
    if avg <= 0 or mark <= 0:
        return False
    lev = Decimal(str(leverage)) if leverage else LEVERAGE_FALLBACK
    if (side or "").upper() == "LONG":
        price_change_pct = ((mark - avg) / avg) * PERCENT_DENOMINATOR
    else:  # SHORT
        price_change_pct = ((avg - mark) / avg) * PERCENT_DENOMINATOR
    roi = price_change_pct * lev
    return roi <= -thr


def resolve_force_sl(
    *,
    override_enabled: bool | None,
    override_roi: Decimal | float | str | None,
    global_enabled: bool,
    global_roi: Decimal,
) -> tuple[bool, Decimal]:
    """전략별 override → 전역 우선순위 해석 (순수 함수, 테스트 가능).

    사장님 2026-06-24: "모두에게 같은 적용 + 각 전략에 우선하는 방식".
    override 값이 None 이면 전역 상속, 아니면 전략 우선.
    """
    enabled = override_enabled if override_enabled is not None else global_enabled
    threshold = Decimal(str(override_roi)) if override_roi is not None else global_roi
    return enabled, threshold


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

        # 🌟🌟🌟 2026-06-11 사장님 critical 영구 fix v4 (BEATUSDT #110 청산 사건!):
        #
        # 사장님 명시 (= 2026-06-11):
        # "6단계를 뺀다고 포지션 진입가에서 손실 -80% 는 아니잖아!"
        # = SL = **포지션 진입가 (평단) 기준 ROI -80%!**
        # = 가격 변동만 봐야!
        # = 자본 (total_capital) 변경 = SL 영향 X!
        #
        # ⛔ 옛 silent bug (PR #57, 2026-06-09):
        # threshold = (total_capital / lev) × 80% = USDT 절대 한도
        # = 자본 변경 시 = 한도 변경 = silent bug!
        # = 사장님 6단계 취소 → total_capital 6100 → 2700 → 한도 -2440 → -1080 → 청산!
        #
        # 🛡 신 fix v4 (사장님 사상 100% 정확!):
        # 1. 평단 vs 현재가 = 가격 변동 % 계산
        # 2. × leverage = ROI %
        # 3. ROI <= -80% = SL 발동!
        # = total_capital 완전 무관 = 사장님 자본 100% 영구 보호!
        from app.core.risk_constants import (
            DEFAULT_SL_PCT_OF_CAPITAL,
            LEVERAGE_FALLBACK,
            PERCENT_DENOMINATOR,
        )
        from app.models.strategy_template import StrategyTemplate
        tpl = self.db.get(StrategyTemplate, strategy.strategy_template_id) if strategy.strategy_template_id else None
        sl_pct = (
            Decimal(str(tpl.stop_loss_percent_of_capital))
            if tpl and tpl.stop_loss_percent_of_capital and Decimal(str(tpl.stop_loss_percent_of_capital)) > 0
            else DEFAULT_SL_PCT_OF_CAPITAL  # template 미설정 시 default 80%
        )
        leverage = Decimal(str(strategy.leverage)) if strategy.leverage else LEVERAGE_FALLBACK

        # 🛡 평단 (= 포지션 진입가) 조회!
        avg_entry = Decimal(str(strategy.avg_entry_price)) if strategy.avg_entry_price else None
        # 현재가 = position.mark_price 조회
        latest_position = self.position_repo.latest_by_strategy(strategy_id)
        mark_price = (
            Decimal(str(latest_position.mark_price))
            if latest_position and latest_position.mark_price else None
        )

        # 평단/현재가 미존재 시 = SL 검증 불가 = False
        if not avg_entry or not mark_price or avg_entry <= 0:
            return False

        # 🌟 사장님 사상 v4: ROI = (평단 vs 현재가) × leverage!
        # SHORT: 가격 하락 = 이익, 가격 상승 = 손실
        # LONG: 가격 상승 = 이익, 가격 하락 = 손실
        if strategy.side == "LONG":
            price_change_pct = ((mark_price - avg_entry) / avg_entry) * PERCENT_DENOMINATOR
        else:  # SHORT
            price_change_pct = ((avg_entry - mark_price) / avg_entry) * PERCENT_DENOMINATOR
        # ROI = 가격 변동 × leverage
        unrealized_roi = price_change_pct * leverage
        # SL 발동: ROI <= -80%
        is_stop = unrealized_roi <= -sl_pct

        if is_stop:
            current_loss_amount = Decimal(str(strategy.realized_pnl or 0)) + Decimal(str(strategy.unrealized_pnl or 0))
            self.db.add(RiskEvent(
                strategy_instance_id=strategy.id,
                event_type="STOP_LOSS_TRIGGERED",
                severity="CRITICAL",
                title="🛑 손절 발동 (Stop Loss)",
                message=(
                    f"평단 {avg_entry} → 현재가 {mark_price} = 가격 변동 {price_change_pct:.2f}% "
                    f"× lev {leverage}x = ROI {unrealized_roi:.2f}% (= 한도 -{sl_pct}% 도달) → 강제 전량 청산. "
                    f"(= 사장님 사상 2026-06-11 v4 — 포지션 진입가 기준 ROI -{sl_pct}%, 자본 무관!)"
                ),
                event_payload={
                    "avg_entry_price": str(avg_entry),
                    "mark_price": str(mark_price),
                    "price_change_pct": str(price_change_pct),
                    "leverage": str(leverage),
                    "unrealized_roi": str(unrealized_roi),
                    "sl_pct": str(sl_pct),
                    "current_loss_amount": str(current_loss_amount),
                    "side": strategy.side,
                },
            ))
            strategy_stop_loss_total.labels(symbol=strategy.symbol, side=strategy.side).inc()
            self.db.flush()
        return is_stop

    def evaluate_force_stop_loss(self, strategy_id: int) -> bool:
        """손실 한도 강제 청산 평가 (FORCE_SL_LOSS_LIMIT_SPEC 2026-06-24).

        기존 evaluate_stop_loss 와 ROI 계산 동일, 단 차이:
          - 단계 게이트 없음 (= 아무 단계에서나 발동 — 물타기 전에 손절).
          - 전역 system_settings 의 force_sl_{long|short}_* 사용 (side별 독립).
          - mark_price = Redis 실시간 우선 (v51 단일 진실), miss 시 DB snapshot fallback.
            둘 다 없으면 False (= 가격 모르면 절대 청산 X — 안전 최우선).
        발동 시 RiskEvent(CRITICAL) 기록 후 True 반환 (실제 청산은 orchestrator).
        """
        strategy = self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            return False
        side = (strategy.side or "").upper()
        # 전역 설정(모든 전략 기본) + 전략별 override 우선 (NULL = 전역 상속).
        # 사장님 2026-06-24: "모두에게 같은 적용 + 각 전략에 우선하는 방식".
        from app.services.system_settings_service import SystemSettingsService
        g_enabled, g_threshold = SystemSettingsService(self.db).get_force_sl(side)
        enabled, threshold = resolve_force_sl(
            override_enabled=strategy.force_sl_enabled_override,
            override_roi=strategy.force_sl_roi_override,
            global_enabled=g_enabled,
            global_roi=g_threshold,
        )
        if not enabled or threshold <= 0:
            return False
        avg_entry = Decimal(str(strategy.avg_entry_price)) if strategy.avg_entry_price else None
        # mark_price: Redis 실시간 캐시 우선 (= 화면 현재가와 동일 소스, v51), miss 시 DB snapshot.
        from app.services.mark_price_cache import get_mark_price
        mark_price = get_mark_price(strategy.symbol)
        if mark_price is None or mark_price <= 0:
            latest_position = self.position_repo.latest_by_strategy(strategy_id)
            if latest_position and latest_position.mark_price:
                mark_price = Decimal(str(latest_position.mark_price))
        # 가격 정보 없으면 절대 청산 X (= 잘못된 데이터로 실자금 청산 금지)
        if avg_entry is None or mark_price is None or avg_entry <= 0 or mark_price <= 0:
            return False
        leverage = Decimal(str(strategy.leverage)) if strategy.leverage else Decimal("1")
        is_force = force_sl_should_trigger(
            side=side, avg_entry=avg_entry, mark_price=mark_price,
            leverage=leverage, enabled=enabled, threshold=threshold,
        )
        if is_force:
            from app.core.risk_constants import PERCENT_DENOMINATOR
            if side == "LONG":
                price_change_pct = ((mark_price - avg_entry) / avg_entry) * PERCENT_DENOMINATOR
            else:
                price_change_pct = ((avg_entry - mark_price) / avg_entry) * PERCENT_DENOMINATOR
            roi = price_change_pct * leverage
            self.db.add(RiskEvent(
                strategy_instance_id=strategy.id,
                event_type="FORCE_STOP_LOSS_TRIGGERED",
                severity="CRITICAL",
                title=f"🛑 손실 한도 강제 청산 — #{strategy.id} {strategy.symbol} {side}",
                message=(
                    f"평단 {avg_entry} → 현재가 {mark_price} = 가격 변동 {price_change_pct:.2f}% "
                    f"× lev {leverage}x = ROI {roi:.2f}% (= 사장님 한도 -{threshold}% 도달) "
                    f"→ 전량 강제 청산 + 전략 종료 (재진입 X). "
                    f"(= FORCE_SL 2026-06-24, 아무 단계에서나 발동)"
                ),
                event_payload={
                    "avg_entry_price": str(avg_entry),
                    "mark_price": str(mark_price),
                    "price_change_pct": str(price_change_pct),
                    "leverage": str(leverage),
                    "unrealized_roi": str(roi),
                    "threshold": str(threshold),
                    "side": side,
                    "current_stage": strategy.current_stage,
                },
            ))
            self.db.flush()
        return is_force

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
        from app.core.risk_constants import LEVERAGE_FALLBACK, PERCENT_DENOMINATOR
        raw_pnl_pct = ((mark_price - avg_entry) / avg_entry) * PERCENT_DENOMINATOR if strategy.side == "LONG" else ((avg_entry - mark_price) / avg_entry) * PERCENT_DENOMINATOR
        leverage = Decimal(str(strategy.leverage)) if strategy.leverage else LEVERAGE_FALLBACK
        pnl_ratio = raw_pnl_pct * leverage

        # ─────────── PnL 추적 + 크라이시스 모드 검사 (Phase D-1) ───────────
        # 2026-05-04: -50% 임계 알림 — _update_pnl_extremes 가 max_loss_pct 갱신하므로
        # 호출 전 prev 값 캡처해서 임계 교차 (prev > -50, new ≤ -50) 1회 감지.
        prev_max_loss = strategy.max_loss_pct
        self._update_pnl_extremes(strategy, pnl_ratio)
        new_max_loss = strategy.max_loss_pct
        self._maybe_send_loss_threshold_alert(strategy, prev_max_loss, new_max_loss)
        # 2026-06-03 신규: SL 진행률 80% 도달 시 1회 알림 (사장님 사상 PR #57 자본 기준).
        # PR #64 의 시각화 (빨강 배지) + Telegram 즉시 인지 = 사장님 운영 안전 보강.
        self._maybe_send_sl_progress_alert(strategy)
        if not strategy.crisis_mode_triggered_at and self._should_trigger_crisis_mode(strategy, pnl_ratio):
            self._enter_crisis_mode(strategy)

        # 피크 갱신 — Redis stored + DB max_profit_pct fallback 중 진정한 max.
        # 2026-05-06 fix (#103): Redis key 휘발 시 DB historical peak 으로 fallback.
        peak = self._update_peak_pnl(strategy_id, pnl_ratio, strategy.max_profit_pct)

        # 템플릿에서 모든 TP 임계치 가져오기 (TP1~TP10, 2026-05-06 사용자 요청).
        # NULL 인 단계는 미사용 — 활성 단계만 평가.
        tpl = self.db.get(StrategyTemplate, strategy.strategy_template_id)
        tp_levels: list[tuple[str, Decimal]] = []
        for n in range(10, 0, -1):  # TP10..TP1
            attr = f"tp{n}_percent"
            val = getattr(tpl, attr, None) if tpl else None
            if val is not None:
                tp_levels.append((f"TP{n}", Decimal(str(val))))

        # ─────────── 크라이시스 모드 — TP 임계치 override (사용자 기획) ───────────
        # 정상 모드: TP1 = 사장님 옵션 (10/15/20/25) 또는 template default, TP2-4 = template
        # 크라이시스: TP1/2/3/4 = 5/10/15/20% (= 옛 그대로, 사장님 옵션 무시)
        # TP5 는 크라이시스 모드에서 사용 안 함 (4단계 TP 까지만)
        #
        # 🌟 2026-06-10 v30 사장님 critical 결정 (= Crisis 모드 영구 비활성!):
        # > '크라이스에서 계속 오류가 나는것 같은데 이기능을 취소하고 세팅된 율로 적용해줘'
        # = Crisis 옵션 무시 = 사장님 설정 TP1~TP4 항상 우선!
        # = 옛 Crisis = 사장님이 임의 조정 자율
        #
        # 신 정책:
        # - crisis_mode_triggered_at 있는 strategy (= 옛 진입) = TP override 안 함
        # - 사장님 TP1 옵션 = 항상 우선 적용
        # 🚨 2026-07-18 v105 사장님 CRITICAL fix: TP1 옵션 = 모든 TP 상향!
        # 사장님 report: TP1 = 25% 설정, But TP2 = ROI 14.61%에서 발동!
        # 옛 로직: TP1만 override, TP2/TP3 = template 값 유지 (silent bug!)
        # 사장님 사상: "TP1 25% 부터 = 모든 TP = 25% 이상만 발동!"
        # v105 fix: max(override, val) = TP1 이상만 발동 보장!
        if strategy.tp1_pct_override is not None:
            _override = Decimal(str(strategy.tp1_pct_override))
            tp_levels = [
                (label, max(_override, val) if val is not None else val)
                for label, val in tp_levels
            ]
            logger.info(
                "[risk] v105 사장님 TP1 옵션 = 모든 TP 상향! strategy=%s TP1_override=%s → tp_levels=%s",
                strategy.id, _override, tp_levels
            )

        # 2026-05-04 critical fix (사용자 #98 LABUSDT 사례):
        # 트레일링 체크가 TP threshold loop 보다 우선해야 함.
        # 2026-05-07 v2: TP3 (idx 2) 발동 후부터 trailing armed.
        # 2026-05-12 새벽 v3: TP4 강제로 변경.
        # 2026-05-12 저녁 v4: v3 → v2 revert (사용자 본래 의도 TP3+).
        # 2026-05-12 밤 v5: v4 + 「current_stage >= 3」 추가 조건.
        # 즉 두 조건 동시 만족 필요:
        #   ① TP3 발동 (status >= TP3_DONE_PARTIAL)
        #   ② 진입 단계 3 이상 (current_stage >= 3)
        # 2단계까지만 진입한 strategy 의 짧은 잔량 trailing 청산 무력화 (사용자 의도).
        TRAILING_ARMED_STATUSES = (
            {f"TP{n}_DONE_PARTIAL" for n in range(TRAILING_MIN_TP_INDEX, 11)}
            | {"TRAILING_ARMED"}
        )
        # 🌟 2026-06-08 사장님 trailing retrace 옵션 (alembic 0017):
        # NULL/5 = default (옛 동작), 10/15/20 = 사장님 선택 (= buffer 더 큼)
        # spec: TRAILING_RETRACE_POLICY_SPEC_2026-06-08.md
        _strategy_retrace = (
            Decimal(str(strategy.trailing_retrace_pct))
            if strategy.trailing_retrace_pct is not None
            else TRAILING_TP_RETRACE_AMOUNT  # global default = 5
        )
        if (
            (strategy.status or "").upper() in TRAILING_ARMED_STATUSES
            and (strategy.current_stage or 0) >= TRAILING_MIN_STAGE
            and peak >= TRAILING_TP_PEAK_THRESHOLD
            and pnl_ratio <= (peak - _strategy_retrace)
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
        # 2026-05-06: TP1~10 단계 동적 (사용자 요청 10단계 확장).
        TP_DONE_INDEX = {f"TP{n}_DONE_PARTIAL": n - 1 for n in range(1, 11)}
        TP_DONE_INDEX["TP2_DONE"] = 1  # legacy 호환
        TP_LABEL_TO_IDX = {f"TP{n}": n - 1 for n in range(1, 11)}
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
        """크라이시스 모드 진입 조건.

        🌟 2026-06-10 v30 사장님 critical 결정 (= 영구 비활성화!):
        > '크라이스에서 계속 오류가 나는것 같은데 이기능을 취소하고
        >  세팅된 율로 적용해줘 이건 사용자가 임의 세팅하면 될것 같아'
        = 사장님 결정: Crisis 모드 = 영구 비활성!
        = TP1~TP4 + Trailing = 사장님 설정 그대로 사용
        = 사장님 운영자 = 임의 조정 자율
        = silent bug 원천 차단!

        옛 기획 (= 사장님 결정으로 폐기):
        - v2: 모든 stage 진입 완료 + max_loss ≤ -50% 도달
        - v3: 임계 사용자 정의 가능
        - v4: ad-hoc 안전망

        신 v30: 무조건 False (= Crisis 자동 진입 영원히 X)
        """
        # 🌟 v30 사장님 결정: Crisis 모드 영구 비활성화!
        return False
        # 옛 코드 (= 사장님 결정으로 비활성):
        if strategy.crisis_mode_triggered_at:
            return False
        # 🌟 2026-06-10 v23 사장님 신 critical 사상 (= 운영자 우선!):
        # 사장님이 옵션 변경 (tp1, trailing 등) = Redis flag 설정 = 24시간 Crisis 재진입 차단
        # = "운영자가 크라이시스를 해제하고 다른 선택을 했어 = 그러면 그렇게 되어야 해"
        try:
            from app.core.redis_client import get_redis_client
            _redis = get_redis_client()
            if _redis.get(f"crisis_user_override:strategy:{strategy.id}"):
                logger.info(
                    "[risk] Crisis 자동 진입 차단 (사장님 v23 override 활성): strategy=%s",
                    strategy.id,
                )
                return False
        except Exception:
            pass
        # Template 별 크라이시스 임계 결정
        from app.models.strategy_template import StrategyTemplate
        tpl = self.db.get(StrategyTemplate, strategy.strategy_template_id) if strategy.strategy_template_id else None
        threshold = (
            Decimal(str(tpl.crisis_max_loss_threshold))
            if tpl and tpl.crisis_max_loss_threshold is not None
            else CRISIS_MAX_LOSS_THRESHOLD  # global -50
        )
        # -100 이하 = 크라이시스 비활성 (어떤 손실도 이 임계에 도달 불가능 — leveraged ROI 도 -100% 가 사실상 청산)
        from app.core.risk_constants import CRISIS_DISABLED_SENTINEL
        if threshold <= CRISIS_DISABLED_SENTINEL:
            return False
        # 1) Stage 조건: 모든 단계 진입 OR 「💉 포지션 추가」 (ad-hoc) 사용 (v4 안전망)
        total_stages = self._get_total_stages(strategy)
        if (strategy.current_stage or 0) < total_stages:
            # 모든 단계 미진입 → ad-hoc 사용 흔적 확인
            from app.models.order import Order
            from sqlalchemy import select as sa_select
            has_adhoc = self.db.execute(
                sa_select(Order.id).where(
                    Order.strategy_instance_id == strategy.id,
                    Order.stage_no.is_(None),    # ad-hoc 표시
                    Order.purpose == "ENTRY",
                    Order.status == "FILLED",     # 실제 체결된 것만
                ).limit(1)
            ).scalar_one_or_none()
            if not has_adhoc:
                return False
            # ad-hoc 사용함 → stage 조건 완화, max_loss 검사로 진행
        # 2) 누적 최대 손실 임계 이하 도달
        if strategy.max_loss_pct is None:
            return False
        max_loss = Decimal(str(strategy.max_loss_pct))
        if max_loss > threshold:  # 예: threshold -60, max_loss -45 면 -60 미달 → skip
            return False
        return True

    def _maybe_send_sl_progress_alert(self, strategy) -> None:
        """SL 진행률 80% 도달 시 1회 Telegram 알림 (사장님 사상 PR #57: 자본 기준).

        2026-06-03 신설 — PR #64 (전략 인스턴스 카드 SL 시각화) 의 Telegram 보완.
        사장님이 화면 안 봐도 SL 발동 임박 즉시 인지 → 결정 도움.

        계산 (PR #57 사장님 사상 일치):
          SL 한도 = total_capital × sl_pct / 100  (레버리지 무관)
          현재 손실 = realized + unrealized
          진행률 = abs(현재 손실) / SL 한도 × 100  (현재 손실 음수일 때)

        Dedup: Redis 'sl_progress_alerted:{strategy_id}' TTL 1시간.
          - 첫 80% 도달 시 알림 + flag SET
          - 1시간 안 재알림 X (spam 방지)
          - 1시간 후 재계산 — 여전히 80% 면 재알림 (사장님 인지 강화)
          - 진행률 < 50% 회복 시 flag DEL (다음 80% 도달 시 새로 알림)
        """
        try:
            from app.core.redis_client import get_redis_client
            from app.models.strategy_template import StrategyTemplate
            from app.core.risk_constants import DEFAULT_SL_PCT_OF_CAPITAL, PERCENT_DENOMINATOR

            total_capital = Decimal(str(strategy.total_capital or 0))
            if total_capital <= 0:
                return
            current_loss = Decimal(str(strategy.realized_pnl or 0)) + Decimal(str(strategy.unrealized_pnl or 0))
            if current_loss >= 0:
                return  # 이익 중 — 알림 의미 X
            tpl = self.db.get(StrategyTemplate, strategy.strategy_template_id) if strategy.strategy_template_id else None
            sl_pct = (
                Decimal(str(tpl.stop_loss_percent_of_capital))
                if tpl and tpl.stop_loss_percent_of_capital and Decimal(str(tpl.stop_loss_percent_of_capital)) > 0
                else DEFAULT_SL_PCT_OF_CAPITAL
            )
            # 🌟 2026-06-09 사장님 사상 정확: SL = 마진 (= 사장님 자금) × sl_pct
            leverage = Decimal(str(strategy.leverage or 1))
            margin = total_capital / leverage if leverage > 0 else total_capital
            sl_threshold = margin * (sl_pct / PERCENT_DENOMINATOR)
            if sl_threshold <= 0:
                return
            progress_pct = abs(current_loss) / sl_threshold * 100

            try:
                redis = get_redis_client()
            except Exception:
                redis = None
            flag_key = f"sl_progress_alerted:{strategy.id}"

            if progress_pct < 50:
                # 회복 중 — flag 제거 (다음 80% 도달 시 새 알림)
                if redis:
                    try: redis.delete(flag_key)
                    except Exception: pass
                return

            if progress_pct < 80:
                return  # 80% 미달

            # 80% 도달 — dedup 확인
            if redis:
                try:
                    if redis.get(flag_key):
                        return  # 1시간 내 이미 알림
                    redis.setex(flag_key, 3600, "1")
                except Exception:
                    pass

            # 알림 발송 — RiskEvent + Telegram
            remaining_usd = sl_threshold + current_loss  # current_loss 음수
            self.db.add(RiskEvent(
                strategy_instance_id=strategy.id,
                event_type="SL_PROGRESS_80PCT_REACHED",
                severity="WARNING",
                title=f"🚨 SL 발동 임박 — {progress_pct:.0f}% 도달",
                message=(
                    f"{strategy.symbol} {strategy.side} 손실 {current_loss:.2f} USDT / SL 한도 {-sl_threshold:.2f} USDT "
                    f"= 진행률 {progress_pct:.1f}%. 남은 마진 {remaining_usd:.2f} USDT. "
                    f"투자금 {total_capital} USDT × {sl_pct}% (PR #57 사장님 사상, 레버리지 무관). "
                    "긴급 종료 / 증거금 추가 검토 권장."
                ),
                event_payload={
                    "progress_pct": str(progress_pct),
                    "current_loss": str(current_loss),
                    "sl_threshold": str(sl_threshold),
                    "remaining_usd": str(remaining_usd),
                    "total_capital": str(total_capital),
                    "sl_pct": str(sl_pct),
                },
            ))
            self.db.flush()
            try:
                from app.services.notification_service import NotificationService
                NotificationService(self.db).send_system_alert(
                    title=f"🚨 [SL 임박] {strategy.symbol} {strategy.side} — {progress_pct:.0f}% 도달",
                    body=(
                        f"📌 strategy #{strategy.id}\n"
                        f"💰 손실: {current_loss:.2f} USDT (한도 {-sl_threshold:.2f})\n"
                        f"📊 진행률: {progress_pct:.1f}% (남은 {remaining_usd:.2f} USDT)\n"
                        f"🔢 투자금 {total_capital} × {sl_pct}% (레버리지 무관)\n\n"
                        f"⚠️ 옵션:\n"
                        f"  • 💰 증거금 추가 (SL 한도 자동 증가 PR #56)\n"
                        f"  • 💉 포지션 추가 (평단 회복)\n"
                        f"  • 🛑 긴급 종료 (수동 청산)"
                    ),
                )
            except Exception:
                pass
        except Exception as e:
            logger.warning("[sl-progress-alert] strategy=%s failed: %s", strategy.id, e)

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

        # 첫 교차 — RiskEvent + Telegram 알림.
        # 2026-05-08 fix (사용자 보고): 「강제 청산 임박」 표현이 오해 유발.
        # 실제 강제 청산은 evaluate_stop_loss 의 가드 「모든 단계 진입 후」 만 발동.
        # 단계 미완료시엔 추가 stage 진입으로 평단가 평균화 기회 먼저 줌.
        # 메시지에 현재 단계 상황 명시해 사용자 이해 돕는다.
        total_stages = self._get_total_stages(strategy)
        cur_stage = strategy.current_stage or 0
        all_entered = cur_stage >= total_stages
        if all_entered:
            sl_status = f"⚠️ 모든 단계 ({cur_stage}/{total_stages}) 진입 완료 — 다음 cycle 에 강제 청산 발동 예정."
        else:
            sl_status = (
                f"📌 현재 {cur_stage}/{total_stages} 단계만 진입 — 강제 청산 미발동 "
                f"(SL 은 모든 단계 진입 후만 발동). 추가 단계 진입으로 평단 회복 기회 대기 중."
            )
        try:
            self.db.add(RiskEvent(
                strategy_instance_id=strategy.id,
                event_type="LOSS_THRESHOLD_50PCT_REACHED",
                severity="WARNING",
                title=f"⚠️ 손실 {LOSS_ALERT_THRESHOLD}% 도달 — 위험 경고",
                message=(
                    f"{strategy.symbol} {strategy.side} ROI {new_d}% — "
                    f"임계 {LOSS_ALERT_THRESHOLD}% 도달. {sl_status} "
                    "증거금 추가 또는 수동 청산 검토 권장."
                ),
                event_payload={
                    "pnl_pct": str(new_d),
                    "threshold_pct": str(LOSS_ALERT_THRESHOLD),
                    "current_stage": cur_stage,
                    "total_stages": total_stages,
                    "all_entered": all_entered,
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
                current_stage=cur_stage,
                total_stages=total_stages,
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
            message=f"전 단계 진입 완료 + 누적 최대 손실 {strategy.max_loss_pct}% 도달 (≤ {CRISIS_MAX_LOSS_THRESHOLD}%). TP1 임계가 +5% 로 변경되어 빠른 회복 익절 시작.",
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
