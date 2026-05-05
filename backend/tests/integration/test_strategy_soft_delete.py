"""DELETE /strategies/{id} — soft delete (archive) — 2026-05-06 (#96 사례).

배경:
  사용자 #96 cascade delete 로 +867 USDT realized_pnl 이 운영 통계 합계에서
  영구 누락. 이전 endpoint 는 current_stage > 0 거부했지만 cleanup 스크립트나
  운영자 직접 SQL 로 우회됨. 또한 미진입 (current_stage=0) strategy 에 대해선
  hard DELETE → cascade 로 orders 도 사라짐.

  Fix: archive 로 변경. row + orders 보존, is_archived=true 마킹만.
  - realized_pnl 통계 합계가 거래소 history 와 일치 유지
  - audit log 보존
  - 1단계 이상 진입한 strategy 도 archive 가능 (이전엔 거부)
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.v1.strategies import delete_strategy
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_stage_plan import StrategyStagePlan


class TestStrategySoftDelete:
    def test_archive_terminal_strategy_preserves_row(
        self, db_session, make_strategy, make_template
    ) -> None:
        """STOPPED strategy 를 archive — DB row 보존, is_archived=true."""
        tpl = make_template()
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STOPPED",
            current_position_qty=Decimal("0"),
            template=tpl,
            realized_pnl=Decimal("100.50"),
        )
        sid = s.id

        result = delete_strategy(strategy_id=sid, db=db_session, user_id=s.user_id)
        assert result.status == "ARCHIVED"
        assert "보관 처리" in result.message or "이미 archive" in result.message

        # row 가 DB 에 그대로 — is_archived=True, realized_pnl 보존
        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, sid)
        assert s2 is not None, "row 가 DB 에 보존돼야 함 (이전 hard delete 와 다름)"
        assert s2.is_archived is True
        assert s2.archived_at is not None
        assert s2.realized_pnl == Decimal("100.50"), "realized_pnl 보존 — 통계 합계에 유지"

    def test_archive_strategy_with_position_history_allowed(
        self, db_session, make_strategy, make_template
    ) -> None:
        """이전엔 current_stage>0 거부했지만, archive 는 허용 (history 보존이 목적)."""
        tpl = make_template()
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STOPPED",
            current_stage=6,  # 이전 코드라면 거부됐음
            current_position_qty=Decimal("0"),
            avg_entry_price=Decimal("50000"),
            realized_pnl=Decimal("867.65"),  # #96 의 실제 손익 시뮬
            template=tpl,
        )
        sid = s.id

        result = delete_strategy(strategy_id=sid, db=db_session, user_id=s.user_id)
        assert result.status == "ARCHIVED"
        # 메시지에 realized_pnl 명시
        assert "867" in result.message or "보관" in result.message

        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, sid)
        assert s2 is not None
        assert s2.is_archived is True
        assert s2.realized_pnl == Decimal("867.65")

    def test_archive_active_strategy_rejected(
        self, db_session, make_strategy, make_template
    ) -> None:
        """STAGE1_OPEN 등 활성 strategy 는 archive 거부 (먼저 종료 필요)."""
        tpl = make_template()
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN",
            current_position_qty=Decimal("-0.5"),
            template=tpl,
        )
        with pytest.raises(HTTPException) as ei:
            delete_strategy(strategy_id=s.id, db=db_session, user_id=s.user_id)
        assert ei.value.status_code == 400
        assert "활성" in ei.value.detail or "종료" in ei.value.detail

    def test_archive_other_user_returns_404(
        self, db_session, make_user, make_strategy, make_template
    ) -> None:
        """다른 user 의 strategy archive 시도 → 404."""
        owner = make_user()
        intruder = make_user()
        tpl = make_template()
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STOPPED",
            current_position_qty=Decimal("0"),
            user=owner, template=tpl,
        )
        with pytest.raises(HTTPException) as ei:
            delete_strategy(strategy_id=s.id, db=db_session, user_id=intruder.id)
        assert ei.value.status_code == 404

    def test_archive_idempotent_when_already_archived(
        self, db_session, make_strategy, make_template
    ) -> None:
        """이미 archived 된 strategy 에 또 호출 → noop (idempotent)."""
        tpl = make_template()
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STOPPED",
            current_position_qty=Decimal("0"),
            template=tpl,
            realized_pnl=Decimal("50"),
        )
        sid = s.id

        # 1st call
        r1 = delete_strategy(strategy_id=sid, db=db_session, user_id=s.user_id)
        assert r1.status == "ARCHIVED"

        # 2nd call — noop
        db_session.expire_all()
        r2 = delete_strategy(strategy_id=sid, db=db_session, user_id=s.user_id)
        assert r2.status == "ARCHIVED"
        assert "이미 archive" in r2.message

        # row + realized 그대로
        s3 = db_session.get(StrategyInstance, sid)
        assert s3.is_archived is True
        assert s3.realized_pnl == Decimal("50")

    def test_archived_strategy_realized_pnl_in_stats_sum(
        self, db_session, make_strategy, make_template
    ) -> None:
        """archive 된 strategy 의 realized_pnl 이 /admin/stats 합계에 포함돼야 함.

        이전엔 hard delete 라 합계에서 사라졌으나, soft delete 후엔 모든 strategy
        포함되어 거래소 history 와 일치 유지.
        """
        from app.api.v1.admin import get_operation_stats
        tpl = make_template()
        # 3개 strategies — 각 다른 PnL
        for i, pnl in enumerate([100, 200, -50]):
            make_strategy(
                symbol_str="BTCUSDT", side="SHORT", status="STOPPED",
                current_position_qty=Decimal("0"),
                template=tpl, realized_pnl=Decimal(str(pnl)),
            )
        # 1개 archive
        archived = db_session.query(StrategyInstance).filter_by(realized_pnl=Decimal("200")).first()
        delete_strategy(strategy_id=archived.id, db=db_session, user_id=archived.user_id)

        # stats 호출 — archived 포함된 합계 = 100 + 200 - 50 = 250
        stats = get_operation_stats(db=db_session, user_id=archived.user_id)
        assert Decimal(stats["realized_pnl_total"]) == Decimal("250"), (
            f"archived strategy 의 realized_pnl 도 합계에 포함돼야 함. 받은: {stats['realized_pnl_total']}"
        )
        # profit/loss count 도 archived 포함
        assert stats["profit_strategy_count"] == 2  # 100 + 200 (archived)
        assert stats["loss_strategy_count"] == 1   # -50

    def test_archive_preserves_orders_cascade(
        self, db_session, make_strategy, make_template
    ) -> None:
        """archive 후 cascade orders / stage_plans 모두 보존 (이전 hard delete 는 cascade 로 사라짐)."""
        from app.models.order import Order
        tpl = make_template()
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STOPPED",
            current_stage=2, current_position_qty=Decimal("0"),
            avg_entry_price=Decimal("50000"),
            realized_pnl=Decimal("300"),
            template=tpl,
        )
        # stage plan + order 추가
        db_session.add(StrategyStagePlan(
            strategy_instance_id=s.id, stage_no=1, side="SHORT",
            trigger_mode="IMMEDIATE", trigger_percent=None,
            trigger_price=Decimal("50000"), planned_capital=Decimal("100"),
            planned_qty=Decimal("0.001"), is_triggered=True,
        ))
        db_session.add(Order(
            strategy_instance_id=s.id, stage_no=1, purpose="ENTRY",
            symbol="BTCUSDT", side="SELL", position_side="SHORT",
            order_type="LIMIT", time_in_force="GTC",
            client_order_id="test-entry-1",
            orig_qty=Decimal("0.001"), price=Decimal("50000"),
            status="FILLED", executed_qty=Decimal("0.001"), avg_price=Decimal("50000"),
        ))
        db_session.commit()

        delete_strategy(strategy_id=s.id, db=db_session, user_id=s.user_id)

        # 모든 cascade 데이터 보존
        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        assert s2 is not None and s2.is_archived is True
        # stage_plans + orders 그대로 — cascade hard delete 아님
        plans = db_session.query(StrategyStagePlan).filter_by(strategy_instance_id=s.id).count()
        orders = db_session.query(Order).filter_by(strategy_instance_id=s.id).count()
        assert plans == 1, "stage_plans 보존 (cascade delete 회피)"
        assert orders == 1, "orders 보존 (cascade delete 회피) — #96 사례 방어"
