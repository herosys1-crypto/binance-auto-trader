"""strategies API endpoint — 종료 상태 (COMPLETED/REENTRY_READY) 처리 회귀 방지.

배경 (2026-05-04 사용자 보고):
- 대시보드에 COMPLETED 전략이 보이고 액션 버튼이 잘못 노출됨 (LABUSDT #94/#95).
- 사용자가 ⏸ 정지 클릭 → backend `/stop` 이 noop 응답 → "안 됐다" 인식.
- 사용자가 ✏️ 수정/🛑 긴급종료 도 같은 noop.
- 삭제 시도 → backend DELETE 의 terminal_statuses 가 COMPLETED 빠져서 잘못된 에러.

Fix:
- 프론트엔드 `TERMINAL_STATUSES` 에 COMPLETED + REENTRY_READY 추가 → 자동 숨김 + active 액션 버튼 안 보임.
- backend DELETE 의 terminal_statuses 를 같은 모듈 _TERMINAL 과 일치 (COMPLETED + REENTRY_READY 추가).

이 테스트는 backend 동작만 보장:
1) /stop on COMPLETED → noop 응답, status 변경 없음, 거래소 호출 없음.
2) DELETE on entered COMPLETED → audit-log guard 로 차단 (terminal status 통과 후).
3) DELETE on never-entered COMPLETED → 정상 삭제.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.strategies import (
    delete_strategy,
    stop_strategy,
)
from app.models.strategy_instance import StrategyInstance
from app.schemas.strategy import StrategyStopRequest


# ============================================================================
# /stop on terminal status → noop
# ============================================================================
class TestStopOnTerminalStatusIsNoop:
    @pytest.mark.parametrize(
        "terminal_status",
        ["COMPLETED", "REENTRY_READY", "STOPPED", "CLOSED",
         "CLOSED_BY_TP", "CLOSED_BY_SL", "KILL_SWITCH_TRIGGERED"],
    )
    def test_stop_on_terminal_returns_noop_message(
        self,
        terminal_status: str,
        db_session,
        make_strategy,
        fake_trade_client,
    ) -> None:
        # given: 이미 종료된 전략
        strategy = make_strategy(
            symbol_str="LABUSDT", side="SHORT", status=terminal_status,
            current_position_qty=Decimal("0"),
            avg_entry_price=Decimal("2.0"),  # 진입했었음
            current_stage=2,
        )
        original_status = strategy.status

        # when: /stop 호출 (cancel_only mode)
        resp = stop_strategy(
            strategy_id=strategy.id,
            payload=StrategyStopRequest(mode="cancel_only", reason="test"),
            db=db_session,
            user_id=strategy.user_id,
        )

        # then: noop 응답 + status 변경 없음 + 거래소 호출 없음
        assert resp.strategy_id == strategy.id
        assert resp.status == original_status  # 그대로
        assert "이미 종료된 전략" in resp.message
        # FakeTradeClient 가 wired 안 됐어도 호출되면 안 됨 — 호출되면 실 trade_client 가
        # 인스턴스화돼서 BinanceClient 통해 외부 호출까지 갈 수 있음. noop 라 도달 안 함.
        assert len(fake_trade_client.placed_orders) == 0
        # DB 도 그대로
        db_session.expire_all()
        s = db_session.get(StrategyInstance, strategy.id)
        assert s.status == original_status

    @pytest.mark.parametrize("terminal_status", ["COMPLETED", "REENTRY_READY"])
    def test_emergency_stop_on_terminal_also_noop(
        self,
        terminal_status: str,
        db_session,
        make_strategy,
        fake_trade_client,
    ) -> None:
        """🛑 emergency_stop 도 같은 endpoint 라 같은 noop."""
        strategy = make_strategy(
            symbol_str="LABUSDT", side="SHORT", status=terminal_status,
            current_position_qty=Decimal("0"),
            avg_entry_price=Decimal("2.0"), current_stage=2,
        )

        resp = stop_strategy(
            strategy_id=strategy.id,
            payload=StrategyStopRequest(mode="emergency_stop", reason="test"),
            db=db_session,
            user_id=strategy.user_id,
        )

        assert resp.status == terminal_status
        assert "이미 종료된 전략" in resp.message
        assert len(fake_trade_client.placed_orders) == 0


# ============================================================================
# DELETE — audit-log guard
# ============================================================================
class TestDeleteStrategyArchive:
    """2026-05-06 (#96 사례 fix): hard delete → soft delete (archive).
    기존 audit-log 가드 (1단계+ 거부) 는 제거 — archive 가 audit log 보존 목적이라 불필요.
    이제 모든 종료 status 는 archive 가능 + row + cascade orders 보존.
    """

    def test_archive_completed_with_entered_position_succeeds(
        self,
        db_session,
        make_strategy,
    ) -> None:
        """1단계+ 진입한 COMPLETED 도 archive 가능 (이전엔 거부, audit log 가드 제거).

        archive 자체가 row + orders 보존이라 audit log 정책 충족.
        사용자 LABUSDT #94/#95 같은 경우도 이제 archive 가능 → UI 깔끔.
        """
        strategy = make_strategy(
            symbol_str="LABUSDT", side="SHORT", status="COMPLETED",
            current_stage=1,
            avg_entry_price=Decimal("2.0"),
            realized_pnl=Decimal("12.34"),  # 진입 흔적
        )
        sid = strategy.id
        resp = delete_strategy(strategy_id=sid, db=db_session, user_id=strategy.user_id)
        assert resp.status == "ARCHIVED"
        # row + realized_pnl 보존
        db_session.expire_all()
        s = db_session.get(StrategyInstance, sid)
        assert s is not None
        assert s.is_archived is True
        assert s.realized_pnl == Decimal("12.34")

    @pytest.mark.parametrize("terminal_status", ["COMPLETED", "REENTRY_READY"])
    def test_archive_terminal_status_succeeds(
        self,
        terminal_status: str,
        db_session,
        make_strategy,
    ) -> None:
        """COMPLETED / REENTRY_READY 모두 archive 가능 (terminal status 분류).

        2026-05-04 fix: COMPLETED/REENTRY_READY 가 TERMINAL_STATUSES 에 포함됨 → 첫 가드 통과.
        2026-05-06 fix: 기존 audit-log 가드 제거 → archive 까지 진행.
        """
        strategy = make_strategy(
            symbol_str="LABUSDT", side="SHORT", status=terminal_status,
            current_stage=1, avg_entry_price=Decimal("2.0"),
        )
        sid = strategy.id
        resp = delete_strategy(strategy_id=sid, db=db_session, user_id=strategy.user_id)
        assert resp.status == "ARCHIVED"
        s = db_session.get(StrategyInstance, sid)
        assert s is not None and s.is_archived is True

    def test_delete_active_strategy_rejected_first_guard(
        self,
        db_session,
        make_strategy,
    ) -> None:
        """active strategy (STAGE_X_OPEN) 는 첫 가드에 차단 — archive 안 됨, 먼저 종료."""
        strategy = make_strategy(
            symbol_str="LABUSDT", side="SHORT", status="STAGE2_OPEN",
            current_stage=2, avg_entry_price=Decimal("2.0"),
        )
        with pytest.raises(HTTPException) as ei:
            delete_strategy(strategy_id=strategy.id, db=db_session, user_id=strategy.user_id)
        assert "활성 전략은 삭제 불가" in ei.value.detail

    def test_archive_never_entered_stopped_strategy_succeeds(
        self,
        db_session,
        make_strategy,
    ) -> None:
        """대기 (current_stage=0, avg_entry=None) 상태 STOPPED 도 archive (이전엔 hard delete).

        UX #17 (2026-04-29) 의 본래 의도 (시작 실패 잔재 정리) 충족 — archive 로 UI 숨김.
        2026-05-06 변경: hard delete → archive 일관성 (모든 DELETE 가 archive).
        """
        strategy = make_strategy(
            symbol_str="TSTUSDT", side="SHORT", status="STOPPED",
            current_stage=0,
            avg_entry_price=None,
            current_position_qty=Decimal("0"),
        )
        sid = strategy.id

        resp = delete_strategy(strategy_id=sid, db=db_session, user_id=strategy.user_id)
        assert resp.status == "ARCHIVED"
        assert resp.strategy_id == sid

        # row 보존 (이전 hard delete 와 다름)
        db_session.expire_all()
        s = db_session.get(StrategyInstance, sid)
        assert s is not None and s.is_archived is True

    def test_delete_stopping_in_transit_rejected(
        self,
        db_session,
        make_strategy,
    ) -> None:
        """STOPPING (닫는 중) 은 의도적으로 terminal_statuses 에서 제외 → 삭제 차단.

        포지션이 거래소에 아직 남아있을 수 있어 삭제 위험.
        """
        strategy = make_strategy(
            symbol_str="LABUSDT", side="SHORT", status="STOPPING",
            current_stage=0, avg_entry_price=None,
            current_position_qty=Decimal("0"),
        )
        with pytest.raises(HTTPException) as ei:
            delete_strategy(strategy_id=strategy.id, db=db_session, user_id=strategy.user_id)
        assert "활성 전략은 삭제 불가" in ei.value.detail
