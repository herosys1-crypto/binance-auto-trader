"""Phase 2B — TP 부분 청산 + ENTRY MARKET post-verify (사장님 요구 2026-05-21).

배경:
  Phase 2 (PR #2) 는 emergency_close (전량 청산) 만 검증 + 자동 재시도 적용.
  사장님 추가 요구: 진입(ENTRY MARKET) / 부분 익절(TP) / 손절(SL) 도 검증 → 거래소가
  실제로 의도대로 작동했는지 즉시 확인 → 실패 시 즉시 사장님 알림.

설계 분기:
  - emergency_close + SL (전량 청산, is_full_close=True): 검증 실패 → MANUAL_CLEANUP_REQUIRED
  - TP 부분 청산 (is_full_close=False): 검증 실패 → 알림만 (status 변경 X, race 방지)
    이유: `_execute_take_profit` 가 호출 후 status TP_N_DONE_PARTIAL 로 덮어쓰므로
    MANUAL_CLEANUP_REQUIRED 가 무효화됨. 다음 cycle 자연 재평가 + 사장님 인지.
  - ENTRY MARKET: 검증 실패 → 알림만 (자동 재시도 X — 중복 진입 risk)

테스트 시나리오:
  A. TP 부분 청산 검증
    1) TP1 발동 + 검증 성공 → status TP1_DONE_PARTIAL 정상
    2) TP1 발동 + 1차 실패 + 재시도 성공 → 정상 + RETRY_SUCCEEDED RiskEvent
    3) TP1 발동 + 1차+재시도 모두 실패 → PARTIAL_CLOSE_VERIFY_FAILED RiskEvent +
       status 변경 안 됨 (MANUAL_CLEANUP_REQUIRED 아님)

  B. ENTRY MARKET 검증
    4) 진입 성공 → 정상, RiskEvent 없음
    5) 진입 검증 실패 → ENTRY_VERIFY_FAILED RiskEvent + 알림 (자동 재시도 X)
    6) initial_qty 조회 실패 → 검증 skip (보수적)
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from app.services.execution_service import ExecutionService


def _make_service(db_session, monkeypatch) -> tuple[ExecutionService, list]:
    """ExecutionService + ENTRY 경로 place_order 호출 추적 리스트 반환."""
    from integration.conftest import FakeBinanceClient, FakeTradeClient
    monkeypatch.setattr("app.services.execution_service.BinanceClient", FakeBinanceClient)
    monkeypatch.setattr(
        "app.services.execution_service.BinanceFuturesTradeClient", FakeTradeClient,
    )
    monkeypatch.setattr("app.services.execution_service.time.sleep", lambda *_, **__: None)
    svc = ExecutionService(db_session, api_key="k", api_secret="s", is_testnet=True)
    # ENTRY MARKET 경로 (adapter.place_order → client.place_order) 용 fake + 호출 추적.
    entry_calls: list = []
    def _fake_place_order(payload):
        entry_calls.append(payload)
        return {
            "orderId": 9999, "clientOrderId": payload.get("newClientOrderId", ""),
            "executedQty": payload.get("quantity", "0"),
            "avgPrice": "0", "price": "0",
            "status": "FILLED",
        }
    svc.client.place_order = _fake_place_order
    return svc, entry_calls


# ============================================================================
# A. TP 부분 청산 검증
# ============================================================================
class TestTPPartialCloseVerify:
    """TP1~9 의 부분 청산 호출 (emergency_close_position with quantity < actual)
    이 검증 흐름을 타고 status 는 변경 안 함을 검증.
    """

    def test_tp_partial_close_verify_success_no_status_change(
        self, db_session, make_strategy, fake_binance, fake_trade_client, fake_redis, monkeypatch,
    ):
        """TP1 부분 청산 + 검증 성공 → status 변경 안 함 (caller 가 처리).

        25% 청산 요청 → 거래소 잔량 75% 됨 → 검증 성공 (감소 25 ≥ 25*0.9).
        """
        s = make_strategy(
            symbol_str="ETHUSDT", side="LONG", status="STAGE3_OPEN",
            current_position_qty=Decimal("1.0"),
            avg_entry_price=Decimal("3000"),
        )
        # 진입 시점 거래소 qty=1.0
        fake_binance.set_position(
            "ETHUSDT", position_amt="1.0", entry_price="3000",
            mark_price="3300", position_side="LONG",
        )
        svc, entry_calls = _make_service(db_session, monkeypatch)

        # 검증 시점에 qty=0.75 (25% 청산 시뮬)
        call_count = {"n": 0}
        def _staged_get(symbol=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [{
                    "symbol": "ETHUSDT", "positionSide": "LONG", "positionAmt": "1.0",
                    "entryPrice": "3000", "markPrice": "3300", "unRealizedProfit": "0",
                    "liquidationPrice": "0", "marginType": "cross", "isolatedMargin": "0",
                    "leverage": "10", "breakEvenPrice": "0",
                }]
            return [{
                "symbol": "ETHUSDT", "positionSide": "LONG", "positionAmt": "0.75",
                "entryPrice": "3000", "markPrice": "3300", "unRealizedProfit": "0",
                "liquidationPrice": "0", "marginType": "cross", "isolatedMargin": "0",
                "leverage": "10", "breakEvenPrice": "0",
            }]
        monkeypatch.setattr(svc.client, "get_position_risk", _staged_get)

        # 부분 청산 25%
        svc.emergency_close_position(s.id, quantity=Decimal("0.25"))

        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        # emergency_close 가 STOPPING 으로 set 했지만 검증 성공 — STOPPING 유지.
        # caller (_execute_take_profit) 가 후속으로 TP1_DONE_PARTIAL 로 변경 (이 테스트에선 호출 안 함).
        # 핵심 검증: MANUAL_CLEANUP_REQUIRED 아님 + PARTIAL_CLOSE_VERIFY_FAILED 없음
        assert s2.status != "MANUAL_CLEANUP_REQUIRED"
        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "PARTIAL_CLOSE_VERIFY_FAILED")
        ).scalars().all()
        assert events == []

    def test_tp_partial_close_first_fails_retry_succeeds(
        self, db_session, make_strategy, fake_binance, fake_trade_client, fake_redis, monkeypatch,
    ):
        """TP1 부분 청산 1차 실패 → 재시도 성공 → status 변경 안 함."""
        s = make_strategy(
            symbol_str="BTCUSDT", side="LONG", status="STAGE2_OPEN",
            current_position_qty=Decimal("0.4"),
            avg_entry_price=Decimal("50000"),
        )
        fake_binance.set_position(
            "BTCUSDT", position_amt="0.4", entry_price="50000",
            mark_price="55000", position_side="LONG",
        )
        svc, entry_calls = _make_service(db_session, monkeypatch)

        # 호출 1: emergency_close 의 actual_position 계산 (0.4)
        # 호출 2: 1차 verify (지연 — qty 0.4 그대로)
        # 호출 3: 재시도 verify (반영 — qty 0.3, 0.1 청산)
        call_count = {"n": 0}
        def _staged(symbol=None):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                return [{
                    "symbol": "BTCUSDT", "positionSide": "LONG", "positionAmt": "0.4",
                    "entryPrice": "50000", "markPrice": "55000", "unRealizedProfit": "0",
                    "liquidationPrice": "0", "marginType": "cross", "isolatedMargin": "0",
                    "leverage": "10", "breakEvenPrice": "0",
                }]
            return [{
                "symbol": "BTCUSDT", "positionSide": "LONG", "positionAmt": "0.3",
                "entryPrice": "50000", "markPrice": "55000", "unRealizedProfit": "0",
                "liquidationPrice": "0", "marginType": "cross", "isolatedMargin": "0",
                "leverage": "10", "breakEvenPrice": "0",
            }]
        monkeypatch.setattr(svc.client, "get_position_risk", _staged)

        svc.emergency_close_position(s.id, quantity=Decimal("0.1"))  # 25% of 0.4

        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        assert s2.status != "MANUAL_CLEANUP_REQUIRED"

        # RETRY_ATTEMPTED + RETRY_SUCCEEDED
        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.strategy_instance_id == s.id)
        ).scalars().all()
        types = {e.event_type for e in events}
        assert "EMERGENCY_CLOSE_RETRY_ATTEMPTED" in types
        assert "EMERGENCY_CLOSE_RETRY_SUCCEEDED" in types
        assert "PARTIAL_CLOSE_VERIFY_FAILED" not in types
        assert "EMERGENCY_CLOSE_VERIFY_FAILED" not in types  # 전량 아니므로 이 type 도 안 떠야

    def test_tp_partial_close_both_fail_notifies_without_status_change(
        self, db_session, make_strategy, fake_binance, fake_trade_client, fake_redis, monkeypatch,
    ):
        """TP1 부분 청산 1차+재시도 모두 실패 → PARTIAL_CLOSE_VERIFY_FAILED RiskEvent + 알림.

        핵심: status 가 MANUAL_CLEANUP_REQUIRED 로 안 가야 함 (caller 의 status 덮어쓰기 race 방지).
        """
        s = make_strategy(
            symbol_str="PHBUSDT", side="LONG", status="STAGE2_OPEN",
            current_position_qty=Decimal("1000"),
            avg_entry_price=Decimal("0.06"),
        )
        fake_binance.set_position(
            "PHBUSDT", position_amt="1000", entry_price="0.06",
            mark_price="0.072", position_side="LONG",
        )
        svc, entry_calls = _make_service(db_session, monkeypatch)

        # fake_binance 가 항상 1000 반환 — 부분 청산도 안 됨
        svc.emergency_close_position(s.id, quantity=Decimal("250"))  # 25% of 1000

        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        # MANUAL_CLEANUP_REQUIRED 가 아니어야 함 (부분 청산이라 status 변경 X)
        assert s2.status != "MANUAL_CLEANUP_REQUIRED"

        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.strategy_instance_id == s.id)
        ).scalars().all()
        types = {e.event_type for e in events}
        assert "EMERGENCY_CLOSE_RETRY_ATTEMPTED" in types
        assert "PARTIAL_CLOSE_VERIFY_FAILED" in types
        assert "EMERGENCY_CLOSE_VERIFY_FAILED" not in types  # 전량 아니므로

        # 알림 메시지에 「TP/부분 청산 검증 실패」 키워드
        partial_event = next(e for e in events if e.event_type == "PARTIAL_CLOSE_VERIFY_FAILED")
        assert partial_event.severity == "WARN"
        assert "부분" in partial_event.title or "TP" in partial_event.title

    def test_full_close_still_promotes_to_manual_cleanup(
        self, db_session, make_strategy, fake_binance, fake_trade_client, fake_redis, monkeypatch,
    ):
        """전량 청산 (quantity = actual_position) 실패는 기존대로 MANUAL_CLEANUP_REQUIRED.

        Phase 2 의 기존 동작이 깨지지 않았는지 확인.
        """
        s = make_strategy(
            symbol_str="RONINUSDT", side="SHORT", status="STAGE1_OPEN",
            current_position_qty=Decimal("-87.1"),
            avg_entry_price=Decimal("5.0"),
        )
        fake_binance.set_position(
            "RONINUSDT", position_amt="-87.1", entry_price="5.0",
            mark_price="5.0", position_side="SHORT",
        )
        svc, entry_calls = _make_service(db_session, monkeypatch)

        # 전량 청산 요청 (87.1 = actual_position)
        svc.emergency_close_position(s.id, quantity=Decimal("87.1"))

        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        # 전량 청산 + 둘 다 실패 → MANUAL_CLEANUP_REQUIRED (기존 흐름)
        assert s2.status == "MANUAL_CLEANUP_REQUIRED"
        events = db_session.execute(
            select(RiskEvent)
            .where(RiskEvent.event_type == "EMERGENCY_CLOSE_VERIFY_FAILED")
            .where(RiskEvent.strategy_instance_id == s.id)
        ).scalars().all()
        assert len(events) == 1


# ============================================================================
# B. ENTRY MARKET 검증 (자동 재시도 X — 중복 진입 risk)
# ============================================================================
class TestEntryMarketVerify:
    def test_entry_verify_success_no_riskevent(
        self, db_session, make_strategy, fake_binance, fake_trade_client, fake_redis, monkeypatch,
    ):
        """ENTRY MARKET 후 거래소 qty 증가 정상 → RiskEvent 없음."""
        s = make_strategy(
            symbol_str="ETHUSDT", side="LONG", status="WAITING",
            current_position_qty=Decimal("0"),
            avg_entry_price=None,
        )
        # 초기 거래소 qty=0
        # 호출 1: _place_market_entry 의 initial_qty 조회 → 0
        # 호출 2: _verify_entry_applied 의 post 조회 → 0.5 (의도대로 진입)
        call_count = {"n": 0}
        def _staged(symbol=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return [{
                    "symbol": "ETHUSDT", "positionSide": "LONG", "positionAmt": "0",
                    "entryPrice": "0", "markPrice": "3000", "unRealizedProfit": "0",
                    "liquidationPrice": "0", "marginType": "cross", "isolatedMargin": "0",
                    "leverage": "10", "breakEvenPrice": "0",
                }]
            return [{
                "symbol": "ETHUSDT", "positionSide": "LONG", "positionAmt": "0.5",
                "entryPrice": "3000", "markPrice": "3000", "unRealizedProfit": "0",
                "liquidationPrice": "0", "marginType": "cross", "isolatedMargin": "0",
                "leverage": "10", "breakEvenPrice": "0",
            }]
        svc, entry_calls = _make_service(db_session, monkeypatch)
        monkeypatch.setattr(svc.client, "get_position_risk", _staged)

        # _place_market_entry 직접 호출 (helper)
        svc._place_market_entry(
            s, stage_no=1, qty=Decimal("0.5"),
            current_price=Decimal("3000"), suffix="TEST",
        )

        events = db_session.execute(
            select(RiskEvent)
            .where(RiskEvent.event_type == "ENTRY_VERIFY_FAILED")
            .where(RiskEvent.strategy_instance_id == s.id)
        ).scalars().all()
        assert events == []
        # 발송 1건만 (자동 재시도 안 함)
        assert len(entry_calls) == 1

    def test_entry_verify_failure_emits_riskevent_no_retry(
        self, db_session, make_strategy, fake_binance, fake_trade_client, fake_redis, monkeypatch,
    ):
        """ENTRY MARKET 후 거래소 qty 안 증가 → ENTRY_VERIFY_FAILED + 알림.

        자동 재시도 안 함 (중복 진입 risk) — placed_orders 가 1건이어야.
        """
        s = make_strategy(
            symbol_str="ETHUSDT", side="LONG", status="WAITING",
            current_position_qty=Decimal("0"),
            avg_entry_price=None,
        )
        # 호출 1: initial_qty=0
        # 호출 2: verify — 여전히 0 (체결 안 됨)
        call_count = {"n": 0}
        def _staged(symbol=None):
            call_count["n"] += 1
            return [{
                "symbol": "ETHUSDT", "positionSide": "LONG", "positionAmt": "0",
                "entryPrice": "0", "markPrice": "3000", "unRealizedProfit": "0",
                "liquidationPrice": "0", "marginType": "cross", "isolatedMargin": "0",
                "leverage": "10", "breakEvenPrice": "0",
            }]
        svc, entry_calls = _make_service(db_session, monkeypatch)
        monkeypatch.setattr(svc.client, "get_position_risk", _staged)

        svc._place_market_entry(
            s, stage_no=1, qty=Decimal("0.5"),
            current_price=Decimal("3000"), suffix="TEST",
        )

        events = db_session.execute(
            select(RiskEvent)
            .where(RiskEvent.event_type == "ENTRY_VERIFY_FAILED")
            .where(RiskEvent.strategy_instance_id == s.id)
        ).scalars().all()
        assert len(events) == 1
        assert events[0].severity == "WARN"
        payload = events[0].event_payload
        assert Decimal(payload["initial_qty"]) == Decimal("0")
        assert Decimal(payload["post_qty"]) == Decimal("0")
        assert Decimal(payload["expected_increase"]) == Decimal("0.5")

        # 자동 재시도 X — 1건만 발송됨
        assert len(entry_calls) == 1

    def test_entry_verify_skipped_if_initial_qty_fetch_fails(
        self, db_session, make_strategy, fake_binance, fake_trade_client, fake_redis, monkeypatch,
    ):
        """_fetch_current_position_qty 가 None (네트워크 실패) → 검증 skip, RiskEvent 없음."""
        s = make_strategy(
            symbol_str="BTCUSDT", side="LONG", status="WAITING",
            current_position_qty=Decimal("0"),
        )
        svc, entry_calls = _make_service(db_session, monkeypatch)
        # 첫 호출 (initial_qty) 에서 예외 → None 반환 → 검증 skip
        monkeypatch.setattr(
            svc.client, "get_position_risk",
            MagicMock(side_effect=Exception("network down")),
        )

        svc._place_market_entry(
            s, stage_no=1, qty=Decimal("0.1"),
            current_price=Decimal("50000"), suffix="TEST",
        )

        events = db_session.execute(
            select(RiskEvent)
            .where(RiskEvent.event_type == "ENTRY_VERIFY_FAILED")
            .where(RiskEvent.strategy_instance_id == s.id)
        ).scalars().all()
        assert events == []
        # 주문 자체는 발송됨 (검증만 skip)
        assert len(entry_calls) == 1
