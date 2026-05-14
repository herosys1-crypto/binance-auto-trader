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

    def test_existing_pending_limit_blocks_duplicate(
        self, db_session, make_strategy, make_template
    ) -> None:
        """사용자 #96 사례: 같은 stage 의 NEW LIMIT 가 거래소에 이미 있으면 거부.
        is_triggered=False 인 plan 이라도 Order NEW 가 있으면 중복 차단."""
        from app.models.order import Order
        from app.models.strategy_stage_plan import StrategyStagePlan
        tpl = make_template(stages_config={"capitals": [50, 50, 50]})
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN",
            current_position_qty=Decimal("-0.5"), current_stage=1,
            template=tpl,
        )
        # stage 2 plan + NEW Order 미리 (이전 「▶」 클릭으로 발송된 LIMIT 시뮬)
        db_session.add(StrategyStagePlan(
            strategy_instance_id=s.id, stage_no=2, side="SHORT",
            trigger_mode="PRICE_UP_PCT", trigger_percent=Decimal("10"),
            trigger_price=Decimal("55000"), planned_capital=Decimal("100"),
            planned_qty=Decimal("0.001"), is_triggered=False,
        ))
        db_session.add(Order(
            strategy_instance_id=s.id, stage_no=2, purpose="ENTRY",
            symbol="BTCUSDT", side="SELL", position_side="SHORT",
            order_type="LIMIT", time_in_force="GTC",
            client_order_id="prev-limit-stage2",
            orig_qty=Decimal("0.001"), price=Decimal("55000"),
            status="NEW",
        ))
        db_session.commit()

        with pytest.raises(HTTPException) as ei:
            trigger_next_stage_manually(strategy_id=s.id, db=db_session, user_id=s.user_id)
        assert ei.value.status_code == 400
        assert "이미 거래소에 미체결" in ei.value.detail
        assert "Stage 2" in ei.value.detail or "stage 2" in ei.value.detail.lower()

    def test_atomic_claim_blocks_double_market_when_already_triggered(
        self, db_session, make_strategy, make_template
    ) -> None:
        """2026-05-04 fix v3 (Phase 1 race): is_triggered=True 인 plan 에 ▶ 호출 시
        atomic UPDATE 가 0 rows → 400. (race window 의 두 번째 호출 시뮬)."""
        from app.models.strategy_stage_plan import StrategyStagePlan
        tpl = make_template(stages_config={"capitals": [50, 50, 50]})
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN",
            current_position_qty=Decimal("-0.5"), current_stage=1,
            template=tpl,
        )
        # 1차 호출이 이미 처리한 결과: stage 2 plan.is_triggered=True (race window 의 후속)
        db_session.add(StrategyStagePlan(
            strategy_instance_id=s.id, stage_no=2, side="SHORT",
            trigger_mode="PRICE_UP_PCT", trigger_percent=Decimal("10"),
            trigger_price=Decimal("55000"), planned_capital=Decimal("100"),
            planned_qty=Decimal("0.001"), is_triggered=True,
        ))
        db_session.commit()

        with pytest.raises(HTTPException) as ei:
            trigger_next_stage_manually(strategy_id=s.id, db=db_session, user_id=s.user_id)
        assert ei.value.status_code == 400
        assert "이미 진입됨" in ei.value.detail or "다른 요청이 처리" in ei.value.detail

    def test_market_failure_rolls_back_atomic_claim(
        self, db_session, make_strategy, make_template, make_exchange_account, monkeypatch
    ) -> None:
        """enter_stage_at_market 실패 시 is_triggered=False 로 롤백 → 다시 시도 가능.
        atomic claim 이 'stuck triggered' 상태로 잠그면 안 됨."""
        from app.models.strategy_stage_plan import StrategyStagePlan
        from app.services.execution_service import ExecutionService

        tpl = make_template(stages_config={"capitals": [50, 50, 50]})
        ea = make_exchange_account()
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN",
            current_position_qty=Decimal("-0.5"), current_stage=1,
            template=tpl, exchange_account=ea,
        )
        db_session.add(StrategyStagePlan(
            strategy_instance_id=s.id, stage_no=2, side="SHORT",
            trigger_mode="PRICE_UP_PCT", trigger_percent=Decimal("10"),
            trigger_price=Decimal("55000"), planned_capital=Decimal("100"),
            planned_qty=Decimal("0.001"), is_triggered=False,
        ))
        db_session.commit()

        # decrypt_text 우회 — fake account.
        # 2026-05-14 Phase 4: strategies.py 분할 후 source 모듈 직접 patch (더 견고).
        # 다른 테스트들 (test_strategy_capital_limits.py 등) 도 같은 패턴 사용.
        monkeypatch.setattr("app.core.crypto.decrypt_text", lambda s: "fake")
        # control.py 가 이미 from app.core.crypto import decrypt_text 한 상태므로
        # control 모듈 내 reference 도 같이 patch.
        from app.api.v1.strategies import control as _strategies_control
        monkeypatch.setattr(_strategies_control, "decrypt_text", lambda s: "fake")
        # ExecutionService.enter_stage_at_market 가 거래소 통신 실패 raise 라고 시뮬
        def _boom(self, strategy_id, stage_no):  # noqa: ANN001, ARG001
            raise RuntimeError("Binance API timeout")
        monkeypatch.setattr(ExecutionService, "enter_stage_at_market", _boom)

        with pytest.raises(HTTPException) as ei:
            trigger_next_stage_manually(strategy_id=s.id, db=db_session, user_id=s.user_id)
        assert ei.value.status_code == 502  # Exchange error
        assert "Binance API timeout" in ei.value.detail

        # 롤백 검증: stage 2 plan 의 is_triggered 가 False 로 복구됐어야 함
        db_session.expire_all()
        plan = db_session.execute(
            select(StrategyStagePlan)
            .where(StrategyStagePlan.strategy_instance_id == s.id)
            .where(StrategyStagePlan.stage_no == 2)
        ).scalar_one()
        assert plan.is_triggered is False, (
            "enter_stage_at_market 실패 시 atomic claim (is_triggered=True) 이 "
            "롤백돼야 stuck 상태 회피 + 재시도 가능"
        )


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


