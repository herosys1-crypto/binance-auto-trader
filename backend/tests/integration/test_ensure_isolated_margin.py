"""ensure_isolated_margin — 모든 신규 strategy 진입 시 ISOLATED 자동 설정.

배경 (사용자 결정 2026-05-06):
  「모든 거래를 격리(ISOLATED)로 진행할려고해」
  Binance Futures default 가 CROSS 라 「💰 증거금 추가」 가 -4096 거부됨.
  fix: strategy 진입 직전 (start_stage1 / enter_stage_at_market / add_position_now)
  마다 ensure_isolated_margin 자동 호출.

  Binance 정책: 빈 포지션일 때만 변경 가능. 진입 전 호출이라 안전.
  이미 ISOLATED 면 -4046 응답 — silent 무시 (idempotent).
  실패 시 warning 만 (본 진입 흐름은 진행).
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_binance_client(monkeypatch):
    """change_margin_type 호출을 추적하는 FakeBinanceClient + 다른 호출은 MagicMock."""
    calls = []
    class FakeClient:
        def __init__(self, *a, **kw):
            pass
        def change_margin_type(self, *, symbol, margin_type):
            calls.append({"symbol": symbol, "margin_type": margin_type})
            return {"code": 200, "msg": "success"}
        def __getattr__(self, name):
            # 다른 메서드 호출은 noop MagicMock
            return MagicMock(return_value={})
    monkeypatch.setattr(
        "app.services.execution_service.BinanceClient",
        FakeClient,
    )
    return calls


@pytest.fixture
def fake_trade_client(monkeypatch):
    """BinanceFuturesTradeClient + ExecutionAdapterRouter 등도 mock."""
    monkeypatch.setattr(
        "app.services.execution_service.BinanceFuturesTradeClient",
        lambda *a, **kw: MagicMock(),
    )


class TestEnsureIsolatedMargin:
    def test_calls_change_margin_type_with_isolated(self, db_session, make_strategy, fake_binance_client, fake_trade_client):
        from app.services.execution_service import ExecutionService
        s = make_strategy(symbol_str="BTCUSDT", side="SHORT", status="WAITING",
                          current_position_qty=Decimal("0"))
        svc = ExecutionService(db_session, api_key="k", api_secret="s", is_testnet=True)
        svc.ensure_isolated_margin(s)
        assert len(fake_binance_client) == 1
        assert fake_binance_client[0]["symbol"] == "BTCUSDT"
        assert fake_binance_client[0]["margin_type"] == "ISOLATED"

    def test_already_isolated_4046_silent(self, db_session, make_strategy, monkeypatch, fake_trade_client):
        """이미 ISOLATED → -4046 응답 → silent 무시 (idempotent)."""
        class FakeClient:
            def __init__(self, *a, **kw): pass
            def change_margin_type(self, **kw):
                raise Exception('Binance API error: status=400, code=-4046, msg=No need to change margin type.')
            def __getattr__(self, name): return MagicMock(return_value={})
        monkeypatch.setattr("app.services.execution_service.BinanceClient", FakeClient)
        from app.services.execution_service import ExecutionService
        s = make_strategy(symbol_str="ETHUSDT", side="LONG", status="WAITING",
                          current_position_qty=Decimal("0"))
        svc = ExecutionService(db_session, api_key="k", api_secret="s", is_testnet=True)
        # raise 안 됨 — silent 무시
        svc.ensure_isolated_margin(s)

    def test_other_error_does_not_block_flow(self, db_session, make_strategy, monkeypatch, fake_trade_client):
        """다른 에러 (포지션 보유 -4048 등) 도 silent — 본 진입 흐름은 진행."""
        class FakeClient:
            def __init__(self, *a, **kw): pass
            def change_margin_type(self, **kw):
                raise Exception('Binance API error: status=400, code=-4048, msg=Margin type cannot be changed if there exists position.')
            def __getattr__(self, name): return MagicMock(return_value={})
        monkeypatch.setattr("app.services.execution_service.BinanceClient", FakeClient)
        from app.services.execution_service import ExecutionService
        s = make_strategy(symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN",
                          current_position_qty=Decimal("-0.5"))
        svc = ExecutionService(db_session, api_key="k", api_secret="s", is_testnet=True)
        # raise 안 됨 — warning 만 + 정상 진행
        svc.ensure_isolated_margin(s)


class TestExecutionServiceCallsEnsureIsolatedMargin:
    """3 진입점 (start_stage1 / enter_stage_at_market / add_position_now) 모두 호출 검증.

    정적 분석 — 코드에 ensure_isolated_margin 호출이 있는지 grep.
    """
    def test_start_stage1_calls_ensure_isolated(self):
        import inspect
        from app.services.execution_service import ExecutionService
        src = inspect.getsource(ExecutionService.start_stage1)
        assert "ensure_isolated_margin" in src, (
            "start_stage1 에 ensure_isolated_margin 호출 누락"
        )

    def test_enter_stage_at_market_calls_ensure_isolated(self):
        import inspect
        from app.services.execution_service import ExecutionService
        src = inspect.getsource(ExecutionService.enter_stage_at_market)
        assert "ensure_isolated_margin" in src, (
            "enter_stage_at_market 에 ensure_isolated_margin 호출 누락"
        )

    def test_add_position_now_calls_ensure_isolated(self):
        import inspect
        from app.services.execution_service import ExecutionService
        src = inspect.getsource(ExecutionService.add_position_now)
        assert "ensure_isolated_margin" in src, (
            "add_position_now 에 ensure_isolated_margin 호출 누락"
        )
