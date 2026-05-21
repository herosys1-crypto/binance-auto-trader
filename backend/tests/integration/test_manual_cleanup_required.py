"""MANUAL_CLEANUP_REQUIRED 신규 상태 통합 테스트 (Phase 2, 2026-05-21).

배경 (#77 PHB / #78 RONIN 사장님 요구):
  - emergency_close 후 거래소가 의도대로 포지션 안 줄이는 경우 자동 STOPPED 처리하지 말고,
    MANUAL_CLEANUP_REQUIRED 로 전환해서 사장님이 직접 처리한 trail 남기기.
  - 사장님이 거래소에서 청산 후 「✅ 처리 완료」 클릭 → 명시적 ack → STOPPED.

테스트 시나리오:
  A. execution_service emergency_close post-verify
     1) 검증 성공 (qty 0) → status STOPPING 유지 (reconcile 다음 사이클이 STOPPED 처리)
     2) 검증 실패 (qty 그대로) → MANUAL_CLEANUP_REQUIRED 전환 + 텔레그램 + RiskEvent
     3) 부분 청산 + 90% 이상 줄음 → 성공 (수수료 허용)
     4) LIMIT 폴백은 검증 skip (즉시 체결 보장 X)
     5) 검증 호출 실패 (네트워크) → status 변경 안 함 (Phase 1 가드 백업)

  B. reconcile_worker 의 자동 STOPPED 차단
     6) MANUAL_CLEANUP_REQUIRED + 거래소 포지션 0 → STOPPED 자동 전환 안 함

  C. API endpoint POST /strategies/{id}/acknowledge-manual-cleanup
     7) MANUAL_CLEANUP_REQUIRED → STOPPED 전환 + RiskEvent
     8) 다른 status 에선 400
     9) 다른 사용자 strategy 에선 404

  D. 신규 진입 가드
    10) 같은 symbol+side MANUAL_CLEANUP_REQUIRED 있으면 새 strategy 차단 (메시지에 가이드)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select, update

from app.core.strategy_status import MANUAL_CLEANUP_REQUIRED
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from app.services.execution_service import ExecutionService
from app.workers.reconcile_worker import _do_reconcile


def _set_updated_at(db_session, strategy_id: int, *, minutes_ago: int) -> None:
    past = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    db_session.execute(
        update(StrategyInstance)
        .where(StrategyInstance.id == strategy_id)
        .values(updated_at=past)
    )
    db_session.commit()
    db_session.expire_all()


def _make_service(db_session, monkeypatch) -> ExecutionService:
    """ExecutionService 인스턴스 — Binance/Trade client 는 fake 로 교체."""
    from integration.conftest import FakeBinanceClient, FakeTradeClient
    monkeypatch.setattr(
        "app.services.execution_service.BinanceClient", FakeBinanceClient,
    )
    monkeypatch.setattr(
        "app.services.execution_service.BinanceFuturesTradeClient", FakeTradeClient,
    )
    # post-verify 의 time.sleep(3) 차단 — 테스트 빠르게.
    monkeypatch.setattr("app.services.execution_service.time.sleep", lambda *_, **__: None)
    return ExecutionService(db_session, api_key="k", api_secret="s", is_testnet=True)


# ============================================================================
# A. execution_service emergency_close post-verify
# ============================================================================
class TestEmergencyClosePostVerify:
    def test_verify_success_no_status_change(
        self, db_session, make_strategy, fake_binance, fake_trade_client, fake_redis, monkeypatch,
    ):
        """청산 주문 후 거래소 qty 가 의도대로 0 됨 → status 유지 (STOPPING)."""
        s = make_strategy(
            symbol_str="ETHUSDT", side="LONG", status="STAGE1_OPEN",
            current_position_qty=Decimal("0.5"),
            avg_entry_price=Decimal("3000"),
        )
        # 진입 시점 포지션
        fake_binance.set_position(
            "ETHUSDT", position_amt="0.5", entry_price="3000",
            mark_price="3001", position_side="LONG",
        )
        svc = _make_service(db_session, monkeypatch)
        # post-verify 호출 시점에 거래소가 이미 0 으로 반영됐다고 시뮬레이션
        # — emergency_close 가 set_position 호출 후 fake_binance 응답이 그대로 유지되니까
        # 호출 후 0 으로 set 하는 trick 이 필요. monkeypatch 로 get_position_risk 변형.
        original_get = fake_binance.get_position_risk
        call_count = {"n": 0}
        def _get_after_close(symbol=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # 최초 호출 — emergency_close 의 actual_position 계산용 (qty=0.5)
                return original_get(symbol=symbol)
            # 두 번째 호출 — post-verify (qty=0 으로 청산 완료 시뮬)
            return [{
                "symbol": "ETHUSDT", "positionSide": "LONG", "positionAmt": "0",
                "entryPrice": "3000", "markPrice": "3001", "unRealizedProfit": "0",
                "liquidationPrice": "0", "marginType": "cross", "isolatedMargin": "0",
                "leverage": "10", "breakEvenPrice": "0",
            }]
        monkeypatch.setattr(svc.client, "get_position_risk", _get_after_close)

        svc.emergency_close_position(s.id, quantity=Decimal("0.5"))

        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        # 정상 청산 — status STOPPING 유지 (reconcile 다음 사이클이 STOPPED 처리)
        assert s2.status == "STOPPING"

        # MANUAL_CLEANUP_REQUIRED 전환 안 됨
        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "EMERGENCY_CLOSE_VERIFY_FAILED")
        ).scalars().all()
        assert events == []

    def test_verify_failure_promotes_to_manual_cleanup(
        self, db_session, make_strategy, fake_binance, fake_trade_client, fake_redis, monkeypatch,
    ):
        """청산 주문 후에도 거래소 qty 그대로 → MANUAL_CLEANUP_REQUIRED 전환."""
        s = make_strategy(
            symbol_str="PHBUSDT", side="LONG", status="STAGE2_OPEN",
            current_position_qty=Decimal("1000"),
            avg_entry_price=Decimal("0.06"),
        )
        fake_binance.set_position(
            "PHBUSDT", position_amt="1000", entry_price="0.06",
            mark_price="0.065", position_side="LONG",
        )
        svc = _make_service(db_session, monkeypatch)
        # post-verify 도 같은 qty 반환 (= 거래소가 청산 안 함)
        # fake_binance 기본 동작 — set_position 한 그대로 유지 → 청산 응답 후에도 1000

        svc.emergency_close_position(s.id, quantity=Decimal("1000"))

        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        # 검증 실패 → MANUAL_CLEANUP_REQUIRED 전환
        assert s2.status == MANUAL_CLEANUP_REQUIRED

        # RiskEvent CRITICAL 기록
        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "EMERGENCY_CLOSE_VERIFY_FAILED")
        ).scalars().all()
        assert len(events) == 1
        assert events[0].severity == "CRITICAL"
        payload = events[0].event_payload
        assert payload["strategy_id"] == s.id
        assert Decimal(payload["initial_position"]) == Decimal("1000")
        assert Decimal(payload["post_position"]) == Decimal("1000")

    def test_verify_partial_close_above_90pct_succeeds(
        self, db_session, make_strategy, fake_binance, fake_trade_client, fake_redis, monkeypatch,
    ):
        """수수료 등으로 의도 대비 90% 이상 줄었으면 성공 처리."""
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN",
            current_position_qty=Decimal("-1.0"),
            avg_entry_price=Decimal("50000"),
        )
        fake_binance.set_position(
            "BTCUSDT", position_amt="-1.0", entry_price="50000",
            mark_price="50001", position_side="SHORT",
        )
        svc = _make_service(db_session, monkeypatch)
        # post-verify 호출 시 0.05 잔량 남음 — 95% 청산됨 (90% 임계 초과 → 성공)
        call_count = {"n": 0}
        def _get_after_close(symbol=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [{
                    "symbol": "BTCUSDT", "positionSide": "SHORT", "positionAmt": "-1.0",
                    "entryPrice": "50000", "markPrice": "50001", "unRealizedProfit": "0",
                    "liquidationPrice": "0", "marginType": "cross", "isolatedMargin": "0",
                    "leverage": "10", "breakEvenPrice": "0",
                }]
            return [{
                "symbol": "BTCUSDT", "positionSide": "SHORT", "positionAmt": "-0.05",
                "entryPrice": "50000", "markPrice": "50001", "unRealizedProfit": "0",
                "liquidationPrice": "0", "marginType": "cross", "isolatedMargin": "0",
                "leverage": "10", "breakEvenPrice": "0",
            }]
        monkeypatch.setattr(svc.client, "get_position_risk", _get_after_close)

        svc.emergency_close_position(s.id, quantity=Decimal("1.0"))

        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        assert s2.status == "STOPPING"  # 정상 청산 — MANUAL_CLEANUP_REQUIRED 안 됨

    def test_verify_skipped_for_limit_fallback(
        self, db_session, make_strategy, fake_binance, fake_trade_client, fake_redis, monkeypatch,
    ):
        """LIMIT 폴백은 즉시 체결 보장 X — verify skip (reconcile/Phase 1 백업).

        verify 가 호출되지 않았는지 확인 — 호출됐다면 fake_binance 의 잔량 1.0 그대로라
        MANUAL_CLEANUP_REQUIRED 전환됐을 것이다.
        """
        s = make_strategy(
            symbol_str="MLNUSDT", side="LONG", status="STAGE1_OPEN",
            current_position_qty=Decimal("1.0"),
            avg_entry_price=Decimal("20.0"),
        )
        fake_binance.set_position(
            "MLNUSDT", position_amt="1.0", entry_price="20.0",
            mark_price="20.1", position_side="LONG",
        )
        svc = _make_service(db_session, monkeypatch)
        # MARKET 호출이 -4131 던지도록 — LIMIT 폴백 경로 강제
        original_place = svc.trade_client.place_market_order
        def _raise_4131(*args, **kwargs):
            raise Exception("Code -4131: PERCENT_PRICE filter rejected")
        monkeypatch.setattr(svc.trade_client, "place_market_order", _raise_4131)
        # _emergency_close_limit_fallback 만 succeed
        def _fb(strategy, *, side, position_side, quantity, client_order_id):
            return {
                "orderId": 9999, "clientOrderId": client_order_id, "executedQty": "0",
                "avgPrice": "0", "status": "NEW", "price": "20.0",
            }
        monkeypatch.setattr(svc, "_emergency_close_limit_fallback", _fb)

        svc.emergency_close_position(s.id, quantity=Decimal("1.0"))

        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        # LIMIT 폴백 후 verify 안 함 → status STOPPING 그대로 (MANUAL_CLEANUP_REQUIRED 아님)
        assert s2.status == "STOPPING"
        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "EMERGENCY_CLOSE_VERIFY_FAILED")
        ).scalars().all()
        assert events == []

    def test_verify_call_failure_does_not_change_status(
        self, db_session, make_strategy, fake_binance, fake_trade_client, fake_redis, monkeypatch,
    ):
        """post-verify 의 get_position_risk 호출 자체 실패 → status 변경 안 함.

        보수적 처리 — false-positive 차단. Phase 1 의 5분 가드가 백업으로 작동.
        """
        s = make_strategy(
            symbol_str="ETHUSDT", side="LONG", status="STAGE1_OPEN",
            current_position_qty=Decimal("0.5"),
            avg_entry_price=Decimal("3000"),
        )
        fake_binance.set_position(
            "ETHUSDT", position_amt="0.5", entry_price="3000",
            mark_price="3001", position_side="LONG",
        )
        svc = _make_service(db_session, monkeypatch)
        call_count = {"n": 0}
        original_get = svc.client.get_position_risk
        def _fail_on_verify(symbol=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return original_get(symbol=symbol)
            raise Exception("network error")
        monkeypatch.setattr(svc.client, "get_position_risk", _fail_on_verify)

        svc.emergency_close_position(s.id, quantity=Decimal("0.5"))

        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        # verify 호출 실패 → MANUAL_CLEANUP_REQUIRED 전환 안 함 (Phase 1 5분 가드가 백업)
        assert s2.status == "STOPPING"


# ============================================================================
# A2. 자동 재시도 1회 (사장님 요구 — 부담 ↓)
# ============================================================================
class TestEmergencyCloseAutoRetry:
    """1차 검증 실패 시 10초 후 잔량 재청산 자동 시도.

    재시도 성공 → 정상 종료 (status STOPPING 유지, reconcile 이 STOPPED 처리)
    재시도 실패 → MANUAL_CLEANUP_REQUIRED 전환 + 텔레그램 (사장님 명시적 처리 필요)
    """

    def test_first_verify_fails_but_retry_succeeds(
        self, db_session, make_strategy, fake_binance, fake_trade_client, fake_redis, monkeypatch,
    ):
        """1차 검증 실패 → 자동 재시도 → 두 번째 검증 성공 → status STOPPING 유지.

        시나리오: 거래소 일시 지연 — 첫 발송 직후엔 qty 1000 그대로,
        재시도 10초 후 거래소 internal state 안정화돼 0 으로 반영.
        """
        s = make_strategy(
            symbol_str="PHBUSDT", side="LONG", status="STAGE2_OPEN",
            current_position_qty=Decimal("1000"),
            avg_entry_price=Decimal("0.06"),
        )
        fake_binance.set_position(
            "PHBUSDT", position_amt="1000", entry_price="0.06",
            mark_price="0.065", position_side="LONG",
        )
        svc = _make_service(db_session, monkeypatch)

        # 호출 1: emergency_close 의 actual_position 계산용 (qty=1000)
        # 호출 2: 1차 post-verify — 거래소 아직 반영 안 됨 (qty=1000)
        # 호출 3: 재시도 후 post-verify — 거래소 반영됨 (qty=0)
        call_count = {"n": 0}
        def _staged_get(symbol=None):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                return [{
                    "symbol": "PHBUSDT", "positionSide": "LONG", "positionAmt": "1000",
                    "entryPrice": "0.06", "markPrice": "0.065", "unRealizedProfit": "0",
                    "liquidationPrice": "0", "marginType": "cross", "isolatedMargin": "0",
                    "leverage": "10", "breakEvenPrice": "0",
                }]
            return [{
                "symbol": "PHBUSDT", "positionSide": "LONG", "positionAmt": "0",
                "entryPrice": "0.06", "markPrice": "0.065", "unRealizedProfit": "0",
                "liquidationPrice": "0", "marginType": "cross", "isolatedMargin": "0",
                "leverage": "10", "breakEvenPrice": "0",
            }]
        monkeypatch.setattr(svc.client, "get_position_risk", _staged_get)

        svc.emergency_close_position(s.id, quantity=Decimal("1000"))

        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        # 재시도 성공 → MANUAL_CLEANUP_REQUIRED 전환 안 됨, STOPPING 유지
        assert s2.status == "STOPPING", (
            f"재시도 성공이면 STOPPING 유지여야 함 — 실제: {s2.status}"
        )

        # RiskEvent 흐름: RETRY_ATTEMPTED + RETRY_SUCCEEDED
        events = db_session.execute(
            select(RiskEvent)
            .where(RiskEvent.strategy_instance_id == s.id)
            .where(RiskEvent.event_type.in_([
                "EMERGENCY_CLOSE_RETRY_ATTEMPTED",
                "EMERGENCY_CLOSE_RETRY_SUCCEEDED",
                "EMERGENCY_CLOSE_VERIFY_FAILED",
            ]))
        ).scalars().all()
        types = {e.event_type for e in events}
        assert "EMERGENCY_CLOSE_RETRY_ATTEMPTED" in types
        assert "EMERGENCY_CLOSE_RETRY_SUCCEEDED" in types
        assert "EMERGENCY_CLOSE_VERIFY_FAILED" not in types  # 재시도 성공이므로 manual cleanup 안 함

        # 재시도 trade_client 호출 발생 (1차 + 재시도 = 2건)
        assert len(fake_trade_client.placed_orders) == 2
        retry_order = fake_trade_client.placed_orders[1]
        assert "EXIT_RETRY" in retry_order["newClientOrderId"]

    def test_first_and_retry_both_fail_promotes_to_manual_cleanup(
        self, db_session, make_strategy, fake_binance, fake_trade_client, fake_redis, monkeypatch,
    ):
        """1차 + 재시도 모두 검증 실패 → MANUAL_CLEANUP_REQUIRED 전환.

        fake_binance 가 계속 1000 반환 — 자동 재시도해도 거래소 거절 지속.
        """
        s = make_strategy(
            symbol_str="RONINUSDT", side="SHORT", status="STAGE1_OPEN",
            current_position_qty=Decimal("-87.1"),
            avg_entry_price=Decimal("5.0"),
        )
        fake_binance.set_position(
            "RONINUSDT", position_amt="-87.1", entry_price="5.0",
            mark_price="5.01", position_side="SHORT",
        )
        svc = _make_service(db_session, monkeypatch)

        # fake_binance 가 항상 -87.1 반환 (재시도해도 거래소 거절 — 예: 마진 부족)
        svc.emergency_close_position(s.id, quantity=Decimal("87.1"))

        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        assert s2.status == MANUAL_CLEANUP_REQUIRED

        # 흐름: RETRY_ATTEMPTED → (재시도 발송) → VERIFY_FAILED (재시도 후에도)
        events = db_session.execute(
            select(RiskEvent)
            .where(RiskEvent.strategy_instance_id == s.id)
            .where(RiskEvent.event_type.in_([
                "EMERGENCY_CLOSE_RETRY_ATTEMPTED",
                "EMERGENCY_CLOSE_RETRY_SUCCEEDED",
                "EMERGENCY_CLOSE_VERIFY_FAILED",
            ]))
        ).scalars().all()
        types = {e.event_type for e in events}
        assert "EMERGENCY_CLOSE_RETRY_ATTEMPTED" in types
        assert "EMERGENCY_CLOSE_RETRY_SUCCEEDED" not in types
        assert "EMERGENCY_CLOSE_VERIFY_FAILED" in types

        # payload 에 retry_attempted=True 기록
        verify_failed = next(e for e in events if e.event_type == "EMERGENCY_CLOSE_VERIFY_FAILED")
        assert verify_failed.event_payload.get("retry_attempted") is True

        # 재시도 발송 자체는 됐음 (2건)
        assert len(fake_trade_client.placed_orders) == 2

    def test_retry_call_itself_fails_promotes_to_manual_cleanup(
        self, db_session, make_strategy, fake_binance, fake_trade_client, fake_redis, monkeypatch,
    ):
        """재시도 발송 자체가 거래소 거절 (Exception) → MANUAL_CLEANUP_REQUIRED + retry_error 기록."""
        s = make_strategy(
            symbol_str="AAAUSDT", side="LONG", status="STAGE1_OPEN",
            current_position_qty=Decimal("100"),
            avg_entry_price=Decimal("1.0"),
        )
        fake_binance.set_position(
            "AAAUSDT", position_amt="100", entry_price="1.0",
            mark_price="1.0", position_side="LONG",
        )
        svc = _make_service(db_session, monkeypatch)

        # 첫 발송은 성공, 재시도는 예외 던지도록 (예: rate limit)
        original_place = svc.trade_client.place_market_order
        call_count = {"n": 0}
        def _fail_on_retry(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return original_place(*args, **kwargs)
            raise Exception("rate limit exceeded -1003")
        monkeypatch.setattr(svc.trade_client, "place_market_order", _fail_on_retry)

        svc.emergency_close_position(s.id, quantity=Decimal("100"))

        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        assert s2.status == MANUAL_CLEANUP_REQUIRED

        events = db_session.execute(
            select(RiskEvent)
            .where(RiskEvent.event_type == "EMERGENCY_CLOSE_VERIFY_FAILED")
            .where(RiskEvent.strategy_instance_id == s.id)
        ).scalars().all()
        assert len(events) == 1
        payload = events[0].event_payload
        assert payload.get("retry_attempted") is True
        assert "rate limit" in (payload.get("retry_error") or "")


# ============================================================================
# B. reconcile_worker 의 자동 STOPPED 차단
# ============================================================================
class TestReconcileAutoStoppedBlocked:
    def test_manual_cleanup_with_exchange_position_zero_not_auto_stopped(
        self, db_session, make_strategy, fake_binance, identity_decrypt,
        patched_sessionlocal,
    ):
        """MANUAL_CLEANUP_REQUIRED 인데 거래소 포지션 0 → 자동 STOPPED 전환 안 함.

        사장님이 거래소에서 직접 청산했어도 명시적 「✅ 처리 완료」 클릭하기 전까지는
        MANUAL_CLEANUP_REQUIRED 유지. reconcile 은 qty/price sync 만 진행.
        """
        s = make_strategy(
            symbol_str="PHBUSDT", side="LONG", status=MANUAL_CLEANUP_REQUIRED,
            current_position_qty=Decimal("100"),
            avg_entry_price=Decimal("0.06"),
        )
        # 거래소 포지션은 0 (사장님이 직접 청산함)
        # fake_binance.set_position 호출 안 함 → matched=None

        _do_reconcile(identity_decrypt)
        db_session.expire_all()

        s2 = db_session.get(StrategyInstance, s.id)
        # 자동 STOPPED 안 됨 — 사장님 명시적 ack 필요
        assert s2.status == MANUAL_CLEANUP_REQUIRED, (
            f"MANUAL_CLEANUP_REQUIRED 는 거래소 포지션 0 이어도 자동 STOPPED 안 돼야 함 — 실제: {s2.status}"
        )


# ============================================================================
# C. API endpoint POST /strategies/{id}/acknowledge-manual-cleanup
# ============================================================================
class TestAcknowledgeManualCleanupEndpoint:
    """endpoint 함수 직접 호출 (TestClient 우회 — sqlite engine 격리 위해).

    기존 test_strategies_endpoint_terminal_handling 와 동일 패턴.
    """

    def test_acknowledge_promotes_manual_cleanup_to_stopped(
        self, db_session, make_strategy,
    ):
        from app.api.v1.strategies.lifecycle import acknowledge_manual_cleanup

        s = make_strategy(
            symbol_str="PHBUSDT", side="LONG", status=MANUAL_CLEANUP_REQUIRED,
            current_position_qty=Decimal("100"),
        )

        resp = acknowledge_manual_cleanup(strategy_id=s.id, db=db_session, user_id=s.user_id)
        assert resp.status == "STOPPED"
        assert "처리 완료" in resp.message

        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        assert s2.status == "STOPPED"
        assert s2.current_position_qty == Decimal("0")
        assert s2.stopped_at is not None

        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "MANUAL_CLEANUP_ACKNOWLEDGED")
        ).scalars().all()
        assert len(events) == 1
        assert events[0].severity == "INFO"
        assert events[0].event_payload["acknowledged_by_user_id"] == s.user_id
        assert events[0].event_payload["previous_status"] == MANUAL_CLEANUP_REQUIRED

    def test_acknowledge_rejected_when_not_manual_cleanup(
        self, db_session, make_strategy,
    ):
        """status 가 MANUAL_CLEANUP_REQUIRED 아니면 400."""
        from fastapi import HTTPException
        from app.api.v1.strategies.lifecycle import acknowledge_manual_cleanup

        s = make_strategy(
            symbol_str="BTCUSDT", side="LONG", status="STAGE1_OPEN",
            current_position_qty=Decimal("0.5"),
        )
        with pytest.raises(HTTPException) as exc_info:
            acknowledge_manual_cleanup(strategy_id=s.id, db=db_session, user_id=s.user_id)
        assert exc_info.value.status_code == 400
        assert "MANUAL_CLEANUP_REQUIRED" in exc_info.value.detail

    def test_acknowledge_rejected_for_other_user(
        self, db_session, make_strategy, make_user,
    ):
        """다른 사용자 strategy ack 시도 시 404."""
        from fastapi import HTTPException
        from app.api.v1.strategies.lifecycle import acknowledge_manual_cleanup

        s = make_strategy(
            symbol_str="PHBUSDT", side="LONG", status=MANUAL_CLEANUP_REQUIRED,
        )
        other_user = make_user()
        with pytest.raises(HTTPException) as exc_info:
            acknowledge_manual_cleanup(strategy_id=s.id, db=db_session, user_id=other_user.id)
        assert exc_info.value.status_code == 404


# ============================================================================
# D. 신규 진입 가드
# ============================================================================
class TestNewStrategyBlockedByManualCleanup:
    def test_duplicate_blocked_with_manual_cleanup_guidance(
        self, db_session, make_strategy, make_template, make_symbol, make_exchange_account,
    ):
        """같은 symbol+side 가 MANUAL_CLEANUP_REQUIRED 면 새 strategy 차단 + 가이드 메시지."""
        from app.services.strategy_service import StrategyService

        ea = make_exchange_account()
        sym = make_symbol("PHBUSDT")
        tpl = make_template()
        # 기존 strategy 가 MANUAL_CLEANUP_REQUIRED 상태
        existing = make_strategy(
            symbol_str="PHBUSDT", side="LONG", status=MANUAL_CLEANUP_REQUIRED,
            user=ea.user_id and None or None,  # 일관성 위해 같은 ea/user 사용
            exchange_account=ea, symbol_obj=sym, template=tpl,
        )

        svc = StrategyService(db_session)
        with pytest.raises(ValueError) as exc_info:
            svc.create_strategy_instance(
                user_id=ea.user_id,
                exchange_account_id=ea.id,
                strategy_template_id=tpl.id,
                symbol="PHBUSDT", side="LONG",
                start_price=Decimal("0.06"),
            )
        err_str = str(exc_info.value)
        # 메시지에 「수동 청산 요청」 가이드 + 「✅ 처리 완료」 + ack 안내 포함
        assert "수동 청산 요청" in err_str
        assert "처리 완료" in err_str
        assert f"#{existing.id}" in err_str
