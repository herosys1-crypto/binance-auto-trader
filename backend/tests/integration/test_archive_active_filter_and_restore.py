"""C-full Step 1+2 — active query 의 is_archived filter + restore endpoint.

배경 (PR #7 의 후속):
  PR #7 (soft delete) 가 DELETE → archive 로 변경했지만, 워커/repository 의 active
  query 들이 archived row 도 처리. 따라서 archive 한 strategy 가 UI 에서 사라지지
  않고 reconcile/tp_sl/etc. 가 계속 평가하는 부작용.

  C-full Step 1: 모든 active query 에 WHERE NOT is_archived 추가 (7곳).
  C-full Step 2: 신규 POST /strategies/{id}/restore — archive 해제.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.strategies import delete_strategy, restore_strategy
from app.models.strategy_instance import StrategyInstance
from app.repositories.strategy_repository import StrategyRepository


class TestArchivedFilterInRepository:
    """repository.list_strategies 가 default 로 archived 제외하는지 검증.

    endpoint (api.v1.strategies.list_strategies) 는 PostgreSQL 전용 enrichment
    (BOOL_OR + regex) 를 사용해 sqlite 에서 호출 불가. repository 만 unit-test.
    """
    def test_list_default_excludes_archived(self, db_session, make_user, make_strategy, make_template):
        tpl = make_template()
        u = make_user()
        s_active = make_strategy(symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN",
                                  current_position_qty=Decimal("-0.5"), user=u, template=tpl)
        s_archived = make_strategy(symbol_str="ETHUSDT", side="SHORT", status="STOPPED",
                                    current_position_qty=Decimal("0"), user=u, template=tpl,
                                    realized_pnl=Decimal("100"))
        s_archived.is_archived = True
        s_archived.archived_at = datetime.now(timezone.utc)
        db_session.commit()

        repo = StrategyRepository(db_session)
        rows = repo.list_strategies(user_id=u.id, include_archived=False)
        ids = {r.id for r in rows}
        assert s_active.id in ids
        assert s_archived.id not in ids, "archived 는 default 에서 제외"

    def test_list_include_archived_returns_all(self, db_session, make_user, make_strategy, make_template):
        tpl = make_template()
        u = make_user()
        s_active = make_strategy(symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN",
                                  current_position_qty=Decimal("-0.5"), user=u, template=tpl)
        s_archived = make_strategy(symbol_str="ETHUSDT", side="SHORT", status="STOPPED",
                                    current_position_qty=Decimal("0"), user=u, template=tpl)
        s_archived.is_archived = True
        s_archived.archived_at = datetime.now(timezone.utc)
        db_session.commit()

        repo = StrategyRepository(db_session)
        rows = repo.list_strategies(user_id=u.id, include_archived=True)
        ids = {r.id for r in rows}
        assert s_active.id in ids
        assert s_archived.id in ids


class TestRestoreEndpoint:
    def test_restore_archived_strategy(self, db_session, make_strategy, make_template):
        """archive 된 strategy 를 restore → is_archived=False, status 그대로."""
        tpl = make_template()
        s = make_strategy(symbol_str="BTCUSDT", side="SHORT", status="STOPPED",
                          current_position_qty=Decimal("0"), template=tpl,
                          realized_pnl=Decimal("50"))
        # archive 먼저
        delete_strategy(strategy_id=s.id, db=db_session, user_id=s.user_id)
        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        assert s2.is_archived is True

        # restore
        result = restore_strategy(strategy_id=s.id, db=db_session, user_id=s.user_id)
        assert result.status == "STOPPED"  # status 그대로
        assert "복원 완료" in result.message

        db_session.expire_all()
        s3 = db_session.get(StrategyInstance, s.id)
        assert s3.is_archived is False
        assert s3.archived_at is None
        assert s3.realized_pnl == Decimal("50")  # realized 그대로

    def test_restore_non_archived_is_noop(self, db_session, make_strategy, make_template):
        """archived 아닌 strategy 에 restore → idempotent (noop)."""
        tpl = make_template()
        s = make_strategy(symbol_str="BTCUSDT", side="SHORT", status="STOPPED",
                          current_position_qty=Decimal("0"), template=tpl)
        result = restore_strategy(strategy_id=s.id, db=db_session, user_id=s.user_id)
        assert result.status == "STOPPED"
        assert "archive 상태가 아닙니다" in result.message

    def test_restore_other_user_returns_404(
        self, db_session, make_user, make_strategy, make_template
    ) -> None:
        owner = make_user()
        intruder = make_user()
        tpl = make_template()
        s = make_strategy(symbol_str="BTCUSDT", side="SHORT", status="STOPPED",
                          current_position_qty=Decimal("0"), user=owner, template=tpl)
        with pytest.raises(HTTPException) as ei:
            restore_strategy(strategy_id=s.id, db=db_session, user_id=intruder.id)
        assert ei.value.status_code == 404


class TestArchiveRestoreCycle:
    def test_archive_then_restore_then_archive_again(
        self, db_session, make_strategy, make_template
    ):
        """archive → restore → archive 사이클 정상 동작 + realized 보존."""
        tpl = make_template()
        s = make_strategy(symbol_str="BTCUSDT", side="SHORT", status="COMPLETED",
                          current_position_qty=Decimal("0"), current_stage=2,
                          avg_entry_price=Decimal("50000"),
                          template=tpl, realized_pnl=Decimal("123.45"))
        sid = s.user_id
        # 1차 archive
        delete_strategy(strategy_id=s.id, db=db_session, user_id=sid)
        # restore
        restore_strategy(strategy_id=s.id, db=db_session, user_id=sid)
        # 2차 archive
        delete_strategy(strategy_id=s.id, db=db_session, user_id=sid)

        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        assert s2.is_archived is True
        assert s2.archived_at is not None
        assert s2.realized_pnl == Decimal("123.45")  # 사이클 거치며 보존


# ============================================================================
# 사용자 #33 AVAAIUSDT + #41 ESPORTSUSDT 좀비 보고 (2026-05-15)
# ============================================================================
class TestArchiveWithNonzeroPositionEmitsCritical:
    """archive 시 latest position snapshot 의 qty 가 0 이 아니면 CRITICAL RiskEvent 발송.

    사용자 #33/#41 사례: force-stop 또는 외부 청산 누락으로 거래소에 잔량 있는 채
    archive → 좀비. 사후 알림 보장으로 운영자가 빨리 인지하도록.
    """
    def test_archive_with_nonzero_position_emits_critical_event(
        self, db_session, make_strategy, make_template
    ):
        """잔량 -182 (force-stop 후 DB qty=0 이지만 position snapshot 에 -182 남음)."""
        from app.models.position import Position
        from app.models.risk_event import RiskEvent

        tpl = make_template()
        s = make_strategy(
            symbol_str="AVAAIUSDT", side="SHORT", status="STOPPED",
            current_position_qty=Decimal("0"),  # force-stop 으로 마킹됨
            avg_entry_price=Decimal("0.00984"),
            template=tpl, current_stage=1,
        )
        # latest position snapshot — 거래소 실제 qty -182 잔재
        db_session.add(Position(
            strategy_instance_id=s.id, symbol="AVAAIUSDT", side="SHORT",
            position_side="SHORT", position_amt=Decimal("-182"),
            entry_price=Decimal("0.00984"), source="TEST",
        ))
        db_session.commit()

        delete_strategy(strategy_id=s.id, db=db_session, user_id=s.user_id)

        # CRITICAL RiskEvent 발생 확인
        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.strategy_instance_id == s.id)
            .where(RiskEvent.event_type == "ARCHIVE_WITH_NONZERO_POSITION")
        ).scalars().all()
        assert len(events) == 1, "archive 시 nonzero position snapshot 이면 CRITICAL 1건 발송 필수"
        assert events[0].severity == "CRITICAL"
        assert "182" in events[0].title

    def test_archive_with_zero_position_no_critical(
        self, db_session, make_strategy, make_template
    ):
        """잔량 0 이면 CRITICAL 발송 안 함 (정상 archive)."""
        from app.models.position import Position
        from app.models.risk_event import RiskEvent

        tpl = make_template()
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="COMPLETED",
            current_position_qty=Decimal("0"),
            avg_entry_price=Decimal("50000"),
            template=tpl, current_stage=2, realized_pnl=Decimal("100"),
        )
        db_session.add(Position(
            strategy_instance_id=s.id, symbol="BTCUSDT", side="SHORT",
            position_side="SHORT", position_amt=Decimal("0"),
            entry_price=Decimal("50000"), source="TEST",
        ))
        db_session.commit()

        delete_strategy(strategy_id=s.id, db=db_session, user_id=s.user_id)

        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.strategy_instance_id == s.id)
            .where(RiskEvent.event_type == "ARCHIVE_WITH_NONZERO_POSITION")
        ).scalars().all()
        assert len(events) == 0, "잔량 0 이면 CRITICAL 발송 안 함 (정상 archive)"

    def test_archive_with_no_position_snapshot_no_critical(
        self, db_session, make_strategy, make_template
    ):
        """Position snapshot 자체가 없으면 (한 번도 진입 안 함) CRITICAL 발송 안 함."""
        from app.models.risk_event import RiskEvent

        tpl = make_template()
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STOPPED",
            current_position_qty=Decimal("0"),
            avg_entry_price=None,
            template=tpl, current_stage=0,
        )

        delete_strategy(strategy_id=s.id, db=db_session, user_id=s.user_id)

        events = db_session.execute(
            select(RiskEvent).where(RiskEvent.strategy_instance_id == s.id)
            .where(RiskEvent.event_type == "ARCHIVE_WITH_NONZERO_POSITION")
        ).scalars().all()
        assert len(events) == 0
