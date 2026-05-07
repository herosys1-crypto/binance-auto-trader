"""트레일링 TP 우선순위 회귀 (사용자 #98 LABUSDT 사례 2026-05-04).

배경 (사용자 보고):
- 전략 #98 TP3_DONE_PARTIAL 상태
- 가격이 peak 대비 10%+ 하락했는데 트레일링 전량 청산 안 됨
- 잔량 그대로 보유 중

근본 원인:
risk_service.evaluate_take_profit_level 의 로직 흐름:
  1. peak 갱신
  2. TP threshold loop (descending) — pnl >= threshold 면 즉시 return label
  3. 트레일링 체크 (loop 다음)

문제: pnl_ratio 가 TP threshold 이상이면 (e.g. 19.76% >= TP3 15%) loop 가
"TP3" 를 즉시 반환. orchestrator 는 status 가 이미 TP3_DONE_PARTIAL 이라
재실행 skip. 트레일링 체크에 도달 안 함.

→ 한번 익절 후 가격이 약간 retrace 됐지만 여전히 직전 TP threshold 위에
있는 모든 케이스에서 트레일링 무력화.

Fix: 트레일링 체크를 TP loop 앞으로 이동.
사용자 의도: "이미 익절 진행 중이고 5%+ retrace 면 전량 청산" — TP partial
보다 우선순위 높음.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.position import Position
from app.services.risk_service import (
    TRAILING_TP_PEAK_THRESHOLD,
    TRAILING_TP_RETRACE_AMOUNT,
    RiskService,
)


@pytest.fixture
def patched_redis_for_risk(monkeypatch):
    """risk_service 가 import 한 get_redis_client 를 in-memory store 로 교체."""

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
def make_position_with_mark(db_session):
    def _factory(strategy, mark_price: Decimal | str | int | float) -> Position:
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
# 사용자 #98 시나리오 — 회귀 방어
# ============================================================================
class TestTrailingFiresWhenAboveTPThreshold:
    """현재 pnl 이 직전 TP threshold 위에 있어도 peak 대비 5%+ 회귀하면 트레일링."""

    def test_98_LABUSDT_scenario_trailing_fires_at_peak_retrace(
        self,
        db_session,
        make_template,
        make_strategy,
        make_position_with_mark,
        patched_redis_for_risk,
    ) -> None:
        """SHORT, TP1=5/TP2=10/TP3=15. status=TP3_DONE_PARTIAL.
        Peak 30%, 현재 19.76% (drop 10.24%) → 트레일링 발동 기대."""
        tpl = make_template(
            tp1_percent=Decimal("5"), tp2_percent=Decimal("10"),
            tp3_percent=Decimal("15"),
            tp1_qty_ratio=Decimal("25"), tp2_qty_ratio=Decimal("50"), tp3_qty_ratio=Decimal("100"),
        )
        # SHORT @ entry 2.37, current 2.13 — leveraged ROI 매핑 위해
        # leverage=2 가정: raw -10.13% × 2 = leveraged ROI ~+20.25% (SHORT side flips sign)
        # 실제 계산: (avg-mark)/avg * 100 = (2.37-2.13)/2.37 * 100 = 10.13% raw
        # × leverage 2 = 20.25% leveraged ROI (사용자 화면 19.76% 와 비슷)
        strategy = make_strategy(
            symbol_str="LABUSDT", side="SHORT", status="TP3_DONE_PARTIAL",
            current_position_qty=Decimal("-476.4"),
            avg_entry_price=Decimal("2.37"),
            leverage=2,
            template=tpl,
            current_stage=1,
        )
        # mark 2.13 → leveraged pnl_ratio ≈ 20.25%
        make_position_with_mark(strategy, Decimal("2.13"))
        # Peak 미리 30% 로 설정 (이전 사이클에 도달한 최고치 시뮬)
        patched_redis_for_risk.store[f"strategy:{strategy.id}:peak_pnl_pct"] = "30"

        result = RiskService(db_session).evaluate_take_profit_level(strategy.id)

        assert result == "TRAILING_TP", (
            f"트레일링 발동 기대: peak=30%, 현재 ~20%, drop ~10% (>5% 임계). "
            f"현재 status TP3_DONE_PARTIAL — 활성 trailing armed status. "
            f"실제 결과: {result} (이전 버그: TP loop 가 'TP3' 조기 반환해 트레일링 무력화)"
        )

    @pytest.mark.parametrize("done_status", [
        "TP3_DONE_PARTIAL", "TP4_DONE_PARTIAL",
    ])
    def test_trailing_fires_for_tp3_plus_done_partials(
        self,
        done_status: str,
        db_session,
        make_template,
        make_strategy,
        make_position_with_mark,
        patched_redis_for_risk,
    ) -> None:
        """TP3+ partial 에서만 trailing 발동 (사용자 기획 v2, 2026-05-07).
        TP1/TP2 는 trailing armed 안 됨 — 별도 테스트에서 검증."""
        tpl = make_template(
            tp1_percent=Decimal("5"), tp2_percent=Decimal("10"),
            tp3_percent=Decimal("15"), tp4_percent=Decimal("25"),
        )
        strategy = make_strategy(
            symbol_str="LABUSDT", side="SHORT", status=done_status,
            current_position_qty=Decimal("-100"),
            avg_entry_price=Decimal("2.37"),
            leverage=2,
            template=tpl, current_stage=1,
        )
        make_position_with_mark(strategy, Decimal("2.13"))
        patched_redis_for_risk.store[f"strategy:{strategy.id}:peak_pnl_pct"] = "30"

        result = RiskService(db_session).evaluate_take_profit_level(strategy.id)
        assert result == "TRAILING_TP", f"{done_status}: 트레일링 안 됨 (결과={result})"

    @pytest.mark.parametrize("done_status", ["TP1_DONE_PARTIAL", "TP2_DONE_PARTIAL"])
    def test_trailing_NOT_armed_for_tp1_tp2_done_partials(
        self,
        done_status: str,
        db_session,
        make_template,
        make_strategy,
        make_position_with_mark,
        patched_redis_for_risk,
    ) -> None:
        """TP1/TP2 발동만으로는 trailing 활성 X (사용자 기획 v2, 2026-05-07).

        같은 시나리오 (peak 30%, 현재 20%) 라도 status TP1/TP2 면 trailing 미발동.
        대신 TP threshold loop 가 다음 미발동 TP 를 반환해야 함.
        """
        tpl = make_template(
            tp1_percent=Decimal("5"), tp2_percent=Decimal("10"),
            tp3_percent=Decimal("15"), tp4_percent=Decimal("25"),
        )
        strategy = make_strategy(
            symbol_str="LABUSDT", side="SHORT", status=done_status,
            current_position_qty=Decimal("-100"),
            avg_entry_price=Decimal("2.37"),
            leverage=2,
            template=tpl, current_stage=1,
        )
        make_position_with_mark(strategy, Decimal("2.13"))
        patched_redis_for_risk.store[f"strategy:{strategy.id}:peak_pnl_pct"] = "30"

        result = RiskService(db_session).evaluate_take_profit_level(strategy.id)
        # peak 30%/현재 20% — trailing 조건은 만족하지만 status TP1/TP2 라 armed X.
        # 대신 다음 미발동 TP (TP1 status → TP2, TP2 status → TP3) 반환.
        assert result != "TRAILING_TP", f"{done_status}: trailing 발동되면 안 됨 (정책 v2)"


# ============================================================================
# 회귀 — 트레일링 조건 미달 시 일반 TP 정상 반환
# ============================================================================
class TestTrailingDoesNotShortcutTPLogic:
    def test_no_peak_no_trailing_returns_tp_label(
        self,
        db_session,
        make_template,
        make_strategy,
        make_position_with_mark,
        patched_redis_for_risk,
    ) -> None:
        """첫 TP1 도달 — peak 없거나 작음 → 트레일링 미발동, TP1 반환."""
        tpl = make_template(
            tp1_percent=Decimal("5"), tp2_percent=Decimal("10"),
            tp3_percent=Decimal("15"),
        )
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
            avg_entry_price=Decimal("50000"),
            leverage=1,
            template=tpl, current_stage=2,
        )
        # mark 47500 → SHORT 5% raw × leverage 1 = 5% leveraged
        make_position_with_mark(strategy, Decimal("47500"))
        # Redis 비움 — _update_peak_pnl 가 자체 갱신

        result = RiskService(db_session).evaluate_take_profit_level(strategy.id)
        assert result == "TP1"

    def test_status_not_in_armed_set_no_trailing(
        self,
        db_session,
        make_template,
        make_strategy,
        make_position_with_mark,
        patched_redis_for_risk,
    ) -> None:
        """status 가 STAGE2_OPEN (TP 미발동) 면 trailing armed 상태 아님 → 미발동."""
        tpl = make_template(
            tp1_percent=Decimal("5"), tp2_percent=Decimal("10"),
            tp3_percent=Decimal("15"),
        )
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
            avg_entry_price=Decimal("50000"),
            leverage=1,
            template=tpl, current_stage=2,
        )
        make_position_with_mark(strategy, Decimal("47500"))
        # Peak 30% 라도 trailing armed 상태 아니라 그냥 TP1 반환
        patched_redis_for_risk.store[f"strategy:{strategy.id}:peak_pnl_pct"] = "30"

        result = RiskService(db_session).evaluate_take_profit_level(strategy.id)
        assert result == "TP1"  # trailing 무시하고 TP1 (현재 pnl >= TP1 threshold)

    def test_drop_less_than_5pct_no_trailing(
        self,
        db_session,
        make_template,
        make_strategy,
        make_position_with_mark,
        patched_redis_for_risk,
    ) -> None:
        """peak 대비 4% 만 drop → 임계 5% 미달 → 트레일링 안 함."""
        tpl = make_template(
            tp1_percent=Decimal("5"), tp2_percent=Decimal("10"),
            tp3_percent=Decimal("15"),
        )
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="TP1_DONE_PARTIAL",
            current_position_qty=Decimal("-0.5"),
            avg_entry_price=Decimal("50000"),
            leverage=1,
            template=tpl, current_stage=2,
        )
        # mark 47000 → 6% leveraged
        make_position_with_mark(strategy, Decimal("47000"))
        # Peak 10% (drop 4%, < 5% 임계)
        patched_redis_for_risk.store[f"strategy:{strategy.id}:peak_pnl_pct"] = "10"

        result = RiskService(db_session).evaluate_take_profit_level(strategy.id)
        # 2026-05-04 v2 기준 (TP skip fix 후):
        # - 트레일링: drop 4% < 임계 5% → 미발동
        # - TP loop: status=TP1_PARTIAL → cur_done_idx=0 → TP1 재발동 안 함 (idx 0 > 0 false).
        #   pnl 6% < TP2 (10%) → TP2 도 미발동.
        # → None 반환 (정확한 동작 — 발동할 TP 없음)
        assert result is None
