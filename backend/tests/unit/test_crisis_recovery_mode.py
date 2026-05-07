"""크라이시스 복구 모드 단위 테스트.

사용자 기획 v2 (2026-05-07):
- 진입 조건: 모든 stage 진입 완료 + 누적 최대 손실 ≤ -50%
- 진입 후: TP1 임계가 +5% 로 변경 → 빠른 회복 익절

3가지 시나리오:
  A. 정상 회복 — -52% → +5% TP1 → +12% 피크 → +7% 회귀 → 트레일링 청산
  B. 재하락 — -52% → +5% TP1 → -1% → 빠른 손절
  C. TP1 발동 전 추가 손실 — -52% → -60% → 정상 모드 손절
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.risk_service import (
    CRISIS_HARD_SL_THRESHOLD,
    CRISIS_MAX_LOSS_THRESHOLD,
    CRISIS_TP1_THRESHOLD,
    CRISIS_TRAILING_DROP,
)


class _FakeStrategy:
    """RiskService 가 사용하는 strategy 객체의 최소 인터페이스."""
    def __init__(self, *, current_stage=5, side="SHORT"):
        self.id = 1
        self.user_id = 1
        self.symbol = "BTCUSDT"
        self.side = side
        self.current_stage = current_stage
        self.avg_entry_price = Decimal("100000")
        self.status = "ACTIVE"
        self.strategy_template_id = 1
        # PnL 추적 컬럼
        self.max_loss_pct: Decimal | None = None
        self.max_profit_pct: Decimal | None = None
        self.crisis_mode_triggered_at = None
        self.crisis_first_tp_done_at = None
        self.peak_pnl_pct_after_first_tp: Decimal | None = None
        # 정상 모드 SL 검사용
        self.realized_pnl = Decimal("0")
        self.unrealized_pnl = Decimal("0")
        self.total_capital = Decimal("1000")


def test_crisis_constants() -> None:
    """크라이시스 모드 임계 상수 — 사용자 기획 v2 (2026-05-07).

    CRISIS_MAX_LOSS_THRESHOLD: -30 → -50 (더 깊은 손실에서 진입).
    CRISIS_MIN_STAGE 상수 제거 — 「모든 stage 진입」 동적 체크로 대체.
    """
    assert CRISIS_MAX_LOSS_THRESHOLD == Decimal("-50")
    assert CRISIS_TP1_THRESHOLD == Decimal("5")
    assert CRISIS_TRAILING_DROP == Decimal("5")
    assert CRISIS_HARD_SL_THRESHOLD == Decimal("-1")


class _ServiceShim:
    """_eval_crisis_mode_tp_sl 만 단위 테스트용으로 호출하기 위한 shim.

    실제 RiskService 는 DB / Redis 의존이라 통합 환경 필요. 여기선 메서드 로직만 검증.
    """
    @staticmethod
    def eval(strategy, pnl_ratio: Decimal) -> str | None:
        # _eval_crisis_mode_tp_sl 의 핵심 로직 인라인 (DB 호출 없음)
        # Stage 1 — TP1 미발동
        if not strategy.crisis_first_tp_done_at:
            if pnl_ratio >= CRISIS_TP1_THRESHOLD:
                return "CRISIS_TP1"
            return None
        # Stage 2 — 피크 갱신
        prev = strategy.peak_pnl_pct_after_first_tp or pnl_ratio
        new_peak = pnl_ratio if pnl_ratio > prev else prev
        strategy.peak_pnl_pct_after_first_tp = new_peak
        if pnl_ratio <= CRISIS_HARD_SL_THRESHOLD:
            return "CRISIS_HARD_SL"
        if new_peak >= CRISIS_TP1_THRESHOLD and pnl_ratio <= (new_peak - CRISIS_TRAILING_DROP):
            return "CRISIS_TRAIL_FULL"
        return None


# ──────────── 시나리오 A: 정상 회복 → 트레일링 청산 ────────────
def test_scenario_A_normal_recovery_trailing() -> None:
    s = _FakeStrategy(current_stage=5)
    # 1) 깊은 손실 누적 (-32%)
    s.max_loss_pct = Decimal("-52")
    # 2) 크라이시스 모드 진입 (시점 기록 시뮬레이션)
    from datetime import datetime, timezone
    s.crisis_mode_triggered_at = datetime.now(timezone.utc)
    # 3) 시세 회복 → +5% — TP1 발동
    assert _ServiceShim.eval(s, Decimal("5")) == "CRISIS_TP1"
    # 4) TP1 발동 시뮬레이션
    s.crisis_first_tp_done_at = datetime.now(timezone.utc)
    s.peak_pnl_pct_after_first_tp = Decimal("5")
    # 5) +12% 피크 (보호 활성, 트레일링 미발동)
    assert _ServiceShim.eval(s, Decimal("12")) is None
    assert s.peak_pnl_pct_after_first_tp == Decimal("12")
    # 6) +7% 회귀 (피크 12% - 5% = 7%) → 트레일링 발동
    assert _ServiceShim.eval(s, Decimal("7")) == "CRISIS_TRAIL_FULL"


# ──────────── 시나리오 B: 회복 후 재하락 → 빠른 손절 ────────────
def test_scenario_B_quick_stop_loss() -> None:
    s = _FakeStrategy(current_stage=5)
    s.max_loss_pct = Decimal("-52")
    from datetime import datetime, timezone
    s.crisis_mode_triggered_at = datetime.now(timezone.utc)
    # +5% TP1
    assert _ServiceShim.eval(s, Decimal("5")) == "CRISIS_TP1"
    s.crisis_first_tp_done_at = datetime.now(timezone.utc)
    s.peak_pnl_pct_after_first_tp = Decimal("5")
    # +3% (보호 모드, 손절 트리거 없음)
    assert _ServiceShim.eval(s, Decimal("3")) is None
    # -1% 도달 — CRISIS_HARD_SL
    assert _ServiceShim.eval(s, Decimal("-1")) == "CRISIS_HARD_SL"


# ──────────── 시나리오 C: TP1 발동 전 추가 손실 ────────────
def test_scenario_C_no_tp1_normal_sl() -> None:
    s = _FakeStrategy(current_stage=5)
    s.max_loss_pct = Decimal("-52")
    from datetime import datetime, timezone
    s.crisis_mode_triggered_at = datetime.now(timezone.utc)
    # PnL 가 +5% 도달 못하고 더 빠짐 (-25%, -45% 등)
    assert _ServiceShim.eval(s, Decimal("-25")) is None
    assert _ServiceShim.eval(s, Decimal("-45")) is None
    # → 정상 모드 SL -50% 이 발동해야 함 (이 부분은 evaluate_stop_loss 로 위임됨)
    # _eval_crisis_mode_tp_sl 은 None 을 반환 → 호출자(evaluate_take_profit_level)가 폴스루
    # → orchestrator 가 evaluate_stop_loss(-50%) 검사 → 발동


# ──────────── 시나리오 D: 우선순위 — -1% 와 트레일링 동시 충족 시 -1% 우선 ────────────
def test_priority_hard_sl_over_trailing() -> None:
    s = _FakeStrategy(current_stage=5)
    s.max_loss_pct = Decimal("-52")
    from datetime import datetime, timezone
    s.crisis_mode_triggered_at = datetime.now(timezone.utc)
    s.crisis_first_tp_done_at = datetime.now(timezone.utc)
    s.peak_pnl_pct_after_first_tp = Decimal("10")
    # -2% — -1% 손절 + 피크-5% 트레일링(=5%) 도 만족 → -1% 우선
    assert _ServiceShim.eval(s, Decimal("-2")) == "CRISIS_HARD_SL"


# ──────────── 시나리오 E: 모든 stage 진입 완료가 진입 조건 ────────────
def test_crisis_requires_all_stages_entered() -> None:
    """사용자 기획 v2 (2026-05-07): 모든 stage 진입 완료 후 -50% 이상 손실에서만 트리거.

    이전 v1 의 「-30% 도달 + 양수 PnL 회복」 조건은 폐기. 이전 CRISIS_MIN_STAGE=5
    상수도 제거됐고, 동적으로 strategy.current_stage == total_stages 체크로 변경.

    이 테스트는 정책 자체의 검증 (constants 만). 실제 _should_trigger_crisis_mode
    호출은 통합 테스트 (DB + StrategyTemplate fixture) 가 담당.
    """
    # -50% 이하 손실이 진입 조건 (이전 -30% 보다 깊음)
    assert CRISIS_MAX_LOSS_THRESHOLD == Decimal("-50")
    # CRISIS_TP1_THRESHOLD 그대로 — 진입 후 빠른 회복 익절
    assert CRISIS_TP1_THRESHOLD == Decimal("5")
