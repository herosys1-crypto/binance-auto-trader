"""TP 중간 단계 skip 회귀 (사용자 #98 LABUSDT 사례 2026-05-04).

배경 (사용자 보고):
- Template: TP1=10/TP2=15/TP3=20/TP4=25/TP5=30 (leveraged ROI %)
- peak max_profit_pct = 22.72% → TP1/TP2/TP3 임계 도달, TP4/TP5 미도달
- 알림 이력: TP1 ✓ → TP2 ✗ → TP3 ✓
- status: TP3_DONE_PARTIAL (TP2 silently skipped)
- 결과: TP1 25% + TP3 25% 청산 = 50% (TP2 의 25% bite 누락)

근본 원인:
risk_service.evaluate_take_profit_level 의 TP loop:
  for label, threshold in tp_levels:  # descending sort (TP5 first)
      if pnl_ratio >= threshold:
          return label  # 가장 높은 도달 TP 즉시 반환

한 tick 에 여러 TP 임계 도달 시 (예: pnl 22% 인데 TP1=10/TP2=15/TP3=20 모두 통과):
- descending: TP3 먼저 매치 → "TP3" 반환
- orchestrator: tp_level_idx=2, cur_done_idx=0 (TP1_PARTIAL) → 2 > 0 → fire TP3
- TP2 silently skipped — 그 단계 청산 비율 영구 누락

Fix:
- TP loop ascending (TP1 → TP5 정렬) + 다음 미발동 TP 만 반환
- 한 tick 에 1개씩 순차 발동 (10초 사이클 × N = 점진적이지만 정확)

이 테스트는 ascending + skip-prevention 동작 보장.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.position import Position
from app.services.risk_service import RiskService


@pytest.fixture
def patched_redis_for_risk(monkeypatch):
    class _FakeRedis:
        def __init__(self):
            self.store: dict[str, str] = {}
        def get(self, key):
            return self.store.get(key)
        def set(self, key, value, ex=None):
            self.store[key] = str(value)
            return True
        def delete(self, key):
            return 1 if self.store.pop(key, None) is not None else 0
    fr = _FakeRedis()
    monkeypatch.setattr("app.services.risk_service.get_redis_client", lambda: fr)
    return fr


@pytest.fixture
def make_position_at_mark(db_session):
    def _factory(strategy, mark_price):
        p = Position(
            strategy_instance_id=strategy.id,
            symbol=strategy.symbol, side=strategy.side, position_side=strategy.side,
            entry_price=strategy.avg_entry_price,
            mark_price=Decimal(str(mark_price)),
            position_amt=strategy.current_position_qty,
            source="TEST",
        )
        db_session.add(p)
        db_session.commit()
        db_session.refresh(p)
        return p
    return _factory


# ============================================================================
# #98 시나리오: TP1 발동 후 가격 급등으로 TP2/TP3 임계 동시 통과
# ============================================================================
class TestTPIntermediateSkipFix:
    def test_returns_tp2_not_tp3_when_status_is_tp1_partial(
        self,
        db_session,
        make_template,
        make_strategy,
        make_position_at_mark,
        patched_redis_for_risk,
    ) -> None:
        """status=TP1_PARTIAL 에서 pnl 22% (TP2 15% + TP3 20% 도달) → "TP2" 반환.

        이전 버그: descending loop → "TP3" 반환 → TP2 skip.
        """
        tpl = make_template(
            tp1_percent=Decimal("10"), tp2_percent=Decimal("15"),
            tp3_percent=Decimal("20"), tp4_percent=Decimal("25"),
            tp5_percent=Decimal("30"),
        )
        # SHORT @ 2.37, mark 2.114 → raw 10.7% × leverage 2 = 21.4% leveraged
        strategy = make_strategy(
            symbol_str="LABUSDT", side="SHORT", status="TP1_DONE_PARTIAL",
            current_position_qty=Decimal("-476.4"),
            avg_entry_price=Decimal("2.37"),
            leverage=2,
            template=tpl, current_stage=1,
        )
        make_position_at_mark(strategy, Decimal("2.116"))  # ~21% leveraged

        result = RiskService(db_session).evaluate_take_profit_level(strategy.id)
        assert result == "TP2", (
            f"TP1 done 후 pnl 21% (TP2 15% + TP3 20% 도달) → 다음 미발동인 TP2 발동되어야. "
            f"실제: {result} (이전 버그: descending → TP3 즉시 반환 → TP2 skip)"
        )

    def test_returns_tp3_when_status_is_tp2_partial(
        self,
        db_session,
        make_template,
        make_strategy,
        make_position_at_mark,
        patched_redis_for_risk,
    ) -> None:
        """다음 tick: status=TP2_PARTIAL → TP3 발동."""
        tpl = make_template(
            tp1_percent=Decimal("10"), tp2_percent=Decimal("15"),
            tp3_percent=Decimal("20"), tp4_percent=Decimal("25"),
            tp5_percent=Decimal("30"),
        )
        strategy = make_strategy(
            symbol_str="LABUSDT", side="SHORT", status="TP2_DONE_PARTIAL",
            current_position_qty=Decimal("-300"),
            avg_entry_price=Decimal("2.37"),
            leverage=2,
            template=tpl, current_stage=1,
        )
        make_position_at_mark(strategy, Decimal("2.116"))  # ~21% leveraged

        result = RiskService(db_session).evaluate_take_profit_level(strategy.id)
        assert result == "TP3"

    def test_returns_none_when_no_more_tp_reachable(
        self,
        db_session,
        make_template,
        make_strategy,
        make_position_at_mark,
        patched_redis_for_risk,
    ) -> None:
        """status=TP3_PARTIAL, pnl 21% (TP4 25%, TP5 30% 미도달) → None."""
        tpl = make_template(
            tp1_percent=Decimal("10"), tp2_percent=Decimal("15"),
            tp3_percent=Decimal("20"), tp4_percent=Decimal("25"),
            tp5_percent=Decimal("30"),
        )
        strategy = make_strategy(
            symbol_str="LABUSDT", side="SHORT", status="TP3_DONE_PARTIAL",
            current_position_qty=Decimal("-200"),
            avg_entry_price=Decimal("2.37"),
            leverage=2,
            template=tpl, current_stage=1,
        )
        make_position_at_mark(strategy, Decimal("2.116"))  # ~21%
        # peak 미설정 — trailing 발동 안 함
        # peak 없으면 _update_peak_pnl 가 21% 로 갱신 → trailing 조건 미충족

        result = RiskService(db_session).evaluate_take_profit_level(strategy.id)
        assert result is None  # 더 이상 발동할 TP 없음

    def test_first_call_returns_tp1_not_higher(
        self,
        db_session,
        make_template,
        make_strategy,
        make_position_at_mark,
        patched_redis_for_risk,
    ) -> None:
        """첫 호출 (status STAGE2_OPEN) + pnl 22% (모든 TP 도달) → TP1 발동.

        이전 버그: descending → TP5 반환 → TP1 skip!
        """
        tpl = make_template(
            tp1_percent=Decimal("10"), tp2_percent=Decimal("15"),
            tp3_percent=Decimal("20"), tp4_percent=Decimal("25"),
            tp5_percent=Decimal("30"),
        )
        strategy = make_strategy(
            symbol_str="LABUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-500"),
            avg_entry_price=Decimal("2.37"),
            leverage=2,
            template=tpl, current_stage=2,
        )
        make_position_at_mark(strategy, Decimal("2.116"))  # ~21%

        result = RiskService(db_session).evaluate_take_profit_level(strategy.id)
        assert result == "TP1", f"첫 TP 는 무조건 TP1 부터. 실제: {result}"


# ============================================================================
# 회귀 — 기존 동작 보존
# ============================================================================
class TestExistingTPBehaviorPreserved:
    def test_only_tp1_threshold_reached_returns_tp1(
        self,
        db_session,
        make_template,
        make_strategy,
        make_position_at_mark,
        patched_redis_for_risk,
    ) -> None:
        tpl = make_template(
            tp1_percent=Decimal("5"), tp2_percent=Decimal("10"),
            tp3_percent=Decimal("15"),
        )
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
            avg_entry_price=Decimal("50000"),
            leverage=1, template=tpl, current_stage=2,
        )
        # mark 47500 → raw 5% × lev 1 = 5% leveraged → only TP1 reached
        make_position_at_mark(strategy, Decimal("47500"))
        result = RiskService(db_session).evaluate_take_profit_level(strategy.id)
        assert result == "TP1"

    def test_no_threshold_reached_returns_none(
        self,
        db_session,
        make_template,
        make_strategy,
        make_position_at_mark,
        patched_redis_for_risk,
    ) -> None:
        tpl = make_template(tp1_percent=Decimal("10"))
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
            avg_entry_price=Decimal("50000"),
            leverage=1, template=tpl, current_stage=2,
        )
        make_position_at_mark(strategy, Decimal("49000"))  # 2% only
        result = RiskService(db_session).evaluate_take_profit_level(strategy.id)
        assert result is None

    def test_no_position_returns_none(
        self,
        db_session,
        make_template,
        make_strategy,
        patched_redis_for_risk,
    ) -> None:
        tpl = make_template()
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="WAITING",
            current_position_qty=Decimal("0"),
            avg_entry_price=None,
            template=tpl,
        )
        # No position — evaluate returns None gracefully
        result = RiskService(db_session).evaluate_take_profit_level(strategy.id)
        assert result is None


# ============================================================================
# 사용자 #40 BUSDT 보고 (2026-05-14 evening) — 3 exits 보장 시뮬레이션
# ============================================================================
class TestUser40Busdt3ExitsGuaranteed:
    """사용자 #40 BUSDT 보고: stage 2 진입 + 빠른 가격 변동 시 EXIT 가 2건만 발생.
    예상: TP1 (25%) + TP2 (25%) + TP3 v7 (100%) = 3건.
    실제 (구 코드): TP1 (25%) + TP3 v7 (100%) = 2건 (TP2 skip).

    원인 추정: v2 fix (2026-05-04, 사용자 #98 LABUSDT 사례) 이전 production code.
    descending loop 였을 때 한 tick 에 TP2/TP3 모두 도달 시 TP3 즉시 반환 → TP2 skip.

    이 테스트는 현재 code 가 #40 같은 시나리오에서 절대 TP2 skip 안 하는지 검증.
    3 exit 시퀀스 시뮬레이션:
      1. status=ACTIVE → pnl 22% (TP1+TP2+TP3 모두 임계 초과) → TP1 반환 (가장 낮은 미발동)
      2. status=TP1_DONE_PARTIAL → pnl 22% 유지 → TP2 반환 (skip 안 됨!)
      3. status=TP2_DONE_PARTIAL → pnl 22% 유지 → TP3 반환 (orchestrator 가 v7 100% 처리)
    """

    def test_first_call_at_status_active_returns_tp1(
        self,
        db_session,
        make_template,
        make_strategy,
        make_position_at_mark,
        patched_redis_for_risk,
    ) -> None:
        """1번째 tick: status=ACTIVE 또는 STAGE2_OPEN, pnl 큰 폭 → TP1 반환 (가장 낮은 미발동)."""
        tpl = make_template(
            tp1_percent=Decimal("10"), tp2_percent=Decimal("15"), tp3_percent=Decimal("20"),
        )
        strategy = make_strategy(
            symbol_str="BUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-76"),
            avg_entry_price=Decimal("0.65"),
            leverage=1,
            template=tpl, current_stage=2,
        )
        # SHORT @ 0.65, mark 0.5135 → +21% raw → 21% leveraged (모든 TP 임계 초과)
        make_position_at_mark(strategy, Decimal("0.5135"))

        result = RiskService(db_session).evaluate_take_profit_level(strategy.id)
        assert result == "TP1", (
            f"#40 시나리오 1번째 tick — TP1 발동 기대 (가장 낮은 미발동). 실제: {result}\n"
            f"이전 버그 (v2 fix 이전): descending → TP3 즉시 반환 → TP1/TP2 skip"
        )

    def test_second_call_at_tp1_partial_returns_tp2_not_tp3(
        self,
        db_session,
        make_template,
        make_strategy,
        make_position_at_mark,
        patched_redis_for_risk,
    ) -> None:
        """2번째 tick: status=TP1_DONE_PARTIAL, pnl 여전히 큼 → TP2 (NOT TP3) 반환.

        #40 BUSDT 의 핵심 회귀: 이 단계에서 TP3 반환 = TP2 skip = 2 exits 만 발생.
        v2 fix 후엔 무조건 TP2 반환 → 다음 tick 에 TP3 → 총 3 exits.
        """
        tpl = make_template(
            tp1_percent=Decimal("10"), tp2_percent=Decimal("15"), tp3_percent=Decimal("20"),
        )
        strategy = make_strategy(
            symbol_str="BUSDT", side="SHORT", status="TP1_DONE_PARTIAL",
            current_position_qty=Decimal("-57"),  # 76 - 19 (TP1 25%)
            avg_entry_price=Decimal("0.65"),
            leverage=1,
            template=tpl, current_stage=2,
        )
        make_position_at_mark(strategy, Decimal("0.5135"))  # +21%

        result = RiskService(db_session).evaluate_take_profit_level(strategy.id)
        assert result == "TP2", (
            f"#40 BUSDT 핵심 회귀 — TP1_PARTIAL 상태에서 pnl 21% (TP3 임계 초과) 라도 "
            f"다음 미발동인 TP2 만 반환해야. 실제: {result}\n"
            f"TP3 반환 시 TP2 skip = 사용자 #40 BUSDT 의 2-exits 버그 재발."
        )

    def test_third_call_at_tp2_partial_returns_tp3_for_v7(
        self,
        db_session,
        make_template,
        make_strategy,
        make_position_at_mark,
        patched_redis_for_risk,
    ) -> None:
        """3번째 tick: status=TP2_DONE_PARTIAL → TP3 반환.

        orchestrator._execute_take_profit('TP3') 가 v7_short_exit 분기로 100% 청산.
        (test_v7_short_exit_partial_stage 가 orchestrator 단 검증)
        """
        tpl = make_template(
            tp1_percent=Decimal("10"), tp2_percent=Decimal("15"), tp3_percent=Decimal("20"),
        )
        strategy = make_strategy(
            symbol_str="BUSDT", side="SHORT", status="TP2_DONE_PARTIAL",
            current_position_qty=Decimal("-43"),  # 57 - 14 (TP2 25%)
            avg_entry_price=Decimal("0.65"),
            leverage=1,
            template=tpl, current_stage=2,
        )
        make_position_at_mark(strategy, Decimal("0.5135"))  # +21%

        result = RiskService(db_session).evaluate_take_profit_level(strategy.id)
        assert result == "TP3", (
            f"3번째 tick — TP3 반환 기대 (orchestrator 가 v7 으로 잔량 100% 청산). 실제: {result}"
        )
