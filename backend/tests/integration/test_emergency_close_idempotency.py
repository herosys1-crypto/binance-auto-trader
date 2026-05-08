"""emergency_close_position idempotency lock — 중복 발사 차단 (2026-05-08 #120 사례).

배경:
  #120 DYDXUSDT 에서 동일 시각 (05:20:56) 에 EXIT MARKET 245 DYDX 가 3건 발사 →
  진입 980 - 청산 735 = 잔량 245 가 거래소에 남았는데 DB 는 REENTRY_READY (qty=0)
  로 마킹 → orphan 감지 → Kill-Switch 발동.

  emergency_close_position 의 4개 caller (manual stop, admin cleanup,
  tp_sl_orchestrator TP, tp_sl_orchestrator SL) 가 각자의 락만 가지고 있어서
  cross-caller 중복은 막히지 않았음. 함수 자체에 Redis 기반 idempotency lock 추가
  (TTL 5s) — 같은 strategy 의 5초 내 중복 호출은 EmergencyCloseInProgress 발생.

검증:
  1) 단일 호출은 정상 진행
  2) 5초 내 두 번째 호출은 EmergencyCloseInProgress 발생
  3) 락 만료 후 (또는 첫 호출 종료 후) 다시 호출 가능
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.execution_service import EmergencyCloseInProgress, ExecutionService


@pytest.fixture
def execution(db_session):
    return ExecutionService(
        db_session, api_key="enc:apikey", api_secret="enc:secret", is_testnet=True,
    )


class TestEmergencyCloseIdempotency:
    def test_single_call_succeeds(
        self, db_session, make_template, make_strategy, make_position,
        fake_redis, fake_binance, fake_trade_client, execution,
    ):
        """단일 호출은 정상 — 락 acquire 성공."""
        tpl = make_template()
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN",
            current_position_qty=Decimal("-0.5"), avg_entry_price=Decimal("50000"),
            template=tpl,
        )
        make_position(s, mark_price=Decimal("50000"))
        fake_binance.set_position(
            "BTCUSDT", position_amt="-0.5", entry_price="50000",
            mark_price="50000", position_side="SHORT",
        )

        order = execution.emergency_close_position(s.id, quantity=Decimal("0.1"))
        assert order is not None
        assert len(fake_trade_client.placed_orders) == 1

    def test_concurrent_call_blocked(
        self, db_session, make_template, make_strategy, make_position,
        fake_redis, fake_binance, fake_trade_client, execution,
    ):
        """다른 caller 가 락 보유 중일 때 두 번째 호출은 EmergencyCloseInProgress."""
        tpl = make_template()
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN",
            current_position_qty=Decimal("-0.5"), avg_entry_price=Decimal("50000"),
            template=tpl,
        )
        make_position(s, mark_price=Decimal("50000"))
        fake_binance.set_position(
            "BTCUSDT", position_amt="-0.5", entry_price="50000",
            mark_price="50000", position_side="SHORT",
        )

        # 첫 caller 가 락 잡음 (수동 simulate — 실제로는 with-block 안에서 처리)
        fake_redis.set(f"lock:strategy:{s.id}:emergency_close", "other-token", nx=True, ex=5)

        # 두 번째 caller 는 EmergencyCloseInProgress
        with pytest.raises(EmergencyCloseInProgress, match="청산이 이미 진행 중"):
            execution.emergency_close_position(s.id, quantity=Decimal("0.1"))

        # 거래소 주문은 0건 (락 차단)
        assert len(fake_trade_client.placed_orders) == 0

    def test_lock_released_after_completion(
        self, db_session, make_template, make_strategy, make_position,
        fake_redis, fake_binance, fake_trade_client, execution,
    ):
        """첫 호출이 완료되면 락 해제 — 이후 호출은 다시 정상 진행 가능."""
        tpl = make_template()
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN",
            current_position_qty=Decimal("-0.5"), avg_entry_price=Decimal("50000"),
            template=tpl,
        )
        make_position(s, mark_price=Decimal("50000"))
        fake_binance.set_position(
            "BTCUSDT", position_amt="-0.5", entry_price="50000",
            mark_price="50000", position_side="SHORT",
        )

        # 첫 호출
        execution.emergency_close_position(s.id, quantity=Decimal("0.1"))
        # 두 번째 호출 — 첫 호출이 with-block 빠져나오며 락 해제
        execution.emergency_close_position(s.id, quantity=Decimal("0.1"))

        # 두 호출 모두 거래소 주문 발사 (락 정상 해제 확인)
        assert len(fake_trade_client.placed_orders) == 2

    def test_three_rapid_calls_only_one_succeeds(
        self, db_session, make_template, make_strategy, make_position,
        fake_redis, fake_binance, fake_trade_client, execution,
    ):
        """#120 사례 재현 — 락이 잡혀있는 동안 추가 호출 모두 차단.

        실제 #120: 3건의 동시 EXIT MARKET 245 발사 → 진입 980 - 735 = 245 잔량.
        fix 후: 첫 호출 진행 중 락 보유 → 2/3번째 호출은 EmergencyCloseInProgress.
        """
        tpl = make_template()
        s = make_strategy(
            symbol_str="DYDXUSDT", side="SHORT", status="STAGE1_OPEN",
            current_position_qty=Decimal("-980.30"), avg_entry_price=Decimal("0.204"),
            template=tpl,
        )
        make_position(s, mark_price=Decimal("0.184"))
        fake_binance.set_position(
            "DYDXUSDT", position_amt="-980.30", entry_price="0.204",
            mark_price="0.184", position_side="SHORT",
        )

        # 첫 caller 가 락 미리 잡고 있는 상황 simulate
        fake_redis.set(f"lock:strategy:{s.id}:emergency_close", "tp_sl-token", nx=True, ex=5)

        # 추가 2번 호출 시도 → 모두 차단
        for _ in range(2):
            with pytest.raises(EmergencyCloseInProgress):
                execution.emergency_close_position(s.id, quantity=Decimal("245"))

        # 거래소 주문 0건 (락이 사전 점유 상태)
        assert len(fake_trade_client.placed_orders) == 0
