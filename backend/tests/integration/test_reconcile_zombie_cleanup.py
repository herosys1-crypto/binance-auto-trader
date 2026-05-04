"""reconcile_worker — 좀비 자동 정리 통합 시나리오.

unit test 가 zombie_guardian 함수 단위 동작을 보장하지만,
이 통합 테스트는 reconcile_worker._do_reconcile 가 실제 DB 와 Binance mock
사이에서 올바르게 wiring 되어 있는지 (status 전이, qty=0, RiskEvent 기록,
commit 까지) 한 번에 검증한다.

시나리오:
  - STOPPING 좀비       : DB 는 STOPPING 인데 거래소 포지션 0 → STOPPED + qty=0 + RiskEvent
  - *_OPEN orphan      : DB 는 STAGE3_OPEN 인데 거래소 포지션 0 → STOPPED + RiskEvent
  - 정상 active        : 거래소 매칭됨 → status 유지, qty/price sync
  - terminal qty 잔재   : COMPLETED + qty != 0 → enforce_terminal_qty_zero 가 0 으로
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.position import Position
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from app.workers.reconcile_worker import _do_reconcile


# ============================================================================
# STOPPING 좀비 — 거래소 포지션 0
# ============================================================================
class TestStoppingZombieAutoCleanup:
    def test_stopping_with_no_exchange_position_promotes_to_stopped(
        self,
        db_session,
        make_strategy,
        fake_binance,
        identity_decrypt,
        patched_sessionlocal,
    ) -> None:
        # given: STOPPING 상태 + qty 잔재 + 거래소 응답이 매칭 없음 (matched=None 경로)
        # 주: Binance 가 hedge mode 에서 amt=0 placeholder 를 보내는 케이스는
        # 5사이클 stuck escalation 으로 처리됨 (별도 path). 이 테스트는 1사이클 자동정리.
        strategy = make_strategy(
            symbol_str="BTCUSDT",
            side="SHORT",
            status="STOPPING",
            current_position_qty=Decimal("-0.5"),  # qty 잔재
        )
        # 의도적으로 set_position 호출 안 함 → fake_binance 가 빈 리스트 리턴

        # when
        _do_reconcile(identity_decrypt)

        # then: STOPPED + qty 0 + stopped_at + RiskEvent INFO
        db_session.expire_all()
        s = db_session.get(StrategyInstance, strategy.id)
        assert s.status == "STOPPED"
        assert s.current_position_qty == Decimal("0")
        assert s.stopped_at is not None

        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.strategy_instance_id == strategy.id)
        ).scalars().all()
        cleanup_events = [e for e in events if e.event_type == "RECONCILE_STOPPING_ZOMBIE_CLEANUP"]
        assert len(cleanup_events) == 1
        assert cleanup_events[0].severity == "INFO"

    def test_open_state_orphan_is_marked_stopped(
        self,
        db_session,
        make_strategy,
        fake_binance,
        identity_decrypt,
        patched_sessionlocal,
    ) -> None:
        """STAGE3_OPEN 인데 Binance 응답에 매칭 없음 (외부 청산) → STOPPED + WARN."""
        strategy = make_strategy(
            symbol_str="ETHUSDT",
            side="LONG",
            status="STAGE3_OPEN",
            current_position_qty=Decimal("1.5"),
        )
        # 의도적으로 set_position 호출 안 함 → matched=None → orphan 분기

        _do_reconcile(identity_decrypt)

        db_session.expire_all()
        s = db_session.get(StrategyInstance, strategy.id)
        assert s.status == "STOPPED"
        assert s.current_position_qty == Decimal("0")

        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "RECONCILE_AUTO_STOP_ORPHAN")
        ).scalars().all()
        assert len(events) == 1


# ============================================================================
# 정상 sync — 거래소 매칭됨
# ============================================================================
class TestPositionSyncHappyPath:
    def test_active_strategy_with_matching_exchange_position_syncs_qty_and_price(
        self,
        db_session,
        make_strategy,
        fake_binance,
        identity_decrypt,
        patched_sessionlocal,
    ) -> None:
        # given: STAGE2_OPEN + 거래소에 일치 포지션
        strategy = make_strategy(
            symbol_str="BTCUSDT",
            side="SHORT",
            status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.3"),
            avg_entry_price=Decimal("48000"),
        )
        fake_binance.set_position(
            "BTCUSDT",
            position_amt="-0.3",
            entry_price="48000",
            mark_price="47500",
            unrealized_pnl="1.5",
            liquidation_price="60000",
            position_side="SHORT",
        )

        _do_reconcile(identity_decrypt)

        db_session.expire_all()
        s = db_session.get(StrategyInstance, strategy.id)
        # status 유지, mark/unrealized 갱신
        assert s.status == "STAGE2_OPEN"
        assert s.current_position_qty == Decimal("-0.3")
        assert s.unrealized_pnl == Decimal("1.5")
        assert s.liquidation_price == Decimal("60000")

        # Position snapshot 1건 기록
        positions = db_session.execute(
            select(Position).where(Position.strategy_instance_id == strategy.id)
        ).scalars().all()
        assert len(positions) == 1
        assert positions[0].source == "POSITION_RISK_SYNC"
        assert positions[0].mark_price == Decimal("47500")

    def test_pending_status_recovers_to_open_when_stage_plan_triggered(
        self,
        db_session,
        make_strategy,
        fake_binance,
        identity_decrypt,
        patched_sessionlocal,
    ) -> None:
        """STAGE2_OPEN_PENDING + stage_plan.is_triggered=True → STAGE2_OPEN 자가 회복.

        2026-05-04 v2 (#96 사용자 사례 fix): stream 이 FILLED 처리하며 plan.is_triggered=True
        atomic UPDATE 했으나 status 갱신과 race — 이 케이스만 reconcile 이 promote.
        plan 미triggered 면 LIMIT 미체결로 보고 promote 안 함 (#96 다단계 manual trigger 보호).
        """
        from app.models.strategy_stage_plan import StrategyStagePlan
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT",
            status="STAGE2_OPEN_PENDING",
            current_position_qty=Decimal("0"),
        )
        # stage_plan 미리 생성 — stage 2 가 fill 됐다고 marking
        db_session.add(StrategyStagePlan(
            strategy_instance_id=strategy.id, stage_no=2, side="SHORT",
            trigger_mode="PRICE_UP_PCT", trigger_percent=Decimal("10"),
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
        assert s.status == "STAGE2_OPEN"  # PENDING → OPEN 자가 회복
        assert s.current_position_qty == Decimal("-0.4")  # 거래소 값 sync

        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "RECONCILE_RECOVERED_PENDING")
        ).scalars().all()
        assert len(events) == 1

    def test_pending_NOT_promoted_when_stage_plan_not_triggered(
        self,
        db_session,
        make_strategy,
        fake_binance,
        identity_decrypt,
        patched_sessionlocal,
    ) -> None:
        """사용자 #96 사례: STAGE4_OPEN_PENDING + 거래소 포지션 (이전 stages 의 합) +
        stage 4 plan is_triggered=False → reconcile 가 promote 안 함.

        이전 버그: 단순히 exchange_position != 0 만 보고 promote → manual 다단계 trigger 시
        잘못된 status 갱신.
        """
        from app.models.strategy_stage_plan import StrategyStagePlan
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT",
            status="STAGE4_OPEN_PENDING",
            current_position_qty=Decimal("-0.5"),  # stages 1+2+3 합 가정
            current_stage=4,
        )
        # stage 1~3 triggered, stage 4 LIMIT placed but not filled
        for stage_no, triggered in [(1, True), (2, True), (3, True), (4, False)]:
            db_session.add(StrategyStagePlan(
                strategy_instance_id=strategy.id, stage_no=stage_no, side="SHORT",
                trigger_mode="PRICE_UP_PCT", trigger_percent=Decimal("10"),
                trigger_price=Decimal("50000"), planned_capital=Decimal("100"),
                planned_qty=Decimal("0.1"), is_triggered=triggered,
            ))
        db_session.commit()
        fake_binance.set_position(
            "BTCUSDT", position_amt="-0.5", entry_price="48000",
            mark_price="48000", position_side="SHORT",
        )

        _do_reconcile(identity_decrypt)

        db_session.expire_all()
        s = db_session.get(StrategyInstance, strategy.id)
        # promote 안 함 — stage 4 plan 미triggered (LIMIT 거래소 book 대기)
        assert s.status == "STAGE4_OPEN_PENDING"

        # RECONCILE_RECOVERED_PENDING 이벤트 없음
        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "RECONCILE_RECOVERED_PENDING")
        ).scalars().all()
        assert len(events) == 0


# ============================================================================
# enforce_terminal_qty_zero (Phase 1 (b)) — terminal status + qty 잔재
# ============================================================================
class TestTerminalQtyResidualFix:
    def test_completed_strategy_with_residual_qty_gets_zeroed(
        self,
        db_session,
        make_strategy,
        fake_binance,
        identity_decrypt,
        patched_sessionlocal,
    ) -> None:
        """COMPLETED 인데 qty != 0 (운영 사례 #83) → reconcile 한 사이클에 0 으로 정리."""
        strategy = make_strategy(
            symbol_str="XNYUSDT",
            side="SHORT",
            status="COMPLETED",
            current_position_qty=Decimal("-60842"),  # 잔재
        )
        # COMPLETED 는 main loop 에서 active 가 아니므로 거래소 응답 불필요.
        # enforce_terminal_qty_zero 가 처리.

        _do_reconcile(identity_decrypt)

        db_session.expire_all()
        s = db_session.get(StrategyInstance, strategy.id)
        assert s.status == "COMPLETED"  # status 는 그대로
        assert s.current_position_qty == Decimal("0")  # qty 0 으로 정리

        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "ZOMBIE_TERMINAL_QTY_RESET")
        ).scalars().all()
        assert len(events) == 1
