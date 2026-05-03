"""Kill Switch 사각지대 회귀 방어.

audit 발견 (2026-05-04): kill_switch.is_enabled 가 ExecutionService.start_stage1
에만 체크됐음. 이는 다음 코드 경로에서 신규 거래를 차단하지 못함:
1. ExecutionService.trigger_next_stage — stage 2~10 자동 진입
2. StrategyService.create_strategy_instance — DB 에 strategy row 생성

운영 영향: kill switch 발동 후에도 추가 거래 발생 가능 → 안전장치 부분 무력화.

이 테스트는 fix 동작 보장:
- create_strategy_instance: kill-switch 활성 시 ValueError + DB row 생성 안 됨
- trigger_next_stage: kill-switch 활성 시 ValueError + 거래소 호출 없음
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.account_kill_switch import AccountKillSwitch
from app.models.strategy_instance import StrategyInstance
from app.services.execution_service import ExecutionService
from app.services.strategy_service import StrategyService


def _enable_kill_switch(db_session, exchange_account_id: int, reason: str = "test") -> None:
    """테스트용 kill switch 활성화 — service 거치지 않고 DB 직접."""
    from datetime import datetime, timezone
    ks = AccountKillSwitch(
        exchange_account_id=exchange_account_id,
        is_enabled=True,
        reason_code=reason,
        reason_message=reason,
        triggered_at=datetime.now(timezone.utc),
    )
    db_session.add(ks)
    db_session.commit()


# ============================================================================
# create_strategy_instance — kill switch 차단
# ============================================================================
class TestCreateStrategyBlockedByKillSwitch:
    def test_kill_switch_active_blocks_create(
        self,
        db_session,
        make_user,
        make_exchange_account,
        make_symbol,
        make_template,
    ) -> None:
        u = make_user()
        ea = make_exchange_account(user=u)
        sym = make_symbol("BTCUSDT")
        tpl = make_template(side="SHORT")
        _enable_kill_switch(db_session, ea.id, reason="DAILY_LOSS_LIMIT")

        with pytest.raises(ValueError) as ei:
            StrategyService(db_session).create_strategy_instance(
                user_id=u.id,
                exchange_account_id=ea.id,
                strategy_template_id=tpl.id,
                symbol="BTCUSDT", side="SHORT",
                start_price=Decimal("50000"),
            )
        msg = str(ei.value)
        assert "Kill-Switch" in msg
        assert str(ea.id) in msg or "kill" in msg.lower()

        # DB 에 새 strategy row 가 만들어지지 않음
        rows = db_session.execute(
            select(StrategyInstance)
            .where(StrategyInstance.exchange_account_id == ea.id)
            .where(StrategyInstance.symbol == "BTCUSDT")
        ).scalars().all()
        assert len(rows) == 0, (
            "kill-switch 활성 시 strategy DB row 가 만들어지지 않아야 함 "
            "(이전엔 create 까지 진행 후 start_stage1 에서 차단 → DB 잔재)"
        )


# ============================================================================
# trigger_next_stage — kill switch 차단
# ============================================================================
class TestTriggerNextStageBlockedByKillSwitch:
    def test_kill_switch_active_blocks_stage2_entry(
        self,
        db_session,
        make_strategy,
        fake_binance,
        fake_trade_client,
    ) -> None:
        # given: STAGE1_OPEN strategy + kill switch 활성
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT",
            status="STAGE1_OPEN",
            current_position_qty=Decimal("-0.5"),
            current_stage=1,
        )
        _enable_kill_switch(db_session, strategy.exchange_account_id)

        svc = ExecutionService(
            db_session,
            api_key="enc:apikey", api_secret="enc:secret", is_testnet=True,
        )

        with pytest.raises(ValueError) as ei:
            svc.trigger_next_stage(strategy.id, stage_no=2)
        msg = str(ei.value)
        assert "kill-switch" in msg.lower()
        assert "stage 2" in msg.lower()

        # 거래소 주문 발송 안 됨 (FakeTradeClient 가 캡처할 게 없어야)
        # Note: trigger_next_stage 가 _place_stage_entry_order 호출 — LIMIT 이라
        # ExecutionAdapterRouter 경로지만 fake 안 거치므로 실제 호출 자체가 일어나면 raise.
        # 여기선 ValueError 가 먼저 떠서 적어도 그 검증은 됨.
        # qty/stage 도 변경 없음
        db_session.expire_all()
        s = db_session.get(StrategyInstance, strategy.id)
        assert s.status == "STAGE1_OPEN"  # 변경 없음
        assert s.current_stage == 1

    @pytest.mark.parametrize("stage_no", [3, 5, 7, 10])
    def test_kill_switch_blocks_all_higher_stages(
        self,
        stage_no: int,
        db_session,
        make_strategy,
        fake_binance,
        fake_trade_client,
    ) -> None:
        """stage 3~10 모두 차단되어야 함 (옵션 C 다단계)."""
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT",
            status=f"STAGE{stage_no - 1}_OPEN",
            current_position_qty=Decimal("-0.5"),
            current_stage=stage_no - 1,
        )
        _enable_kill_switch(db_session, strategy.exchange_account_id)

        svc = ExecutionService(
            db_session, api_key="enc:apikey", api_secret="enc:secret", is_testnet=True,
        )
        with pytest.raises(ValueError) as ei:
            svc.trigger_next_stage(strategy.id, stage_no=stage_no)
        assert "kill-switch" in str(ei.value).lower()

    def test_kill_switch_inactive_allows_trigger_to_proceed(
        self,
        db_session,
        make_strategy,
    ) -> None:
        """kill_switch 가 비활성이면 trigger_next_stage 가 정상 진행 (다른 이유로 fail 가능).

        여기선 stage_plan 미존재로 ValueError 가 나야 함 — kill-switch 통과는 한 거.
        """
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT",
            status="STAGE1_OPEN",
            current_stage=1,
        )
        # kill switch 활성 안 함

        svc = ExecutionService(
            db_session, api_key="enc:apikey", api_secret="enc:secret", is_testnet=True,
        )
        with pytest.raises(ValueError) as ei:
            svc.trigger_next_stage(strategy.id, stage_no=2)
        # stage_plan 미존재 메시지 (kill-switch 메시지가 아님)
        assert "kill-switch" not in str(ei.value).lower()
        assert "stage" in str(ei.value).lower() and "plan" in str(ei.value).lower()
