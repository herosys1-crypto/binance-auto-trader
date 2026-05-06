"""증거금 추가 + -50% 손실 임계 알림 통합 (사용자 요청 2026-05-04).

기능 1) 각 전략에 증거금 추가:
- POST /strategies/{id}/add-margin → ExecutionService.add_position_margin
- BinanceClient.add_position_margin (POST /fapi/v1/positionMargin/modify, type=1)
- 검증: 포지션 보유, amount > 0, 거래소 거절 시 친절 메시지 + RiskEvent

기능 2) -50% ROI 손실 임계 알림:
- risk_service.evaluate_take_profit_level 안에서 max_loss_pct 임계 교차 1회 감지
- prev > -50 (or None) AND new ≤ -50 → RiskEvent + Telegram 알림
- 이미 교차한 후엔 재알림 안 함
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.strategies import AddMarginRequest, add_margin_to_strategy
from app.models.notification import Notification
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from app.services.execution_service import ExecutionService
from app.services.risk_service import LOSS_ALERT_THRESHOLD, RiskService


# ============================================================================
# 증거금 추가 — ExecutionService 단위
# ============================================================================
class TestAddPositionMarginService:
    @pytest.fixture
    def fake_client(self, monkeypatch):
        """ExecutionService 의 BinanceClient 를 fake 로 교체."""
        captured: list[dict] = []

        class _FakeClient:
            def __init__(self, *a, **kw):
                pass

            def add_position_margin(self, *, symbol, position_side, amount, margin_type):
                captured.append({
                    "symbol": symbol,
                    "position_side": position_side,
                    "amount": amount,
                    "margin_type": margin_type,
                })
                return {"code": 200, "msg": "Successfully modify position margin", "amount": amount, "type": margin_type}

        # ExecutionService 가 self.client 로 BinanceClient 인스턴스화 → 패치
        monkeypatch.setattr("app.services.execution_service.BinanceClient", _FakeClient)
        # FakeTradeClient 는 trade_client 로 별개 — 안 씀
        return captured

    def test_add_margin_success(
        self, db_session, make_strategy, fake_client, fake_trade_client
    ) -> None:
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
        )
        svc = ExecutionService(db_session, api_key="k", api_secret="s", is_testnet=True)
        resp = svc.add_position_margin(strategy.id, amount=Decimal("10"))

        assert len(fake_client) == 1
        call = fake_client[0]
        assert call["symbol"] == "BTCUSDT"
        assert call["position_side"] == "SHORT"
        assert call["margin_type"] == 1  # add
        assert Decimal(call["amount"]) == Decimal("10")

        # RiskEvent INFO 기록
        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.strategy_instance_id == strategy.id)
        ).scalars().all()
        assert any(e.event_type == "ADD_MARGIN_SUCCESS" for e in events)
        # Notification (Telegram) 기록 — DB 에 PENDING/SENT (Telegram disabled in test)
        notifs = db_session.execute(
            select(Notification).where(Notification.strategy_instance_id == strategy.id)
        ).scalars().all()
        assert any("증거금" in (n.title or "") for n in notifs)

    def test_zero_amount_rejected(
        self, db_session, make_strategy, fake_client, fake_trade_client
    ) -> None:
        strategy = make_strategy(symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
                                 current_position_qty=Decimal("-0.5"))
        svc = ExecutionService(db_session, api_key="k", api_secret="s", is_testnet=True)
        with pytest.raises(ValueError, match="양수"):
            svc.add_position_margin(strategy.id, amount=Decimal("0"))
        assert len(fake_client) == 0

    def test_no_position_rejected(
        self, db_session, make_strategy, fake_client, fake_trade_client
    ) -> None:
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="WAITING",
            current_position_qty=Decimal("0"),  # 포지션 없음
        )
        svc = ExecutionService(db_session, api_key="k", api_secret="s", is_testnet=True)
        with pytest.raises(ValueError, match="포지션 없음"):
            svc.add_position_margin(strategy.id, amount=Decimal("10"))
        assert len(fake_client) == 0

    def test_cross_mode_error_friendly_message(
        self, db_session, make_strategy, fake_trade_client, monkeypatch
    ) -> None:
        """CROSS 모드 거절 (-4046) 시 친절한 에러 메시지 + RiskEvent ERROR."""
        class _FailingClient:
            def __init__(self, *a, **kw): pass
            def add_position_margin(self, **kw):
                raise Exception('{"code":-4046,"msg":"No need to change margin type."}')
        monkeypatch.setattr("app.services.execution_service.BinanceClient", _FailingClient)

        strategy = make_strategy(symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
                                 current_position_qty=Decimal("-0.5"))
        svc = ExecutionService(db_session, api_key="k", api_secret="s", is_testnet=True)
        with pytest.raises(ValueError) as ei:
            svc.add_position_margin(strategy.id, amount=Decimal("10"))
        assert "ISOLATED" in str(ei.value) or "CROSS" in str(ei.value)

        # RiskEvent ERROR 기록
        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "ADD_MARGIN_FAILED")
        ).scalars().all()
        assert len(events) == 1
        assert events[0].severity == "ERROR"

    def test_isolated_only_error_4096_friendly_message(
        self, db_session, make_strategy, fake_trade_client, monkeypatch
    ) -> None:
        """2026-05-06 사용자 보고 — Binance -4096 'Add margin only support for isolated
        position' 도 친절 메시지 매핑돼야 함. 이전엔 -4046 만 매핑되어 raw 메시지 노출."""
        class _FailingClient:
            def __init__(self, *a, **kw): pass
            def add_position_margin(self, **kw):
                raise Exception('Binance API error: status=400, code=-4096, msg=Add margin only support for isolated position.')
        monkeypatch.setattr("app.services.execution_service.BinanceClient", _FailingClient)

        strategy = make_strategy(symbol_str="ETHUSDT", side="LONG", status="STAGE1_OPEN",
                                 current_position_qty=Decimal("1"))
        svc = ExecutionService(db_session, api_key="k", api_secret="s", is_testnet=True)
        with pytest.raises(ValueError) as ei:
            svc.add_position_margin(strategy.id, amount=Decimal("50"))
        # 친절 메시지 가드: ISOLATED 안내 + Binance UI 절차 명시
        msg = str(ei.value)
        assert "ISOLATED" in msg, f"친절 메시지에 ISOLATED 안내 없음: {msg}"
        assert "Binance UI" in msg or "마진 모드" in msg or "포지션을 종료" in msg, (
            f"운영 가이드 누락: {msg}"
        )


