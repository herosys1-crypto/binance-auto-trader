"""reconcile_worker — 옵션 C 5+ 단계 strategy 자가 회복 통합.

배경: 2026-05-04 fix 이전엔 reconcile_worker 의 active 필터 + _PENDING_TO_OPEN
모두 1~4 단계 hardcoded → 5+ 단계 strategy 가 main loop 에서 누락 또는
PENDING 에서 OPEN 으로 자가 회복 못함. 이 테스트는 STAGE5_OPEN_PENDING /
STAGE6_OPEN 등이 정상 처리되는지 보장.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from app.workers.reconcile_worker import _do_reconcile


class TestReconcile5PlusStages:
    @pytest.mark.parametrize("stage_no", [5, 6, 7, 8, 9, 10])
    def test_stage_n_pending_recovers_to_open(
        self,
        stage_no: int,
        db_session,
        make_strategy,
        fake_binance,
        identity_decrypt,
        patched_sessionlocal,
    ) -> None:
        """STAGE5~10_OPEN_PENDING + stage_plan.is_triggered=True → STAGE{N}_OPEN 자가 회복.

        2026-05-04 v2: stage_plan 이 triggered 인 경우만 promote (stream race window).
        plan 미triggered 면 LIMIT 거래소 book 대기로 보고 promote 안 함.
        """
        from app.models.strategy_stage_plan import StrategyStagePlan
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT",
            status=f"STAGE{stage_no}_OPEN_PENDING",
            current_position_qty=Decimal("0"),
            current_stage=stage_no,
        )
        # plan 미리 생성 — triggered=True 로 stream FILLED 처리됨 가정
        db_session.add(StrategyStagePlan(
            strategy_instance_id=strategy.id, stage_no=stage_no, side="SHORT",
            trigger_mode="PRICE_UP_PCT", trigger_percent=Decimal("20"),
            trigger_price=Decimal("48000"), planned_capital=Decimal("100"),
            planned_qty=Decimal("0.4"), is_triggered=True,
        ))
        db_session.commit()
        fake_binance.set_position(
            "BTCUSDT", position_amt="-0.4", entry_price="48000",
            mark_price="48000", position_side="SHORT",
        )

        _do_reconcile(identity_decrypt)

        db_session.expire_all()
        s = db_session.get(StrategyInstance, strategy.id)
        assert s.status == f"STAGE{stage_no}_OPEN", (
            f"STAGE{stage_no}_OPEN_PENDING 가 plan triggered + 거래소 매칭 시 STAGE{stage_no}_OPEN 으로 자가 회복돼야 함"
        )
        assert s.current_position_qty == Decimal("-0.4")

        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "RECONCILE_RECOVERED_PENDING")
        ).scalars().all()
        assert len(events) == 1

    @pytest.mark.parametrize("stage_no", [5, 6, 7, 8, 9, 10])
    def test_stage_n_open_orphan_marked_stopped(
        self,
        stage_no: int,
        db_session,
        make_strategy,
        fake_binance,
        identity_decrypt,
        patched_sessionlocal,
    ) -> None:
        """STAGE5~10_OPEN + 거래소 매칭 없음 (외부 청산) → STOPPED + WARN."""
        strategy = make_strategy(
            symbol_str="ETHUSDT", side="LONG",
            status=f"STAGE{stage_no}_OPEN",
            current_position_qty=Decimal("1.5"),
            current_stage=stage_no,
        )
        # set_position 안 호출 → matched=None → orphan 분기

        _do_reconcile(identity_decrypt)

        db_session.expire_all()
        s = db_session.get(StrategyInstance, strategy.id)
        assert s.status == "STOPPED", (
            f"STAGE{stage_no}_OPEN orphan 도 STOPPED 자동 정리돼야 함 "
            f"(이전엔 1~4 hardcoded 라 5+ 누락)"
        )
        assert s.current_position_qty == Decimal("0")

    def test_stage6_strategy_in_active_loop_syncs_qty(
        self,
        db_session,
        make_strategy,
        fake_binance,
        identity_decrypt,
        patched_sessionlocal,
    ) -> None:
        """STAGE6_OPEN strategy 가 main loop 에서 정상 처리 (qty/price sync)."""
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT",
            status="STAGE6_OPEN",
            current_position_qty=Decimal("-0.7"),
            avg_entry_price=Decimal("48000"),
            current_stage=6,
        )
        fake_binance.set_position(
            "BTCUSDT", position_amt="-0.7",
            entry_price="48000", mark_price="47500",
            unrealized_pnl="3.5", position_side="SHORT",
        )

        _do_reconcile(identity_decrypt)

        db_session.expire_all()
        s = db_session.get(StrategyInstance, strategy.id)
        # main loop 에서 처리 → unrealized 갱신, status 그대로
        assert s.status == "STAGE6_OPEN"
        assert s.unrealized_pnl == Decimal("3.5")
