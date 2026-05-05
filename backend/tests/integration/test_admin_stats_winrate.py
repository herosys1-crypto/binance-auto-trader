"""GET /admin/stats — 2026-05-06 strategy 단위 승률 정확화.

배경 (사용자 보고 2026-05-06):
  화면에 승률 100% / 실현손익 +608.13 USDT 표시되는데, DB 의 strategy 별
  realized_pnl 분포 보면 손실 3건 (#84 -84.54, #59 -22.78, #68 -4.72) 존재.
  알림 기반 승률은 이 손실들이 「[손절 발동]」 알림 없이 STOPPED 됐기 때문에
  분모에서 빠짐 → 100% 잘못 계산.

Fix: win_rate_pct 를 strategy.realized_pnl 부호 기준으로 계산.
  - profit_strategy_count = COUNT(realized_pnl > 0)
  - loss_strategy_count = COUNT(realized_pnl < 0)
  - win_rate_pct = profit / (profit + loss) * 100
  - 알림 기반 (이전) 은 win_rate_alert_based_pct 로 백업 노출.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session


# inline test client — admin.py 의 stats endpoint 직접 호출
def _call_stats(db_session):
    """admin.py 의 get_operation_stats 함수 본체 호출 (FastAPI 라우터 거치지 않음).

    Depends(get_db), Depends(get_current_user_id) 는 함수 인자 default 로 들어있어
    직접 호출 시 user_id 만 더미값 (1) 으로 명시 — endpoint 본체는 user 검증 안 함.
    """
    from app.api.v1.admin import get_operation_stats
    return get_operation_stats(db=db_session, user_id=1)


class TestStatsWinRateStrategyBased:
    def test_no_strategies_returns_zero_winrate(self, db_session):
        result = _call_stats(db_session)
        assert result["profit_strategy_count"] == 0
        assert result["loss_strategy_count"] == 0
        assert result["decided_strategy_count"] == 0
        assert result["win_rate_pct"] == "0.00"

    def test_only_profit_strategies_100pct(self, db_session, make_strategy, make_template):
        tpl = make_template()
        for pnl in [10, 20, 30]:
            make_strategy(
                symbol_str="BTCUSDT", side="SHORT", status="STOPPED",
                current_position_qty=Decimal("0"),
                template=tpl, realized_pnl=Decimal(str(pnl)),
            )
        result = _call_stats(db_session)
        assert result["profit_strategy_count"] == 3
        assert result["loss_strategy_count"] == 0
        assert result["win_rate_pct"] == "100.00"

    def test_only_loss_strategies_0pct(self, db_session, make_strategy, make_template):
        tpl = make_template()
        for pnl in [-10, -20, -30]:
            make_strategy(
                symbol_str="BTCUSDT", side="SHORT", status="STOPPED",
                current_position_qty=Decimal("0"),
                template=tpl, realized_pnl=Decimal(str(pnl)),
            )
        result = _call_stats(db_session)
        assert result["profit_strategy_count"] == 0
        assert result["loss_strategy_count"] == 3
        assert result["win_rate_pct"] == "0.00"

    def test_mixed_profit_loss_calculates_correctly(self, db_session, make_strategy, make_template):
        """사용자 보고 사례 시뮬: 23 수익 + 3 손실 = 88.46% (이전엔 알림 0건이라 100% 였던 것)."""
        tpl = make_template()
        # 23 수익
        for i in range(23):
            make_strategy(
                symbol_str="BTCUSDT", side="SHORT", status="STOPPED",
                current_position_qty=Decimal("0"),
                template=tpl, realized_pnl=Decimal("10"),
            )
        # 3 손실 — 「[손절 발동]」 알림 없이 STOPPED (사용자 사례)
        for i in range(3):
            make_strategy(
                symbol_str="BTCUSDT", side="SHORT", status="STOPPED",
                current_position_qty=Decimal("0"),
                template=tpl, realized_pnl=Decimal("-30"),
            )
        result = _call_stats(db_session)
        assert result["profit_strategy_count"] == 23
        assert result["loss_strategy_count"] == 3
        assert result["decided_strategy_count"] == 26
        # 23 / 26 = 88.4615... → round 2 → 88.46
        assert result["win_rate_pct"] == "88.46"
        # 알림 기반 승률 (이전 메트릭) 은 0 알림이라 0% (분모 0)
        assert result["win_rate_alert_based_pct"] == "0.00"

    def test_breakeven_strategies_excluded_from_decided(self, db_session, make_strategy, make_template):
        """realized_pnl == 0 (진행 중 또는 breakeven) 은 분모/분자 모두 제외."""
        tpl = make_template()
        # 2 수익
        for i in range(2):
            make_strategy(
                symbol_str="BTCUSDT", side="SHORT", status="STOPPED",
                current_position_qty=Decimal("0"),
                template=tpl, realized_pnl=Decimal("5"),
            )
        # 5 진행 중 (realized=0)
        for i in range(5):
            make_strategy(
                symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN",
                current_position_qty=Decimal("-0.5"),
                template=tpl, realized_pnl=Decimal("0"),
            )
        result = _call_stats(db_session)
        assert result["profit_strategy_count"] == 2
        assert result["loss_strategy_count"] == 0
        assert result["decided_strategy_count"] == 2  # 진행 중 5 제외
        assert result["win_rate_pct"] == "100.00"

    def test_realized_pnl_total_matches_sum(self, db_session, make_strategy, make_template):
        """realized_pnl_total 이 모든 strategy 의 realized_pnl 합과 정확히 일치."""
        tpl = make_template()
        pnls = [Decimal("100.50"), Decimal("-30.25"), Decimal("75.75"), Decimal("0")]
        for p in pnls:
            make_strategy(
                symbol_str="BTCUSDT", side="SHORT", status="STOPPED",
                current_position_qty=Decimal("0"),
                template=tpl, realized_pnl=p,
            )
        result = _call_stats(db_session)
        # 100.50 - 30.25 + 75.75 + 0 = 146.00
        assert Decimal(result["realized_pnl_total"]) == Decimal("146.00")
        assert result["profit_strategy_count"] == 2
        assert result["loss_strategy_count"] == 1
