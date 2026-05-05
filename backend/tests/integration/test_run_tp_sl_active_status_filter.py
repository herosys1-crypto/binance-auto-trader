"""run_tp_sl_once active status filter — 옵션 C 5+ 단계 + 모든 TP_DONE_PARTIAL 포함.

2026-05-05 critical fix (#96 TSTUSDT 좀비 사례):
  기존 hardcoded 화이트리스트 (STAGE1~4_OPEN, TP1/2_DONE_PARTIAL) 가 STAGE6_OPEN
  인 #96 를 평가 0회 → max_profit_pct 갱신 X → TP 발동 X.
  fix: TERMINAL_STATUSES 제외 패턴으로 변경. 새 status 추가 시 자동 포함.

이 테스트는 SQL filter 자체를 검증 (orchestrator 통합은 별도 test_tp_sl_orchestrator).
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance


@pytest.mark.parametrize("stage_no", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
def test_stage_n_open_picked_up_by_filter(
    stage_no, db_session, make_strategy, make_template
) -> None:
    """STAGE1~10_OPEN 모두 active filter 에 잡혀야 함."""
    from app.core.strategy_status import TERMINAL_STATUSES
    tpl = make_template()
    s = make_strategy(
        symbol_str="BTCUSDT", side="SHORT", status=f"STAGE{stage_no}_OPEN",
        current_position_qty=Decimal("-0.5"),
        current_stage=stage_no,
        template=tpl,
    )
    rows = db_session.execute(
        select(StrategyInstance, ExchangeAccount)
        .join(ExchangeAccount, StrategyInstance.exchange_account_id == ExchangeAccount.id)
        .where(~StrategyInstance.status.in_(TERMINAL_STATUSES))
        .where(StrategyInstance.status != "WAITING")
        .where(ExchangeAccount.is_active.is_(True))
    ).all()
    matched_ids = {row[0].id for row in rows}
    assert s.id in matched_ids, (
        f"STAGE{stage_no}_OPEN 가 run_tp_sl_once filter 에 매칭돼야 함 "
        f"(이전엔 STAGE5+ 가 누락돼 #96 좀비). matched={matched_ids}"
    )


@pytest.mark.parametrize("status", [
    "TP1_DONE_PARTIAL",
    "TP2_DONE_PARTIAL", "TP2_DONE",
    "TP3_DONE_PARTIAL",
    "TP4_DONE_PARTIAL",
    "TP5_DONE_PARTIAL",
    "TRAILING_ARMED",
    "CRISIS_TP1",
])
def test_all_intermediate_tp_statuses_picked_up(
    status, db_session, make_strategy, make_template
) -> None:
    """TP3~5_DONE_PARTIAL, TP2_DONE, TRAILING_ARMED, CRISIS_TP1 모두 active filter 에 매칭."""
    from app.core.strategy_status import TERMINAL_STATUSES
    tpl = make_template()
    s = make_strategy(
        symbol_str="BTCUSDT", side="SHORT", status=status,
        current_position_qty=Decimal("-0.3"), template=tpl,
    )
    rows = db_session.execute(
        select(StrategyInstance, ExchangeAccount)
        .join(ExchangeAccount, StrategyInstance.exchange_account_id == ExchangeAccount.id)
        .where(~StrategyInstance.status.in_(TERMINAL_STATUSES))
        .where(StrategyInstance.status != "WAITING")
        .where(ExchangeAccount.is_active.is_(True))
    ).all()
    matched_ids = {row[0].id for row in rows}
    assert s.id in matched_ids, (
        f"{status} 가 run_tp_sl_once filter 에 매칭돼야 함 "
        f"(이전 hardcoded 화이트리스트엔 누락). matched={matched_ids}"
    )


@pytest.mark.parametrize("terminal_status", [
    "STOPPED", "COMPLETED", "CLOSED", "CLOSED_BY_SL", "CLOSED_BY_TP",
    "REENTRY_READY", "KILL_SWITCH_TRIGGERED", "STOPPING", "WAITING",
])
def test_terminal_status_excluded_from_filter(
    terminal_status, db_session, make_strategy, make_template
) -> None:
    """종료 status + WAITING 는 active filter 에서 제외돼야 함 (불필요한 orchestrator 호출 방지)."""
    from app.core.strategy_status import TERMINAL_STATUSES
    tpl = make_template()
    s = make_strategy(
        symbol_str="BTCUSDT", side="SHORT", status=terminal_status,
        current_position_qty=Decimal("0"), template=tpl,
    )
    not_for_tp_sl = frozenset(TERMINAL_STATUSES) | {"STOPPING", "WAITING"}
    rows = db_session.execute(
        select(StrategyInstance, ExchangeAccount)
        .join(ExchangeAccount, StrategyInstance.exchange_account_id == ExchangeAccount.id)
        .where(~StrategyInstance.status.in_(not_for_tp_sl))
        .where(ExchangeAccount.is_active.is_(True))
    ).all()
    matched_ids = {row[0].id for row in rows}
    assert s.id not in matched_ids, (
        f"{terminal_status} 는 active filter 에서 제외돼야 함. "
        f"(STOPPING 좀비는 zombie_guardian 이 처리, 불필요한 orchestrator 호출 방지). "
        f"matched={matched_ids}"
    )


def test_inactive_exchange_account_excluded(
    db_session, make_strategy, make_template, make_exchange_account, make_user
) -> None:
    """is_active=False 인 exchange_account 의 strategy 는 제외."""
    from app.core.strategy_status import TERMINAL_STATUSES
    u = make_user()
    inactive_ea = make_exchange_account(user=u, is_active=False)
    tpl = make_template()
    s = make_strategy(
        symbol_str="BTCUSDT", side="SHORT", status="STAGE6_OPEN",
        current_position_qty=Decimal("-0.5"),
        user=u, exchange_account=inactive_ea, template=tpl,
    )
    not_for_tp_sl = frozenset(TERMINAL_STATUSES) | {"STOPPING", "WAITING"}
    rows = db_session.execute(
        select(StrategyInstance, ExchangeAccount)
        .join(ExchangeAccount, StrategyInstance.exchange_account_id == ExchangeAccount.id)
        .where(~StrategyInstance.status.in_(not_for_tp_sl))
        .where(ExchangeAccount.is_active.is_(True))
    ).all()
    assert s.id not in {row[0].id for row in rows}