# ============================================================================
# Phase 3b — capitals in-place 변경 (2026-05-05)
# ============================================================================
class TestSettingsUpdateWithCapitals:
    def _create(self, db_session, make_strategy, make_template, make_symbol,
                *, current_stage: int = 1, n_stages: int = 3, capitals_str=None):
        sym = make_symbol("BTCUSDT")
        capitals_str = capitals_str or [str(50 * (i + 1)) for i in range(n_stages)]
        tpl = make_template(
            stages_config={
                "capitals": capitals_str,
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
        for i in range(n_stages):
            stage_no = i + 1
            db_session.add(StrategyStagePlan(
                strategy_instance_id=s.id,
                stage_no=stage_no,
                side=s.side,
                trigger_mode="IMMEDIATE" if stage_no == 1 else "PRICE_UP_PCT",
                trigger_percent=Decimal("10") if stage_no > 1 else None,
                trigger_price=Decimal("50000") + Decimal(stage_no - 1) * Decimal("5000"),
                planned_capital=Decimal(capitals_str[i]),
                planned_qty=Decimal("0.001"),
                is_triggered=stage_no <= current_stage,
            ))
        db_session.commit()
        return s, tpl

    def test_change_unentered_stage_capital(
        self, db_session, make_strategy, make_template, make_symbol
    ) -> None:
        """current_stage=1, stage 2/3 capital 변경 → planned_capital 재계산."""
        s, _ = self._create(db_session, make_strategy, make_template, make_symbol,
                            current_stage=1, n_stages=3)
        update_strategy_settings_in_place(
            strategy_id=s.id,
            payload=StrategySettingsUpdate(
                capitals=[None, Decimal("200"), Decimal("300")],
            ),
            db=db_session, user_id=s.user_id,
        )
        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        new_tpl = db_session.get(StrategyTemplate, s2.strategy_template_id)
        assert new_tpl.stages_config["capitals"][1] == "200"
        assert new_tpl.stages_config["capitals"][2] == "300"
        # plan 의 planned_capital 도 갱신됐어야
        plans = db_session.execute(
            select(StrategyStagePlan).where(StrategyStagePlan.strategy_instance_id == s.id)
        ).scalars().all()
        for p in plans:
            if p.stage_no == 1:
                assert p.is_triggered is True  # 발동된 plan 보존
            elif p.stage_no == 2:
                assert p.planned_capital == Decimal("200")
            elif p.stage_no == 3:
                assert p.planned_capital == Decimal("300")

    def test_capital_already_entered_rejected(
        self, db_session, make_strategy, make_template, make_symbol
    ) -> None:
        """current_stage=2, stage 2 capital 변경 시도 → 400."""
        s, _ = self._create(db_session, make_strategy, make_template, make_symbol,
                            current_stage=2, n_stages=3)
        with pytest.raises(HTTPException) as ei:
            update_strategy_settings_in_place(
                strategy_id=s.id,
                payload=StrategySettingsUpdate(
                    capitals=[None, Decimal("999"), None],  # stage 2 변경 시도
                ),
                db=db_session, user_id=s.user_id,
            )
        assert ei.value.status_code == 400
        assert "이미 진입한 단계" in ei.value.detail

    def test_capitals_and_triggers_length_mismatch_rejected(
        self, db_session, make_strategy, make_template, make_symbol
    ) -> None:
        s, _ = self._create(db_session, make_strategy, make_template, make_symbol,
                            current_stage=1, n_stages=3)
        with pytest.raises(HTTPException) as ei:
            update_strategy_settings_in_place(
                strategy_id=s.id,
                payload=StrategySettingsUpdate(
                    capitals=[None, Decimal("200"), Decimal("300"), Decimal("400")],  # 길이 4
                    trigger_percents=[None, Decimal("10"), Decimal("15")],  # 길이 3
                ),
                db=db_session, user_id=s.user_id,
            )
        assert ei.value.status_code == 400
        assert "일치" in ei.value.detail


# ============================================================================
# Phase 3c — 단계 수 변경 (추가/제거) (2026-05-05)
# ============================================================================
class TestSettingsUpdateWithStageCountChange:
    def _create(self, db_session, make_strategy, make_template, make_symbol,
                *, current_stage: int = 1, n_stages: int = 3):
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

    def test_add_stage_increases_count(
        self, db_session, make_strategy, make_template, make_symbol
    ) -> None:
        """3단계 → 4단계 (capital 4 추가) → stage 4 plan 신규 생성."""
        s, _ = self._create(db_session, make_strategy, make_template, make_symbol,
                            current_stage=1, n_stages=3)
        update_strategy_settings_in_place(
            strategy_id=s.id,
            payload=StrategySettingsUpdate(
                capitals=[None, None, None, Decimal("400")],  # 길이 4, 새 stage 4
                trigger_percents=[None, None, None, Decimal("20")],
            ),
            db=db_session, user_id=s.user_id,
        )
        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        new_tpl = db_session.get(StrategyTemplate, s2.strategy_template_id)
        assert len(new_tpl.stages_config["capitals"]) == 4
        assert new_tpl.stages_config["capitals"][3] == "400"
        # 신규 plan 생성됐어야
        plans = db_session.execute(
            select(StrategyStagePlan).where(StrategyStagePlan.strategy_instance_id == s.id)
        ).scalars().all()
        stage_nos = sorted(p.stage_no for p in plans)
        assert stage_nos == [1, 2, 3, 4]
        plan4 = next(p for p in plans if p.stage_no == 4)
        assert plan4.is_triggered is False
        assert plan4.planned_capital == Decimal("400")

    def test_remove_stage_decreases_count(
        self, db_session, make_strategy, make_template, make_symbol
    ) -> None:
        """3단계 → 2단계 (current_stage=1) → stage 3 plan 삭제."""
        s, _ = self._create(db_session, make_strategy, make_template, make_symbol,
                            current_stage=1, n_stages=3)
        update_strategy_settings_in_place(
            strategy_id=s.id,
            payload=StrategySettingsUpdate(
                capitals=[None, None],  # 길이 2 (stage 3 제거)
                trigger_percents=[None, None],
            ),
            db=db_session, user_id=s.user_id,
        )
        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        new_tpl = db_session.get(StrategyTemplate, s2.strategy_template_id)
        assert len(new_tpl.stages_config["capitals"]) == 2
        plans = db_session.execute(
            select(StrategyStagePlan).where(StrategyStagePlan.strategy_instance_id == s.id)
        ).scalars().all()
        stage_nos = sorted(p.stage_no for p in plans)
        assert stage_nos == [1, 2]  # stage 3 삭제됨

    def test_remove_below_current_stage_rejected(
        self, db_session, make_strategy, make_template, make_symbol
    ) -> None:
        """current_stage=2, capitals 길이 1 시도 → 400 (이미 발동한 stage 보존 필수)."""
        s, _ = self._create(db_session, make_strategy, make_template, make_symbol,
                            current_stage=2, n_stages=3)
        with pytest.raises(HTTPException) as ei:
            update_strategy_settings_in_place(
                strategy_id=s.id,
                payload=StrategySettingsUpdate(
                    capitals=[None],
                    trigger_percents=[None],
                ),
                db=db_session, user_id=s.user_id,
            )
        assert ei.value.status_code == 400
        assert "current_stage" in ei.value.detail
        # plan 들 보존됐어야 — DB 상태 변경 X
        plans = db_session.execute(
            select(StrategyStagePlan).where(StrategyStagePlan.strategy_instance_id == s.id)
        ).scalars().all()
        assert len(plans) == 3

    def test_new_stage_capital_required(
        self, db_session, make_strategy, make_template, make_symbol
    ) -> None:
        """3단계 → 4단계인데 stage 4 capital 가 None → 400."""
        s, _ = self._create(db_session, make_strategy, make_template, make_symbol,
                            current_stage=1, n_stages=3)
        with pytest.raises(HTTPException) as ei:
            update_strategy_settings_in_place(
                strategy_id=s.id,
                payload=StrategySettingsUpdate(
                    capitals=[None, None, None, None],  # 길이 4 인데 신규 stage 4 capital None
                    trigger_percents=[None, None, None, Decimal("20")],
                ),
                db=db_session, user_id=s.user_id,
            )
        assert ei.value.status_code == 400
        assert "신규 stage" in ei.value.detail or "capital" in ei.value.detail.lower()
