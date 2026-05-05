"""GET /admin/stats/breakdown — 운영 통계 셀 클릭 시 strategy 별 상세.

2026-05-06 (사용자 요청): 운영 통계 패널 합계만 보이는 것의 산출 근거 가시화.
- view=strategies: 모든 strategy
- view=realized: realized_pnl != 0 인 strategy 만
- view=losses: 손실 strategy 만 (감사용)

archive 된 strategy 도 포함 (#96 사례 정합성 유지 — 통계 합계와 일치).
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException


def _call_breakdown(db_session, view="strategies"):
    from app.api.v1.admin import get_stats_breakdown
    return get_stats_breakdown(view=view, db=db_session, user_id=1)


class TestStatsBreakdown:
    def test_empty_returns_zero(self, db_session):
        r = _call_breakdown(db_session, "strategies")
        assert r["count"] == 0
        assert r["items"] == []
        assert r["realized_pnl_sum"] == "0"
        assert r["profit_count"] == 0
        assert r["loss_count"] == 0

    def test_strategies_view_includes_all(self, db_session, make_strategy, make_template):
        tpl = make_template()
        for pnl in [10, -5, 0]:
            make_strategy(
                symbol_str="BTCUSDT", side="SHORT", status="STOPPED",
                current_position_qty=Decimal("0"),
                template=tpl, realized_pnl=Decimal(str(pnl)),
            )
        # 진행 중 strategy
        make_strategy(
            symbol_str="ETHUSDT", side="LONG", status="STAGE1_OPEN",
            current_position_qty=Decimal("1"), template=tpl,
        )
        r = _call_breakdown(db_session, "strategies")
        assert r["count"] == 4
        assert r["profit_count"] == 1
        assert r["loss_count"] == 1
        # classifications
        clss = sorted([it["classification"] for it in r["items"]])
        assert "수익" in clss
        assert "손실" in clss
        assert "진행중" in clss

    def test_realized_view_excludes_zero(self, db_session, make_strategy, make_template):
        tpl = make_template()
        for pnl in [100, -30, 50, 0, 0]:
            make_strategy(
                symbol_str="BTCUSDT", side="SHORT", status="STOPPED",
                current_position_qty=Decimal("0"),
                template=tpl, realized_pnl=Decimal(str(pnl)),
            )
        r = _call_breakdown(db_session, "realized")
        assert r["count"] == 3  # zero 두 개 제외
        # 절댓값 정렬 — 100 > 50 > -30
        ids = [Decimal(it["realized_pnl"]) for it in r["items"]]
        assert abs(ids[0]) >= abs(ids[1]) >= abs(ids[2])

    def test_losses_view_only_negative(self, db_session, make_strategy, make_template):
        tpl = make_template()
        for pnl in [50, -10, -30, 100, -5]:
            make_strategy(
                symbol_str="BTCUSDT", side="SHORT", status="STOPPED",
                current_position_qty=Decimal("0"),
                template=tpl, realized_pnl=Decimal(str(pnl)),
            )
        r = _call_breakdown(db_session, "losses")
        assert r["count"] == 3
        # 깊은 손실 먼저 (오름차순)
        pnls = [Decimal(it["realized_pnl"]) for it in r["items"]]
        assert pnls == sorted(pnls)
        # 모두 음수
        assert all(p < 0 for p in pnls)

    def test_invalid_view_rejected(self, db_session):
        with pytest.raises(HTTPException) as ei:
            _call_breakdown(db_session, "invalid_view")
        assert ei.value.status_code == 400

    def test_archived_strategy_included_in_breakdown(self, db_session, make_strategy, make_template):
        """#96 사례: archive 된 strategy 도 breakdown 에 포함 (정합성)."""
        from datetime import datetime, timezone
        tpl = make_template()
        s = make_strategy(
            symbol_str="TSTUSDT", side="SHORT", status="STOPPED",
            current_position_qty=Decimal("0"),
            template=tpl, realized_pnl=Decimal("867.65"),
        )
        s.is_archived = True
        s.archived_at = datetime.now(timezone.utc)
        db_session.commit()

        r = _call_breakdown(db_session, "strategies")
        assert r["count"] == 1
        assert r["archived_count"] == 1
        assert r["items"][0]["is_archived"] is True
        assert r["items"][0]["classification"] == "수익"
        assert Decimal(r["realized_pnl_sum"]) == Decimal("867.65")
