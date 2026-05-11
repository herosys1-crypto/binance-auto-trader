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
        # 2026-05-08 변경: 정렬을 「최신 시작 순」 으로 — 사용자가 가장 알고 싶어하는 것은
        # 최근 거래 결과. 같은 created_at 이면 ID 큰 (최근 row) 우선.
        # 모든 strategy 가 거의 동시 생성됐으니 ID 큰 순 (마지막에 만든 것 = 최근).
        ids = [it["id"] for it in r["items"]]
        assert ids == sorted(ids, reverse=True)

    def test_losses_view_includes_audit_targets(self, db_session, make_strategy, make_template):
        """2026-05-12 사용자 요청 (정책 v2): 「손실/감사」 view 가 손실 외에도 감사 대상 포함.

        포함 기준 (OR):
        - realized_pnl < 0 (실제 손실)
        - max_loss_pct < -10% (큰 미실현 낙폭)
        - status IN (STOPPED, STOPPING) (수동 정지)
        - crisis_mode_triggered_at IS NOT NULL (크라이시스 진입)

        이전엔 realized_pnl < 0 만 봐서 「수동 정지 2건」 같은 카운트가 모달에 안 나옴.
        """
        tpl = make_template()
        for pnl in [50, -10, -30, 100, -5]:
            make_strategy(
                symbol_str="BTCUSDT", side="SHORT", status="STOPPED",
                current_position_qty=Decimal("0"),
                template=tpl, realized_pnl=Decimal(str(pnl)),
            )
        r = _call_breakdown(db_session, "losses")
        # 5개 모두 STOPPED 상태이므로 「수동정지」 분류로 모두 포함됨.
        assert r["count"] == 5, f"수동정지(STOPPED) 5건 모두 포함돼야 함 (count={r['count']})"
        ids = [it["id"] for it in r["items"]]
        assert ids == sorted(ids, reverse=True)  # 최신순 정렬 유지

    def test_losses_view_excludes_clean_running(self, db_session, make_strategy, make_template):
        """진행중 + realized_pnl 양수/0 + max_loss 작음 + 수동정지 아님 — 감사 대상 X."""
        tpl = make_template()
        # 양수 PnL 진행중 (STAGE2_OPEN) — 감사 대상 아님
        s_clean = make_strategy(
            symbol_str="ETHUSDT", side="LONG", status="STAGE2_OPEN",
            current_position_qty=Decimal("0.5"),
            template=tpl, realized_pnl=Decimal("0"),
            max_loss_pct=Decimal("-3"),  # -10% 이내
        )
        # 손실 (감사 대상)
        s_loss = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="COMPLETED",
            current_position_qty=Decimal("0"),
            template=tpl, realized_pnl=Decimal("-15"),
        )
        r = _call_breakdown(db_session, "losses")
        ids = {it["id"] for it in r["items"]}
        assert s_loss.id in ids, "손실 strategy 는 감사 대상 ✓"
        assert s_clean.id not in ids, "진행중 + 손실 작은 strategy 는 감사 대상 X"

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
