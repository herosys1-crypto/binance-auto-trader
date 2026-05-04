"""reconcile_worker Phase 1 (a) — pre_pass_dedup 통합.

같은 (account, symbol, side) 에 active strategy 가 2개 이상 → 가장 최근 1개만
남기고 나머지 STOPPED 강등. Binance hedge mode 의 통합 포지션 보호 — 두 strategy
가 같은 거래소 포지션을 점유하는 race 방지.

운영 사례 #89/#90 (LABUSDT) — race window 에 같은 심볼/방향으로 신규 진입되어
좀비 발생. 후속 reconcile 사이클에서 자동 강등으로 정합성 회복.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from app.workers.reconcile_worker import _do_reconcile


class TestDuplicateActiveDedup:
    def test_duplicate_active_keeps_newest_demotes_older_via_reconcile(
        self,
        db_session,
        make_user,
        make_exchange_account,
        make_symbol,
        make_template,
        make_strategy,
        fake_binance,
        identity_decrypt,
        patched_sessionlocal,
    ) -> None:
        # given: 같은 (acc, BTCUSDT, SHORT) active 2개 — older + newer
        u = make_user()
        ea = make_exchange_account(user=u)
        sym = make_symbol("BTCUSDT")
        tpl = make_template()

        older = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN",
            current_position_qty=Decimal("-0.3"),
            user=u, exchange_account=ea, symbol_obj=sym, template=tpl,
        )
        newer = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
            user=u, exchange_account=ea, symbol_obj=sym, template=tpl,
        )
        # newer 가 더 큰 id 라고 보장 (factory 순차 생성)
        assert newer.id > older.id

        # 거래소엔 newer 가 점유한 포지션
        fake_binance.set_position(
            "BTCUSDT", position_amt="-0.5", position_side="SHORT",
            entry_price="48000", mark_price="48000",
        )

        # when
        _do_reconcile(identity_decrypt)

        # then: newer 그대로, older 는 STOPPED 강등 + qty=0
        db_session.expire_all()
        n = db_session.get(StrategyInstance, newer.id)
        o = db_session.get(StrategyInstance, older.id)
        assert n.status == "STAGE2_OPEN"  # keeper
        assert n.current_position_qty == Decimal("-0.5")
        assert o.status == "STOPPED"  # demoted
        assert o.current_position_qty == Decimal("0")
        assert o.stopped_at is not None

        # RiskEvent: ZOMBIE_DUPLICATE_ACTIVE_DEMOTED
        events = db_session.execute(
            select(RiskEvent).where(
                RiskEvent.event_type == "ZOMBIE_DUPLICATE_ACTIVE_DEMOTED"
            )
        ).scalars().all()
        assert len(events) == 1
        assert events[0].strategy_instance_id == older.id
        payload = events[0].event_payload or {}
        assert payload.get("zombie_strategy_id") == older.id
        assert payload.get("keeper_strategy_id") == newer.id

    def test_different_accounts_same_symbol_not_dedup(
        self,
        db_session,
        make_strategy,
        fake_binance,
        identity_decrypt,
        patched_sessionlocal,
    ) -> None:
        """같은 symbol/side 라도 account 가 다르면 별개 — dedup 안 함."""
        # 두 strategy 가 별개 user/account 로 생성됨 (factory 기본값)
        s_a = make_strategy(symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN")
        s_b = make_strategy(symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN")
        assert s_a.exchange_account_id != s_b.exchange_account_id

        # 두 계정 각각 BTCUSDT 포지션 매칭
        fake_binance.set_position("BTCUSDT", position_amt="-0.3", position_side="SHORT")

        _do_reconcile(identity_decrypt)

        db_session.expire_all()
        a = db_session.get(StrategyInstance, s_a.id)
        b = db_session.get(StrategyInstance, s_b.id)
        # 둘 다 active 유지
        assert a.status == "STAGE1_OPEN"
        assert b.status == "STAGE1_OPEN"

        # demotion 이벤트 없음
        events = db_session.execute(
            select(RiskEvent).where(
                RiskEvent.event_type == "ZOMBIE_DUPLICATE_ACTIVE_DEMOTED"
            )
        ).scalars().all()
        assert len(events) == 0
