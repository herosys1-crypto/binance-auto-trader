"""tp_sl_orchestrator 종단간 통합 — 마크프라이스 → TP 발동 → 부분 청산 → status 전이.

unit test 가 helper 함수와 분기를 보장하지만, 이 통합 테스트는 실제 흐름을 한 번에:
  TPSLOrchestratorService.run_for_strategy
    → RiskService.evaluate_take_profit_level
    → ExecutionService.emergency_close_position
    → BinanceFuturesTradeClient.place_market_order  ← FakeTradeClient
    → Order row 생성 + strategy.status 전이 + Notification 발송

Binance API 는 두 군데에서 호출됨:
  1) ExecutionService.client.get_position_risk → FakeBinanceClient 처리
  2) ExecutionService.trade_client.place_market_order → FakeTradeClient 처리

Redis 는 redis_lock + risk_service peak_pnl 추적 → FakeRedis 처리.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.notification import Notification
from app.models.order import Order
from app.models.strategy_instance import StrategyInstance
from app.services.tp_sl_orchestrator import TPSLOrchestratorService


@pytest.fixture
def orchestrator(db_session):
    """ExecutionService 가 BinanceClient/BinanceFuturesTradeClient 를 인스턴스화하는데
    fake_binance + fake_trade_client fixture 가 import 위치를 패치해 둔 상태에서
    오케스트레이터를 만든다."""
    return TPSLOrchestratorService(
        db_session,
        api_key="enc:apikey",
        api_secret="enc:secret",
        is_testnet=True,
    )


# ============================================================================
# 정상 모드 — TP1 부분 청산
# ============================================================================
class TestTP1PartialClose:
    """SHORT BTCUSDT, leverage 1x, TP1=5%. 마크프라이스가 진입가 대비 5% 하락."""

    def test_short_tp1_threshold_triggers_partial_close(
        self,
        db_session,
        make_template,
        make_strategy,
        make_position,
        fake_redis,
        fake_binance,
        fake_trade_client,
        orchestrator,
    ) -> None:
        # given: SHORT 0.5 BTC @ 50000, leverage 1x, status STAGE2_OPEN
        # template: TP1=5%, TP2=10%, TP3=15%, qty_ratios=25/50/100
        tpl = make_template(
            tp1_percent=Decimal("5"), tp2_percent=Decimal("10"), tp3_percent=Decimal("15"),
            tp1_qty_ratio=Decimal("25"), tp2_qty_ratio=Decimal("50"), tp3_qty_ratio=Decimal("100"),
        )
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
            avg_entry_price=Decimal("50000"),
            leverage=1,
            template=tpl,
            current_stage=2,
        )
        # mark price 47500 → SHORT raw PnL = +5% → leveraged ROI = 5% → TP1 도달
        make_position(strategy, mark_price=Decimal("47500"))
        # 거래소 매칭 포지션 (emergency_close 가 get_position_risk 검사)
        fake_binance.set_position(
            "BTCUSDT", position_amt="-0.5", entry_price="50000", mark_price="47500",
            position_side="SHORT",
        )

        # when
        orchestrator.run_for_strategy(strategy.id)

        # then: 거래소 BUY 0.125 (close 25% of 0.5) 주문 1건
        assert len(fake_trade_client.placed_orders) == 1
        placed = fake_trade_client.placed_orders[0]
        assert placed["symbol"] == "BTCUSDT"
        assert placed["side"] == "BUY"  # SHORT 청산은 BUY
        assert placed["positionSide"] == "SHORT"
        assert Decimal(placed["quantity"]) == Decimal("0.125")  # 0.5 × 25%

        # status = TP1_DONE_PARTIAL (마지막 활성 TP 가 아니므로 부분 청산)
        db_session.expire_all()
        s = db_session.get(StrategyInstance, strategy.id)
        assert s.status == "TP1_DONE_PARTIAL"

        # Order row 1건 (purpose=EXIT, status=FILLED)
        orders = db_session.execute(
            select(Order).where(Order.strategy_instance_id == strategy.id)
        ).scalars().all()
        assert len(orders) == 1
        assert orders[0].purpose == "EXIT"
        assert orders[0].status == "FILLED"
        assert orders[0].orig_qty == Decimal("0.125")

        # Notification 1건 (take profit alert)
        notifs = db_session.execute(
            select(Notification).where(Notification.strategy_instance_id == strategy.id)
        ).scalars().all()
        assert len(notifs) == 1
        assert "TP1" in notifs[0].title or "익절" in notifs[0].title

    def test_no_tp_threshold_reached_no_close_no_status_change(
        self,
        db_session,
        make_template,
        make_strategy,
        make_position,
        fake_redis,
        fake_binance,
        fake_trade_client,
        orchestrator,
    ) -> None:
        """마크프라이스가 임계 미달 → 아무 청산 없음, status 유지."""
        tpl = make_template(tp1_percent=Decimal("5"))
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
            avg_entry_price=Decimal("50000"), leverage=1,
            template=tpl, current_stage=2,
        )
        # mark 49000 = SHORT 2% PnL (TP1 5% 미달)
        make_position(strategy, mark_price=Decimal("49000"))
        fake_binance.set_position(
            "BTCUSDT", position_amt="-0.5", position_side="SHORT",
            entry_price="50000", mark_price="49000",
        )

        orchestrator.run_for_strategy(strategy.id)

        assert len(fake_trade_client.placed_orders) == 0
        db_session.expire_all()
        s = db_session.get(StrategyInstance, strategy.id)
        assert s.status == "STAGE2_OPEN"


# ============================================================================
# 마지막 활성 TP — 잔량 100% 청산 + COMPLETED
# ============================================================================
class TestLastActiveTPFullClose:
    """사용자 기획: 활성 TP 중 가장 큰 번호가 발동하면 사용자 ratio 무시하고 잔량 100% 청산.

    예: TP1/2/3 활성 + TP3 발동 → 사용자가 ratio=50% 설정해도 잔량 100% 청산 + COMPLETED.
    이는 "4/4 익절 모두 종료되면 전략 인스턴스 모두 종료" 기획의 정확 반영.
    """

    def test_short_tp3_uses_template_ratio_not_full_close_v6(
        self,
        db_session,
        make_template,
        make_strategy,
        make_position,
        fake_redis,
        fake_binance,
        fake_trade_client,
        orchestrator,
    ) -> None:
        """v6 (2026-05-12 밤): last_active_tp shortcut 폐지. TP3 가 마지막 enabled 여도
        사용자 ratio (또는 default 25%) 사용. trailing 이 close-all 처리.

        시나리오: TP1=5/TP2=10/TP3=15 활성, TP3 ratio=50% — 사용자 의도 부분 청산.
        v5 까지: TP3 가 last_active_tp → 100% 강제 → COMPLETED.
        v6: TP3 가 50% 청산 → 잔량 보유 → status TP3_DONE_PARTIAL → trailing 가능.
        """
        tpl = make_template(
            tp1_percent=Decimal("5"), tp2_percent=Decimal("10"), tp3_percent=Decimal("15"),
            tp1_qty_ratio=Decimal("25"), tp2_qty_ratio=Decimal("50"), tp3_qty_ratio=Decimal("50"),
            tp4_percent=None, tp5_percent=None,
        )
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="TP2_DONE_PARTIAL",
            current_position_qty=Decimal("-0.2"),  # TP1+TP2 청산 후 잔량
            avg_entry_price=Decimal("50000"), leverage=1,
            template=tpl, current_stage=3,
        )
        make_position(strategy, mark_price=Decimal("42500"))
        fake_binance.set_position(
            "BTCUSDT", position_amt="-0.2", position_side="SHORT",
            entry_price="50000", mark_price="42500",
        )

        orchestrator.run_for_strategy(strategy.id)

        # v6: 사용자 ratio 50% 적용 → 0.1 BTC 청산 (잔량 0.1 보유)
        assert len(fake_trade_client.placed_orders) == 1
        placed = fake_trade_client.placed_orders[0]
        assert Decimal(placed["quantity"]) == Decimal("0.1"), (
            f"v6: TP3 사용자 ratio 50% 적용, 100% 강제 안 함 (last_active_tp shortcut 폐지). "
            f"실제 quantity={placed['quantity']}"
        )

        db_session.expire_all()
        s = db_session.get(StrategyInstance, strategy.id)
        # v6: 부분 청산 → status = TP3_DONE_PARTIAL (COMPLETED 아님)
        assert s.status == "TP3_DONE_PARTIAL", (
            f"v6: 부분 청산 후 TP3_DONE_PARTIAL 상태 (잔량 보유 → trailing 기회). "
            f"실제 status={s.status}"
        )


# ============================================================================
# 이미 더 높은 단계 — 같은 또는 낮은 TP 재발동 방지
# ============================================================================
class TestNoRefireOnLowerOrSameTPLevel:
    """status=TP2_DONE_PARTIAL 인데 mark price 가 TP1 임계만 도달 → TP1 재실행 안 함."""

    def test_tp2_done_state_does_not_refire_tp1(
        self,
        db_session,
        make_template,
        make_strategy,
        make_position,
        fake_redis,
        fake_binance,
        fake_trade_client,
        orchestrator,
    ) -> None:
        tpl = make_template(
            tp1_percent=Decimal("5"), tp2_percent=Decimal("10"), tp3_percent=Decimal("15"),
        )
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="TP2_DONE_PARTIAL",
            current_position_qty=Decimal("-0.25"),
            avg_entry_price=Decimal("50000"), leverage=1,
            template=tpl, current_stage=2,
        )
        # mark 47500 = SHORT 5% PnL (TP1 도달, TP2/3 미달)
        # 하지만 status 가 이미 TP2_DONE_PARTIAL → TP1 재실행 안 함.
        make_position(strategy, mark_price=Decimal("47500"))
        fake_binance.set_position(
            "BTCUSDT", position_amt="-0.25", position_side="SHORT",
            entry_price="50000", mark_price="47500",
        )

        orchestrator.run_for_strategy(strategy.id)

        # 청산 발생 안 함
        assert len(fake_trade_client.placed_orders) == 0
        db_session.expire_all()
        s = db_session.get(StrategyInstance, strategy.id)
        assert s.status == "TP2_DONE_PARTIAL"  # 변경 없음


# ============================================================================
# Redis lock 보호 — 동시 호출 한 쪽만 진행
# ============================================================================
class TestRedisLockProtection:
    """run_for_strategy 가 wait_timeout=0 락이라 락 점유 시 즉시 skip."""

    def test_lock_held_by_other_skips_silently(
        self,
        db_session,
        make_template,
        make_strategy,
        make_position,
        fake_redis,
        fake_binance,
        fake_trade_client,
        orchestrator,
    ) -> None:
        tpl = make_template(tp1_percent=Decimal("5"))
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
            avg_entry_price=Decimal("50000"), leverage=1,
            template=tpl, current_stage=2,
        )
        make_position(strategy, mark_price=Decimal("47500"))  # TP1 도달
        fake_binance.set_position(
            "BTCUSDT", position_amt="-0.5", position_side="SHORT",
            entry_price="50000", mark_price="47500",
        )
        # 다른 인스턴스가 lock 을 미리 점유
        lock_key = f"lock:strategy:{strategy.id}:tp_sl"
        fake_redis.set(lock_key, "other_token", nx=True, ex=20)

        # when
        orchestrator.run_for_strategy(strategy.id)

        # then: lock 점유로 skip → 청산 발생 안 함, status 유지
        assert len(fake_trade_client.placed_orders) == 0
        db_session.expire_all()
        s = db_session.get(StrategyInstance, strategy.id)
        assert s.status == "STAGE2_OPEN"


# ============================================================================
# 사용자 #40 BUSDT step_size flooring 후속 (2026-05-14)
# ============================================================================
class TestTPMinStepEnforcement:
    """사용자 #40 BUSDT 보고 후속 — step_size flooring 으로 close_qty=0 이 되면
    사용자 「3단계 익절 모두 진행」 의도와 다름. 잔량 ≥ step 이면 최소 1 step 보장.

    테스트:
    1. 잔량 충분 (100) + step 50 + ratio 25% (=25 → floor 0) → close=50 (1 step 보장)
    2. 잔량 부족 (25) + step 50 → 청산 진행 X (current_qty < step)
    """

    def test_tp_with_floored_zero_qty_enforces_min_step(
        self,
        db_session,
        make_template,
        make_strategy,
        make_position,
        make_symbol,
        fake_redis,
        fake_binance,
        fake_trade_client,
        orchestrator,
    ) -> None:
        """잔량 100, step 50, TP1 ratio 25% → raw=25 → floor=0 → fix: 50 보장."""
        # 큰 step_size 심볼 (BUSDT 같은)
        sym = make_symbol("BIGSTEP", step_size=Decimal("50"))
        tpl = make_template(
            tp1_percent=Decimal("5"), tp2_percent=Decimal("10"), tp3_percent=Decimal("15"),
            tp1_qty_ratio=Decimal("25"), tp2_qty_ratio=Decimal("25"), tp3_qty_ratio=Decimal("25"),
        )
        strategy = make_strategy(
            symbol_str="BIGSTEP", side="SHORT", status="STAGE2_OPEN",
            symbol_obj=sym,
            current_position_qty=Decimal("-100"),  # 잔량 100, step 50
            avg_entry_price=Decimal("1.0"),
            leverage=1,
            template=tpl, current_stage=2,
        )
        # mark 0.95 = SHORT +5% → TP1 도달
        make_position(strategy, mark_price=Decimal("0.95"))
        fake_binance.set_position(
            "BIGSTEP", position_amt="-100", position_side="SHORT",
            entry_price="1.0", mark_price="0.95",
        )

        orchestrator.run_for_strategy(strategy.id)

        # 100 × 0.25 = 25 → step 50 으로 floor 시 0 → fix 작동 → 50 (1 step) close
        assert len(fake_trade_client.placed_orders) == 1, (
            "step flooring 으로 close_qty=0 이 되더라도 최소 1 step 청산 보장 (사용자 #40 후속)"
        )
        placed = fake_trade_client.placed_orders[0]
        assert Decimal(placed["quantity"]) == Decimal("50"), (
            f"최소 1 step (50) close 기대. 실제: {placed['quantity']}"
        )

        # status 진행 (TP1_DONE_PARTIAL)
        db_session.expire_all()
        s = db_session.get(StrategyInstance, strategy.id)
        assert s.status == "TP1_DONE_PARTIAL"

        # WARN 이벤트 기록
        from app.models.risk_event import RiskEvent
        events = db_session.execute(
            select(RiskEvent)
            .where(RiskEvent.strategy_instance_id == strategy.id)
            .where(RiskEvent.event_type == "TP_MIN_STEP_ENFORCED")
        ).scalars().all()
        assert len(events) == 1, "TP_MIN_STEP_ENFORCED RiskEvent 기록돼야"
        assert "TP1" in events[0].title

    def test_tp_with_qty_below_step_skips_close(
        self,
        db_session,
        make_template,
        make_strategy,
        make_position,
        make_symbol,
        fake_redis,
        fake_binance,
        fake_trade_client,
        orchestrator,
    ) -> None:
        """잔량 25 (step 50 미만) + partial TP → close 진행 X (current_qty < step).

        partial close 경로 (close_ratio < 1.00) 만 step floor 검증 — last TP 의 100%
        close 는 별도 경로 (close_qty = current_qty 그대로).
        """
        sym = make_symbol("TINYREM", step_size=Decimal("50"))
        # TP1 + TP2 정의 → TP1 발동 시 partial close (last X)
        tpl = make_template(
            tp1_percent=Decimal("5"), tp2_percent=Decimal("10"), tp3_percent=Decimal("15"),
            tp1_qty_ratio=Decimal("25"), tp2_qty_ratio=Decimal("25"), tp3_qty_ratio=Decimal("25"),
        )
        strategy = make_strategy(
            symbol_str="TINYREM", side="SHORT", status="STAGE2_OPEN",
            symbol_obj=sym,
            current_position_qty=Decimal("-25"),  # 잔량 25 < step 50
            avg_entry_price=Decimal("1.0"),
            leverage=1,
            template=tpl, current_stage=2,
        )
        # mark 0.95 = SHORT +5% → TP1 도달 (partial 25%)
        make_position(strategy, mark_price=Decimal("0.95"))
        fake_binance.set_position(
            "TINYREM", position_amt="-25", position_side="SHORT",
            entry_price="1.0", mark_price="0.95",
        )

        orchestrator.run_for_strategy(strategy.id)

        # 25 × 0.25 = 6.25 → step 50 으로 floor = 0 → fix: current_qty 25 < step 50 →
        # 1 step 보장 안 됨 → return (close 안 함)
        assert len(fake_trade_client.placed_orders) == 0, (
            "잔량 < step 이면 close 진행 안 함 (1 step 도 부족 — 진짜 청산 불가)"
        )
        # status 도 진행 안 함 (return 으로 인해)
        db_session.expire_all()
        s = db_session.get(StrategyInstance, strategy.id)
        assert s.status == "STAGE2_OPEN", "step 부족 시 status 도 그대로"
