"""orphan 감지 시 REENTRY_READY race window 면 KS 보류 (#120 사례).

배경:
  #120 DYDXUSDT 의 EXIT FILLED 처리에서 DB 는 잔량 0 으로 판단해 REENTRY_READY
  마킹. 그러나 거래소엔 245 잔량이 남아있던 race window 동안 zombie scan 이
  실행 → matching ACTIVE_LIKE strategy 없음 → orphan → KS 즉시 발동.

  이 테스트는 zombie_guardian.detect_orphan_exchange_positions 가:
  - REENTRY_READY (최근 5분 내) + 같은 symbol/side 매칭 시 → KS 보류 + WARN
  - REENTRY_READY 더 오래된 (>5분) → orphan KS 정상 발동
  - STOPPED / COMPLETED → 항상 orphan KS (REENTRY_READY 와 다른 카테고리)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.account_kill_switch import AccountKillSwitch
from app.models.risk_event import RiskEvent
from app.workers.reconcile_worker import _do_reconcile


class TestOrphanReentryRaceDefer:
    def test_recent_reentry_ready_defers_kill_switch(
        self, db_session, make_strategy, fake_binance, identity_decrypt, patched_sessionlocal,
    ):
        """REENTRY_READY (최근 1분) + 거래소 잔량 → race deferred, KS 미발동."""
        s = make_strategy(
            symbol_str="DYDXUSDT", side="SHORT", status="REENTRY_READY",
            current_position_qty=Decimal("0"),
        )
        # 거래소엔 245 잔량 (race window — exit 직후)
        fake_binance.set_position(
            "DYDXUSDT", position_amt="-245.0", position_side="SHORT",
            entry_price="0.204", mark_price="0.184",
        )

        _do_reconcile(identity_decrypt)

        # KS 발동 안 함
        ks = db_session.execute(select(AccountKillSwitch)).scalar_one_or_none()
        assert ks is None, "REENTRY_READY race window 에서 KS 발동 차단돼야 함"

        # CRITICAL orphan event 도 없음
        critical = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "ZOMBIE_ORPHAN_EXCHANGE_POSITION")
        ).scalars().all()
        assert len(critical) == 0

        # 대신 WARN 이벤트가 기록됨 (운영자 가시성)
        warn = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "ZOMBIE_ORPHAN_RACE_DEFERRED")
        ).scalars().all()
        assert len(warn) == 1
        assert warn[0].severity == "WARN"
        assert warn[0].strategy_instance_id == s.id

    def test_old_reentry_ready_still_triggers_orphan(
        self, db_session, make_strategy, fake_binance, identity_decrypt, patched_sessionlocal,
    ):
        """REENTRY_READY 가 5분 이상 오래된 경우 → race window 끝, 진짜 orphan."""
        s = make_strategy(
            symbol_str="DYDXUSDT", side="SHORT", status="REENTRY_READY",
            current_position_qty=Decimal("0"),
        )
        # updated_at 을 10분 전으로 설정
        s.updated_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        db_session.commit()

        fake_binance.set_position(
            "DYDXUSDT", position_amt="-245.0", position_side="SHORT",
            entry_price="0.204", mark_price="0.184",
        )

        _do_reconcile(identity_decrypt)

        # KS 발동 (race window 지났음)
        ks = db_session.execute(select(AccountKillSwitch)).scalar_one_or_none()
        assert ks is not None
        assert ks.is_enabled is True

        # CRITICAL orphan event
        critical = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "ZOMBIE_ORPHAN_EXCHANGE_POSITION")
        ).scalars().all()
        assert len(critical) == 1

    def test_stopped_strategy_always_triggers_orphan(
        self, db_session, make_strategy, fake_binance, identity_decrypt, patched_sessionlocal,
    ):
        """STOPPED 는 정상 종료라 거래소 잔량은 항상 진짜 orphan (race defer 안 함)."""
        make_strategy(
            symbol_str="ETHUSDT", side="LONG", status="STOPPED",
            current_position_qty=Decimal("0"),
        )
        fake_binance.set_position(
            "ETHUSDT", position_amt="2.0", position_side="LONG",
            entry_price="3000", mark_price="3100",
        )

        _do_reconcile(identity_decrypt)

        # KS 발동 (STOPPED 는 race defer 안 함)
        ks = db_session.execute(select(AccountKillSwitch)).scalar_one_or_none()
        assert ks is not None
        critical = db_session.execute(
            select(RiskEvent).where(RiskEvent.event_type == "ZOMBIE_ORPHAN_EXCHANGE_POSITION")
        ).scalars().all()
        assert len(critical) == 1