# ============================================================================
# 증거금 추가 — API endpoint
# ============================================================================
class TestAddMarginEndpoint:
    def test_endpoint_returns_404_for_other_user(
        self, db_session, make_user, make_strategy
    ) -> None:
        owner = make_user()
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
            user=owner,
        )
        intruder = make_user()
        with pytest.raises(HTTPException) as ei:
            add_margin_to_strategy(
                strategy_id=strategy.id,
                payload=AddMarginRequest(amount=Decimal("10")),
                db=db_session,
                user_id=intruder.id,
            )
        assert ei.value.status_code == 404

    def test_endpoint_validates_positive_amount(self) -> None:
        """Pydantic gt=0 가드."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AddMarginRequest(amount=Decimal("0"))
        with pytest.raises(ValidationError):
            AddMarginRequest(amount=Decimal("-5"))


# ============================================================================
# 2026-05-06 (사용자 요청): 증거금/포지션 추가 시 텔레그램 알림 발송 검증
# ============================================================================
class TestNotificationOnAddMarginAndPosition:
    def test_send_margin_added_alert_creates_notification(
        self, db_session, make_strategy
    ) -> None:
        """NotificationService.send_margin_added_alert 가 Notification row 생성."""
        from app.services.notification_service import NotificationService
        from app.models.notification import Notification
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN",
            current_position_qty=Decimal("-0.5"),
        )
        ns = NotificationService(db_session)
        ns.send_margin_added_alert(
            strategy_instance_id=s.id, symbol="BTCUSDT", side="SHORT",
            amount=Decimal("100"),
        )
        rows = db_session.query(Notification).filter_by(strategy_instance_id=s.id).all()
        assert len(rows) == 1
        n = rows[0]
        assert "[증거금 추가]" in n.title
        assert "100" in n.body
        assert n.channel == "TELEGRAM"

    def test_send_position_added_alert_market(
        self, db_session, make_strategy
    ) -> None:
        """포지션 추가 (MARKET) — title + body 검증."""
        from app.services.notification_service import NotificationService
        from app.models.notification import Notification
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN",
            current_position_qty=Decimal("-0.5"),
        )
        ns = NotificationService(db_session)
        ns.send_position_added_alert(
            strategy_instance_id=s.id, symbol="BTCUSDT", side="SHORT",
            amount_usdt=Decimal("250"), order_type="MARKET",
            qty=Decimal("0.005"), limit_price=None,
        )
        n = db_session.query(Notification).filter_by(strategy_instance_id=s.id).one()
        assert "[포지션 추가]" in n.title
        assert "MARKET" in n.title
        assert "250" in n.body
        assert "시장가" in n.body

    def test_send_position_added_alert_limit_includes_price(
        self, db_session, make_strategy
    ) -> None:
        """포지션 추가 (LIMIT) — body 에 지정가 포함."""
        from app.services.notification_service import NotificationService
        from app.models.notification import Notification
        s = make_strategy(
            symbol_str="ETHUSDT", side="LONG", status="STAGE1_OPEN",
            current_position_qty=Decimal("1"),
        )
        ns = NotificationService(db_session)
        ns.send_position_added_alert(
            strategy_instance_id=s.id, symbol="ETHUSDT", side="LONG",
            amount_usdt=Decimal("500"), order_type="LIMIT",
            qty=Decimal("0.5"), limit_price=Decimal("2500"),
        )
        n = db_session.query(Notification).filter_by(strategy_instance_id=s.id).one()
        assert "[포지션 추가]" in n.title
        assert "LIMIT" in n.title
        assert "2,500" in n.body or "2500" in n.body  # _fmt_num 의 thousand separator 호환
        assert "지정가" in n.body


# ============================================================================
# -50% ROI 손실 임계 알림
# ============================================================================
class TestLossThresholdAlert:
    """RiskService._maybe_send_loss_threshold_alert — prev/new max_loss 비교."""

    def _make_strategy_obj(self, **overrides):
        """RiskEvent 추가/flush 검증 용 SimpleNamespace 객체."""
        from types import SimpleNamespace
        defaults = dict(
            id=42, symbol="BTCUSDT", side="SHORT",
            max_loss_pct=None, max_profit_pct=None,
            crisis_mode_triggered_at=None,
        )
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_first_crossing_to_minus_50_sends_alert(
        self, db_session, make_strategy, monkeypatch
    ) -> None:
        captured: list[dict] = []

        def _spy_alert(self, **kwargs):
            captured.append(kwargs)
            from app.models.notification import Notification as _N
            return _N(strategy_instance_id=kwargs.get("strategy_instance_id"),
                     channel="TELEGRAM", title=kwargs.get("symbol", ""), body="x", send_status="SENT")

        from app.services.notification_service import NotificationService
        monkeypatch.setattr(NotificationService, "send_loss_threshold_alert", _spy_alert)

        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
        )
        svc = RiskService(db_session)
        # prev=None, new=-55 → 첫 교차 → 알림 발송
        svc._maybe_send_loss_threshold_alert(strategy, None, Decimal("-55"))

        assert len(captured) == 1
        assert captured[0]["pnl_pct"] == "-55"
        # RiskEvent 기록
        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "LOSS_THRESHOLD_50PCT_REACHED")
        ).scalars().all()
        assert len(events) == 1
        assert events[0].severity == "WARNING"

    def test_already_crossed_no_realert(
        self, db_session, make_strategy, monkeypatch
    ) -> None:
        captured: list[dict] = []

        def _spy(self, **kw):
            captured.append(kw)
            from app.models.notification import Notification as _N
            return _N(strategy_instance_id=kw.get("strategy_instance_id"),
                     channel="TELEGRAM", title="x", body="x", send_status="SENT")

        from app.services.notification_service import NotificationService
        monkeypatch.setattr(NotificationService, "send_loss_threshold_alert", _spy)

        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
        )
        svc = RiskService(db_session)
        # prev=-55 (이미 교차), new=-60 (더 깊어짐) → 재알림 안 함
        svc._maybe_send_loss_threshold_alert(strategy, Decimal("-55"), Decimal("-60"))
        assert len(captured) == 0

    def test_above_threshold_no_alert(
        self, db_session, make_strategy, monkeypatch
    ) -> None:
        captured: list[dict] = []

        def _spy(self, **kw):
            captured.append(kw)
            from app.models.notification import Notification as _N
            return _N(strategy_instance_id=1, channel="TELEGRAM", title="x", body="x", send_status="SENT")

        from app.services.notification_service import NotificationService
        monkeypatch.setattr(NotificationService, "send_loss_threshold_alert", _spy)

        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
        )
        svc = RiskService(db_session)
        # new=-30 → 임계(-50) 미도달 → 알림 안 함
        svc._maybe_send_loss_threshold_alert(strategy, None, Decimal("-30"))
        assert len(captured) == 0

    def test_threshold_constant_value(self) -> None:
        """임계가 -50 (사용자 요청) 인지 확인."""
        assert LOSS_ALERT_THRESHOLD == Decimal("-50")

    def test_exact_threshold_triggers(
        self, db_session, make_strategy, monkeypatch
    ) -> None:
        """new = -50.00 정확히 일치 → 교차로 간주."""
        captured: list[dict] = []

        def _spy(self, **kw):
            captured.append(kw)
            from app.models.notification import Notification as _N
            return _N(strategy_instance_id=1, channel="TELEGRAM", title="x", body="x", send_status="SENT")

        from app.services.notification_service import NotificationService
        monkeypatch.setattr(NotificationService, "send_loss_threshold_alert", _spy)

        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
        )
        svc = RiskService(db_session)
        svc._maybe_send_loss_threshold_alert(strategy, Decimal("-49.9"), Decimal("-50"))
        assert len(captured) == 1

    def test_recovery_then_re_crossing_no_realert(
        self, db_session, make_strategy, monkeypatch
    ) -> None:
        """한번 교차한 후 회복(-30) → 다시 -55 가도 재알림 안 함.

        max_loss_pct 는 monotonic (deepest only updates) 이므로 prev_max_loss
        는 -55 그대로 → 재교차 검사에서 prev ≤ -50 으로 간주 → skip.
        """
        captured: list[dict] = []

        def _spy(self, **kw):
            captured.append(kw)
            from app.models.notification import Notification as _N
            return _N(strategy_instance_id=1, channel="TELEGRAM", title="x", body="x", send_status="SENT")

        from app.services.notification_service import NotificationService
        monkeypatch.setattr(NotificationService, "send_loss_threshold_alert", _spy)

        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
        )
        svc = RiskService(db_session)
        svc._maybe_send_loss_threshold_alert(strategy, Decimal("-55"), Decimal("-60"))
        assert len(captured) == 0  # 이미 교차됨
