"""reconcile_worker Phase 2 — 거래소 orphan 포지션 감지 통합.

시나리오: Binance 에 포지션이 있는데 DB 에 매칭 active strategy 가 없음.
원인: 사용자 수동 진입, DB 손상, 시스템 미인지 진입 등.
정책: detect_orphan_exchange_positions 가 발견 → CRITICAL RiskEvent +
      AccountKillSwitch 자동 발동 → 신규 주문 차단.

zombie_guardian.detect_orphan_exchange_positions 가 모든 active ExchangeAccount
에 대해 client.get_position_risk() (no-arg, 전체) 를 호출 → positionAmt != 0 인
포지션마다 매칭 active strategy 가 있는지 확인 → 없으면 escalate.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.account_kill_switch import AccountKillSwitch
from app.models.risk_event import RiskEvent
from app.workers.reconcile_worker import _do_reconcile


class TestOrphanExchangePositionDetection:
    def test_orphan_position_triggers_kill_switch_and_critical_event(
        self,
        db_session,
        make_exchange_account,
        fake_binance,
        identity_decrypt,
        patched_sessionlocal,
    ) -> None:
        """거래소에 BTCUSDT SHORT 있는데 DB 에 매칭 strategy 없음 → kill-switch + CRITICAL."""
        # given: ExchangeAccount 만 있고 strategy 는 없음
        account = make_exchange_account()
        # 거래소 포지션 (orphan): set_position 이 ALL 응답에도 자동 추가
        fake_binance.set_position(
            "BTCUSDT",
            position_amt="-0.5",  # SHORT 0.5 BTC
            entry_price="48000",
            mark_price="47500",
            unrealized_pnl="2.5",
            position_side="SHORT",
        )

        # when
        _do_reconcile(identity_decrypt)

        # then: CRITICAL RiskEvent 1건 (strategy_instance_id 가 NULL — 시스템 이벤트)
        events = db_session.execute(
            select(RiskEvent).where(
                RiskEvent.event_type == "ZOMBIE_ORPHAN_EXCHANGE_POSITION"
            )
        ).scalars().all()
        assert len(events) == 1
        assert events[0].severity == "CRITICAL"
        assert events[0].strategy_instance_id is None  # 시스템 레벨 이벤트
        # payload 에 거래소 스냅샷 포함
        payload = events[0].event_payload or {}
        assert payload.get("account_id") == account.id
        snapshot = payload.get("exchange_snapshot") or {}
        assert snapshot.get("symbol") == "BTCUSDT"
        assert snapshot.get("positionSide") == "SHORT"
        assert snapshot.get("positionAmt") == "-0.5"

        # AccountKillSwitch 자동 발동
        ks = db_session.execute(
            select(AccountKillSwitch).where(
                AccountKillSwitch.exchange_account_id == account.id
            )
        ).scalar_one_or_none()
        assert ks is not None
        assert ks.is_enabled is True
        assert ks.reason_code is not None
        assert ks.reason_code.startswith("ZOMBIE:ORPHAN_EXCHANGE_POSITION")
        assert ks.triggered_at is not None

    def test_matched_active_strategy_does_not_trigger_orphan(
        self,
        db_session,
        make_strategy,
        fake_binance,
        identity_decrypt,
        patched_sessionlocal,
    ) -> None:
        """active strategy 가 있으면 거래소 포지션은 정상 — orphan 발동 안 함."""
        strategy = make_strategy(
            symbol_str="BTCUSDT",
            side="SHORT",
            status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
        )
        fake_binance.set_position(
            "BTCUSDT", position_amt="-0.5", position_side="SHORT",
            entry_price="48000", mark_price="48000",
        )

        _do_reconcile(identity_decrypt)

        # orphan 이벤트 없음
        events = db_session.execute(
            select(RiskEvent).where(
                RiskEvent.event_type == "ZOMBIE_ORPHAN_EXCHANGE_POSITION"
            )
        ).scalars().all()
        assert len(events) == 0

        # kill-switch 도 발동 안 함
        ks = db_session.execute(select(AccountKillSwitch)).scalar_one_or_none()
        assert ks is None

    def test_zero_amount_exchange_position_is_ignored(
        self,
        db_session,
        make_exchange_account,
        fake_binance,
        identity_decrypt,
        patched_sessionlocal,
    ) -> None:
        """positionAmt=0 placeholder 는 orphan 으로 간주하지 않음."""
        make_exchange_account()
        # Binance 가 positionAmt="0" placeholder 만 보내는 경우 (실 포지션 없음)
        fake_binance.set_position(
            "BTCUSDT", position_amt="0", position_side="SHORT",
        )

        _do_reconcile(identity_decrypt)

        events = db_session.execute(
            select(RiskEvent).where(
                RiskEvent.event_type == "ZOMBIE_ORPHAN_EXCHANGE_POSITION"
            )
        ).scalars().all()
        assert len(events) == 0

    def test_orphan_with_existing_terminal_strategy_still_orphans(
        self,
        db_session,
        make_strategy,
        fake_binance,
        identity_decrypt,
        patched_sessionlocal,
    ) -> None:
        """STOPPED strategy 는 active 가 아니므로 같은 심볼 거래소 포지션은 orphan."""
        strategy = make_strategy(
            symbol_str="ETHUSDT",
            side="LONG",
            status="STOPPED",  # 종료된 strategy
            current_position_qty=Decimal("0"),
        )
        # 거래소엔 포지션 있음 (예: 사용자가 STOPPED 후 수동 진입)
        fake_binance.set_position(
            "ETHUSDT", position_amt="2.0", position_side="LONG",
            entry_price="3000", mark_price="3100",
        )

        _do_reconcile(identity_decrypt)

        events = db_session.execute(
            select(RiskEvent).where(
                RiskEvent.event_type == "ZOMBIE_ORPHAN_EXCHANGE_POSITION"
            )
        ).scalars().all()
        assert len(events) == 1
