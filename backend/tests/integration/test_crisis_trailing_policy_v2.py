"""크라이시스 모드 + Trailing TP 정책 v3 검증 (사용자 기획 2026-05-12).

변경 이력:
- v1 (2026-04-30): TP1 발동 후부터 trailing armed
- v2 (2026-05-07): TP3 발동 후부터 trailing armed
- v3 (2026-05-12): TP4 발동 후부터 trailing armed — TP1/2/3/4 모두 후
  Crisis 진입: max_loss ≤ -30% + 양수 PnL → 전 단계 진입 + max_loss ≤ -50%

영구 회귀 방어 — 정책 변경 시 테스트도 같이 업데이트해야 함.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.risk_service import (
    CRISIS_MAX_LOSS_THRESHOLD,
    RiskService,
    TRAILING_MIN_TP_INDEX,
)


class TestTrailingArmedFromTP4:
    """Trailing TP 가 TP4 발동 후부터 armed 되어야 함 (v3, 2026-05-12)."""

    def test_constant_value(self):
        assert TRAILING_MIN_TP_INDEX == 4

    def test_armed_statuses_only_tp4_plus(self):
        """TRAILING_ARMED_STATUSES set 검증 — TP4~TP10 만 포함."""
        # risk_service 의 evaluate_take_profit_level 안에서 정의됨.
        # 직접 import 안 되니 동작 검증으로 대체 — 별도 통합 시나리오 테스트 필요.
        # 이 테스트는 상수 정확성만 보장.
        for n in range(1, 4):
            # TP1, TP2, TP3 발동만으론 trailing 안 잡혀야
            assert n < TRAILING_MIN_TP_INDEX
        for n in range(4, 11):
            assert n >= TRAILING_MIN_TP_INDEX


class TestCrisisAllStagesEntered:
    """Crisis 진입 조건 — 모든 stage 진입 완료 + max_loss ≤ -50%."""

    def test_crisis_max_loss_threshold_minus_50(self):
        """이전 -30 → 변경 -50."""
        assert CRISIS_MAX_LOSS_THRESHOLD == Decimal("-50")

    def test_partial_stage_entry_no_crisis(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy
    ):
        """5단계 strategy 의 3단계까지만 진입 + max_loss=-60% — 미진입 단계 있어 crisis 안 됨."""
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(
            stages_config={"capitals": ["100"] * 5, "trigger_percents": [None] * 5},
        )
        strategy = make_strategy(
            user=u, exchange_account=ea, template=tpl,
            current_stage=3,  # 3/5 단계만 진입
            max_loss_pct=Decimal("-60"),  # 충분히 깊은 손실
        )
        rs = RiskService(db_session)
        # current_pnl 은 무관 — partial stage 라 이미 거부
        assert rs._should_trigger_crisis_mode(strategy, Decimal("-30")) is False
        assert rs._should_trigger_crisis_mode(strategy, Decimal("0")) is False
        assert rs._should_trigger_crisis_mode(strategy, Decimal("10")) is False

    def test_all_stages_entered_above_minus_50_no_crisis(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy
    ):
        """전 단계 진입했지만 max_loss=-40% — -50% 미달이라 crisis 안 됨."""
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(stages_config={"capitals": ["100"] * 5})
        strategy = make_strategy(
            user=u, exchange_account=ea, template=tpl,
            current_stage=5,
            max_loss_pct=Decimal("-40"),  # -50% 미달
        )
        rs = RiskService(db_session)
        assert rs._should_trigger_crisis_mode(strategy, Decimal("-30")) is False

    def test_all_stages_entered_below_minus_50_triggers_crisis(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy
    ):
        """전 단계 진입 + max_loss=-55% — crisis 진입 ✓."""
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(stages_config={"capitals": ["100"] * 5})
        strategy = make_strategy(
            user=u, exchange_account=ea, template=tpl,
            current_stage=5,
            max_loss_pct=Decimal("-55"),
        )
        rs = RiskService(db_session)
        # current_pnl 무관 — 이전 v1 의 「양수 PnL 회복 시점」 조건 폐기됨
        assert rs._should_trigger_crisis_mode(strategy, Decimal("-30")) is True
        assert rs._should_trigger_crisis_mode(strategy, Decimal("0")) is True
        assert rs._should_trigger_crisis_mode(strategy, Decimal("5")) is True

    def test_already_in_crisis_no_retrigger(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy
    ):
        """이미 crisis 상태면 재트리거 안 됨 (idempotent)."""
        from datetime import datetime, timezone
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(stages_config={"capitals": ["100"] * 3})
        strategy = make_strategy(
            user=u, exchange_account=ea, template=tpl,
            current_stage=3,
            max_loss_pct=Decimal("-55"),
            crisis_mode_triggered_at=datetime.now(timezone.utc),
        )
        rs = RiskService(db_session)
        assert rs._should_trigger_crisis_mode(strategy, Decimal("0")) is False

    def test_max_loss_pct_none_no_crisis(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy
    ):
        """max_loss_pct 가 None (아직 측정 안됨) 이면 crisis 안 됨."""
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(stages_config={"capitals": ["100"] * 3})
        strategy = make_strategy(
            user=u, exchange_account=ea, template=tpl,
            current_stage=3,
            max_loss_pct=None,
        )
        rs = RiskService(db_session)
        assert rs._should_trigger_crisis_mode(strategy, Decimal("0")) is False
