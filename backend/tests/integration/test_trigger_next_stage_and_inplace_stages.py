"""사용자 요청 2026-05-04 (3가지 신규):
1. POST /strategies/{id}/trigger-next-stage — 수동 다음 단계 즉시 진입
2. PATCH /strategies/{id}/settings (확장) — 미발동 단계 trigger_percents 갱신
3. (UI 만 — 「💰 증거금 추가」 버튼 위치 — 회귀 테스트 불필요)
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.strategies import (
    StrategySettingsUpdate,
    trigger_next_stage_manually,
    update_strategy_settings_in_place,
)
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_stage_plan import StrategyStagePlan
from app.models.strategy_template import StrategyTemplate


# ============================================================================
# Feature 2 — 수동 다음 단계 즉시 진입
# ============================================================================
class TestTriggerNextStageManually:
    def test_terminal_strategy_rejected(
        self, db_session, make_strategy, make_template
    ) -> None:
        tpl = make_template()
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="COMPLETED",
            current_position_qty=Decimal("0"),
            template=tpl,
        )
        with pytest.raises(HTTPException) as ei:
            trigger_next_stage_manually(strategy_id=s.id, db=db_session, user_id=s.user_id)
        assert ei.value.status_code == 400
        assert "종료" in ei.value.detail

    def test_other_user_returns_404(
        self, db_session, make_user, make_strategy, make_template
    ) -> None:
        owner = make_user()
        tpl = make_template()
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN",
            template=tpl, user=owner,
        )
        intruder = make_user()
        with pytest.raises(HTTPException) as ei:
            trigger_next_stage_manually(strategy_id=s.id, db=db_session, user_id=intruder.id)
        assert ei.value.status_code == 404

    def test_all_stages_done_rejected(
        self, db_session, make_strategy, make_template
    ) -> None:
        """모든 단계 진입 완료 → 400."""
        tpl = make_template(
            stages_config={"capitals": [50, 50], "trigger_percents": [None, 10]},
        )
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
            current_stage=2,  # 2/2 완료
            template=tpl,
        )
        with pytest.raises(HTTPException) as ei:
            trigger_next_stage_manually(strategy_id=s.id, db=db_session, user_id=s.user_id)
        assert ei.value.status_code == 400
        assert "모든 단계" in ei.value.detail

    def test_stage_plan_missing_rejected(
        self, db_session, make_strategy, make_template
    ) -> None:
        """current_stage+1 의 plan 이 없으면 400."""
        tpl = make_template(stages_config={"capitals": [50, 50, 50]})
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN",
            current_position_qty=Decimal("-0.5"), current_stage=1,
            template=tpl,
        )
        # plan 안 만듦 — make_strategy 가 plan 생성 안 함
        with pytest.raises(HTTPException) as ei:
            trigger_next_stage_manually(strategy_id=s.id, db=db_session, user_id=s.user_id)
        assert ei.value.status_code == 400


# ============================================================================
# Feature 1 — PATCH /settings 의 trigger_percents 부분 갱신
# ============================================================================
class TestSettingsUpdateWithTriggerPercents:
    def _create_strategy_with_plans(
        self, db_session, make_strategy, make_template, make_symbol,
        *, current_stage: int = 1, n_stages: int = 3,
    ):
        from app.models.strategy_instance import StrategyInstance as _SI
        sym = make_symbol("BTCUSDT")
        tpl = make_template(
            stages_config={
                "capitals": [str(50 * (i + 1)) for i in range(n_stages)],
                "trigger_percents": [None] + ["10"] * (n_stages - 1),
            },
        )
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status=f"STAGE{current_stage}_OPEN",
            current_position_qty=Decimal("-0.5"),
            current_stage=current_stage,
            avg_entry_price=Decimal("50000"),
            template=tpl, symbol_obj=sym,
        )
        # stage_plans 생성 (current_stage 이하는 is_triggered=True)
        for i in range(n_stages):
            stage_no = i + 1
            db_session.add(StrategyStagePlan(
                strategy_instance_id=s.id,
                stage_no=stage_no,
                side=s.side,
                trigger_mode="IMMEDIATE" if stage_no == 1 else "PRICE_UP_PCT",
                trigger_percent=Decimal("10") if stage_no > 1 else None,
                trigger_price=Decimal("50000") + Decimal(stage_no - 1) * Decimal("5000"),
                planned_capital=Decimal(str(50 * stage_no)),
                planned_qty=Decimal("0.001"),
                is_triggered=stage_no <= current_stage,
            ))
        db_session.commit()
        return s, tpl

    def test_change_unentered_stage_trigger_percent(
        self, db_session, make_strategy, make_template, make_symbol
    ) -> None:
        # 4 단계 — stage 2, 3 변경 (4 는 마지막 단계라 last_stage_trigger_percent 별도 처리)
        s, _ = self._create_strategy_with_plans(
            db_session, make_strategy, make_template, make_symbol,
            current_stage=1, n_stages=4,
        )
        update_strategy_settings_in_place(
            strategy_id=s.id,
            payload=StrategySettingsUpdate(
                trigger_percents=[None, Decimal("8"), Decimal("15"), None],
            ),
            db=db_session, user_id=s.user_id,
        )

        # 새 template 의 stages_config 확인
        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        new_tpl = db_session.get(StrategyTemplate, s2.strategy_template_id)
        assert new_tpl.stages_config["trigger_percents"][1] == "8"
        assert new_tpl.stages_config["trigger_percents"][2] == "15"

        # stage_plan 의 trigger_price 재계산됐어야 (미발동 plan 만)
        plans = db_session.execute(
            select(StrategyStagePlan).where(StrategyStagePlan.strategy_instance_id == s.id)
        ).scalars().all()
        for p in plans:
            if p.stage_no == 1:
                # 발동된 plan — trigger_percent None 그대로 (변경 없음)
                assert p.is_triggered is True
            elif p.stage_no == 2:
                # 미발동 — trigger_percent 8 으로 갱신
                assert p.trigger_percent == Decimal("8")
                assert p.is_triggered is False
            elif p.stage_no == 3:
                assert p.trigger_percent == Decimal("15")

    def test_change_already_entered_stage_rejected(
        self, db_session, make_strategy, make_template, make_symbol
    ) -> None:
        """current_stage 이하 단계의 trigger_percent 변경 시도 → 400."""
        s, _ = self._create_strategy_with_plans(
            db_session, make_strategy, make_template, make_symbol,
            current_stage=2, n_stages=3,
        )
        # stage 2 변경 시도 (current_stage=2 라 거부)
        with pytest.raises(HTTPException) as ei:
            update_strategy_settings_in_place(
                strategy_id=s.id,
                payload=StrategySettingsUpdate(
                    trigger_percents=[None, Decimal("5"), None],  # stage 2 변경
                ),
                db=db_session, user_id=s.user_id,
            )
        assert ei.value.status_code == 400
        assert "이미 진입한 단계" in ei.value.detail

    def test_length_mismatch_rejected(
        self, db_session, make_strategy, make_template, make_symbol
    ) -> None:
        s, _ = self._create_strategy_with_plans(
            db_session, make_strategy, make_template, make_symbol,
            current_stage=1, n_stages=3,
        )
        with pytest.raises(HTTPException) as ei:
            update_strategy_settings_in_place(
                strategy_id=s.id,
                payload=StrategySettingsUpdate(
                    trigger_percents=[None, Decimal("8")],  # 길이 2, 단계 수 3
                ),
                db=db_session, user_id=s.user_id,
            )
        assert ei.value.status_code == 400
        assert "길이" in ei.value.detail

    def test_combined_tp_and_trigger_update(
        self, db_session, make_strategy, make_template, make_symbol
    ) -> None:
        """TP 와 trigger_percents 동시 update."""
        s, _ = self._create_strategy_with_plans(
            db_session, make_strategy, make_template, make_symbol,
            current_stage=1, n_stages=3,
        )
        update_strategy_settings_in_place(
            strategy_id=s.id,
            payload=StrategySettingsUpdate(
                tp1_percent=Decimal("7"),
                trigger_percents=[None, Decimal("12"), None],
            ),
            db=db_session, user_id=s.user_id,
        )
        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        new_tpl = db_session.get(StrategyTemplate, s2.strategy_template_id)
        assert new_tpl.tp1_percent == Decimal("7")
        assert new_tpl.stages_config["trigger_percents"][1] == "12"
