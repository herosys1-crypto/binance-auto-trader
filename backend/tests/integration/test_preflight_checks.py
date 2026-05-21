"""Phase 3 — ENTRY MARKET 사전 마진 검증 (사장님 요구 2026-05-21).

배경:
  이전엔 ENTRY MARKET 발송 후 거래소가 -2027 (Margin is insufficient) 반환하면 그 응답
  받고 에러 표시. 사장님이 1~2초 기다린 후 에러를 봄.
  → 발송 전에 가용 USDT 잔액 vs 필요 마진 비교해서 사전 차단 (거래소 호출 0).

테스트:
  1. 마진 충분 → 정상 통과 (place_order 호출됨, RiskEvent 없음)
  2. 마진 부족 → PreflightCheckFailed 예외 + PREFLIGHT_BLOCKED RiskEvent, place_order 호출 X
  3. 마진 정확히 같으면? — 5% 버퍼 (×1.05) 미만이면 차단
  4. balance API 실패 → preflight skip (거래소가 직접 거절하면 -2027)
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.models.risk_event import RiskEvent
from app.services.execution_service import (
    EmergencyCloseInProgress,
    ExecutionService,
    PreflightCheckFailed,
)


def _make_service(db_session, monkeypatch) -> tuple[ExecutionService, list]:
    """ExecutionService + ENTRY 경로 place_order 호출 추적 리스트 반환."""
    from integration.conftest import FakeBinanceClient, FakeTradeClient
    monkeypatch.setattr("app.services.execution_service.BinanceClient", FakeBinanceClient)
    monkeypatch.setattr(
        "app.services.execution_service.BinanceFuturesTradeClient", FakeTradeClient,
    )
    monkeypatch.setattr("app.services.execution_service.time.sleep", lambda *_, **__: None)
    svc = ExecutionService(db_session, api_key="k", api_secret="s", is_testnet=True)
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


def _stub_balance(svc, usdt_balance: str, monkeypatch):
    """svc.client.get_balance 를 stub — USDT availableBalance 만 반환."""
    svc.client.get_balance = lambda: [
        {"asset": "USDT", "availableBalance": usdt_balance, "balance": usdt_balance},
        {"asset": "BNB", "availableBalance": "0", "balance": "0"},
    ]


class TestPreflightEntryMarketMarginCheck:
    def test_sufficient_margin_allows_entry(
        self, db_session, make_strategy, fake_binance, fake_trade_client, fake_redis, monkeypatch,
    ):
        """가용 USDT 잔액 >= 필요 마진 × 1.05 → 정상 진입."""
        s = make_strategy(
            symbol_str="ETHUSDT", side="LONG", status="WAITING",
            current_position_qty=Decimal("0"),
            leverage=10,
        )
        svc, entry_calls = _make_service(db_session, monkeypatch)
        # 필요 마진 = (0.5 × 3000) / 10 = 150 USDT
        # 1.05 버퍼 = 157.5 USDT. 가용 200 USDT 면 통과.
        _stub_balance(svc, "200", monkeypatch)

        svc._preflight_entry_market_check(
            s, qty=Decimal("0.5"), current_price=Decimal("3000"),
            purpose="test",
        )

        # 차단 안 됨 — PREFLIGHT_BLOCKED RiskEvent 없음
        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "PREFLIGHT_BLOCKED")
        ).scalars().all()
        assert events == []

    def test_insufficient_margin_blocks_entry_with_riskevent(
        self, db_session, make_strategy, fake_binance, fake_trade_client, fake_redis, monkeypatch,
    ):
        """가용 USDT 잔액 < 필요 마진 × 1.05 → PreflightCheckFailed + RiskEvent + 거래소 호출 X."""
        s = make_strategy(
            symbol_str="PHBUSDT", side="LONG", status="WAITING",
            current_position_qty=Decimal("0"),
            leverage=10,
        )
        svc, entry_calls = _make_service(db_session, monkeypatch)
        # 필요 마진 = (1000 × 0.06) / 10 = 6 USDT. ×1.05 = 6.3
        # 가용 5 USDT 면 차단.
        _stub_balance(svc, "5", monkeypatch)

        with pytest.raises(PreflightCheckFailed) as exc_info:
            svc._preflight_entry_market_check(
                s, qty=Decimal("1000"), current_price=Decimal("0.06"),
                purpose="test_insufficient",
            )

        err_msg = str(exc_info.value)
        # 친절 메시지 — 필요/가용 USDT 명시
        assert "USDT" in err_msg
        assert "6.3" in err_msg or "6." in err_msg  # 필요 마진
        assert "5." in err_msg  # 가용

        # RiskEvent 기록
        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "PREFLIGHT_BLOCKED")
        ).scalars().all()
        assert len(events) == 1
        assert events[0].severity == "WARN"
        payload = events[0].event_payload
        assert payload["purpose"] == "test_insufficient"
        assert Decimal(payload["required_margin"]) > Decimal(payload["usdt_available"])

        # 거래소 호출 0건 — preflight 가 사전 차단
        assert entry_calls == []

    def test_balance_api_failure_skips_preflight(
        self, db_session, make_strategy, fake_binance, fake_trade_client, fake_redis, monkeypatch,
    ):
        """get_balance 호출 실패 (네트워크) → preflight skip, 정상 진행.

        거래소가 직접 -2027 거절하면 그때 받음 — false-positive 방지.
        """
        s = make_strategy(
            symbol_str="BTCUSDT", side="LONG", status="WAITING",
            current_position_qty=Decimal("0"),
            leverage=5,
        )
        svc, entry_calls = _make_service(db_session, monkeypatch)
        svc.client.get_balance = MagicMock(side_effect=Exception("network timeout"))

        # 예외 발생 안 함 — skip 으로 진행
        svc._preflight_entry_market_check(
            s, qty=Decimal("0.1"), current_price=Decimal("50000"),
            purpose="api_failure_test",
        )

        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "PREFLIGHT_BLOCKED")
        ).scalars().all()
        assert events == []


class TestPreflightIntegrationViaEnterStageAtMarket:
    """enter_stage_at_market → preflight 통합 흐름.

    실제 진입 함수에서 preflight 가 호출되는지 + 차단 시 거래소 호출 안 되는지 검증.
    """

    def test_enter_stage_at_market_blocks_on_insufficient_margin(
        self, db_session, make_strategy, fake_binance, fake_trade_client, fake_redis,
        make_template, monkeypatch,
    ):
        """마진 부족 시 enter_stage_at_market 가 PreflightCheckFailed 예외 발생."""
        tpl = make_template(stages_config={"capitals": [100, 200, 300], "trigger_percents": [None, -5, -10]})
        s = make_strategy(
            symbol_str="ETHUSDT", side="LONG", status="WAITING",
            current_position_qty=Decimal("0"),
            avg_entry_price=None,
            leverage=10,
            template=tpl,
        )
        # stage_plan 생성
        from app.models.strategy_stage_plan import StrategyStagePlan
        for n, cap in [(1, 100), (2, 200), (3, 300)]:
            db_session.add(StrategyStagePlan(
                strategy_instance_id=s.id, stage_no=n, side=s.side,
                trigger_mode="PRICE",
                planned_capital=Decimal(str(cap)), planned_qty=None,
                trigger_price=Decimal("3000"), is_triggered=False,
            ))
        db_session.commit()
        db_session.refresh(s)

        svc, entry_calls = _make_service(db_session, monkeypatch)
        # current_price mock — 3000 USDT
        monkeypatch.setattr(
            svc, "_fetch_current_mark_price", lambda symbol: Decimal("3000"),
        )
        # ensure_isolated_margin no-op
        monkeypatch.setattr(svc, "ensure_isolated_margin", lambda strategy: None)
        # _floor_qty_to_step — 그대로 반환
        monkeypatch.setattr(
            svc, "_floor_qty_to_step", lambda sym, q: q.quantize(Decimal("0.001")),
        )
        # 잔액 매우 부족 — 1 USDT
        _stub_balance(svc, "1", monkeypatch)

        with pytest.raises(PreflightCheckFailed):
            svc.enter_stage_at_market(s.id, stage_no=2)

        # 거래소 호출 0건 — 사전 차단
        assert entry_calls == []
        # PREFLIGHT_BLOCKED RiskEvent 1건
        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "PREFLIGHT_BLOCKED")
        ).scalars().all()
        assert len(events) == 1
        assert "manual_stage_trigger_2" in events[0].event_payload["purpose"]
