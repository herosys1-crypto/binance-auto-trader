"""PATCH /strategies/{id}/settings — in-place TP/SL 수정 (포지션/단계 유지).

사용자 요청 (2026-05-04): 수정 모드에 "종료 없이 재시작" 옵션.
구현: 새 template clone (override TP/SL) + strategy.strategy_template_id 갱신.

검증 항목:
- 활성 strategy 의 TP/SL 갱신 + 새 template 생성 확인
- 포지션/단계/현재 stage 보존
- 종료된 strategy 거부 (404 또는 400)
- 다른 user 의 strategy 차단
- side / leverage / stages_config 변경 시도 시 무시 (payload 에 없음)
- 부분 update (tp1 만) 시 나머지는 원본 유지
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.strategies import (
    StrategySettingsUpdate,
    update_strategy_settings_in_place,
)
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_template import StrategyTemplate


class TestUpdateStrategySettingsInPlace:
    def test_full_tp_sl_update_creates_new_template(
        self, db_session, make_strategy, make_template
    ) -> None:
        tpl = make_template(
            tp1_percent=Decimal("10"), tp2_percent=Decimal("15"),
            tp3_percent=Decimal("20"), tp4_percent=Decimal("25"),
            tp5_percent=Decimal("30"),
            stop_loss_percent_of_capital=Decimal("50"),
        )
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE2_OPEN",
            current_position_qty=Decimal("-0.5"),
            current_stage=2,
            template=tpl,
        )
        original_tpl_id = s.strategy_template_id
        original_qty = s.current_position_qty
        original_stage = s.current_stage

        resp = update_strategy_settings_in_place(
            strategy_id=s.id,
            payload=StrategySettingsUpdate(
                tp1_percent=Decimal("5"), tp2_percent=Decimal("10"),
                tp3_percent=Decimal("15"), tp4_percent=Decimal("20"),
                tp5_percent=Decimal("25"),
                tp1_qty_ratio=Decimal("30"),
                stop_loss_percent_of_capital=Decimal("40"),
            ),
            db=db_session,
            user_id=s.user_id,
        )

        # template_id 가 새 것으로 갱신
        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        assert s2.strategy_template_id != original_tpl_id

        # 새 template 의 TP/SL 값 검증
        new_tpl = db_session.get(StrategyTemplate, s2.strategy_template_id)
        assert new_tpl.tp1_percent == Decimal("5")
        assert new_tpl.tp2_percent == Decimal("10")
        assert new_tpl.tp3_percent == Decimal("15")
        assert new_tpl.tp4_percent == Decimal("20")
        assert new_tpl.tp5_percent == Decimal("25")
        assert new_tpl.tp1_qty_ratio == Decimal("30")
        assert new_tpl.stop_loss_percent_of_capital == Decimal("40")
        # 새 template 은 is_active=False (다른 신규 strategy 가 선택 못 하게)
        assert new_tpl.is_active is False

        # 포지션 + 단계 보존 (in-place 의도)
        assert s2.current_position_qty == original_qty
        assert s2.current_stage == original_stage
        assert s2.status == "STAGE2_OPEN"

        # response 필드 확인
        assert resp.id == s.id

    def test_partial_update_preserves_unchanged_fields(
        self, db_session, make_strategy, make_template
    ) -> None:
        """tp1 만 update → tp2~5/SL 은 원본 그대로."""
        tpl = make_template(
            tp1_percent=Decimal("10"), tp2_percent=Decimal("15"),
            tp3_percent=Decimal("20"),
            tp1_qty_ratio=Decimal("25"), tp2_qty_ratio=Decimal("50"),
            stop_loss_percent_of_capital=Decimal("50"),
        )
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN",
            current_position_qty=Decimal("-0.5"), current_stage=1,
            template=tpl,
        )

        update_strategy_settings_in_place(
            strategy_id=s.id,
            payload=StrategySettingsUpdate(tp1_percent=Decimal("7")),
            db=db_session, user_id=s.user_id,
        )

        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        new_tpl = db_session.get(StrategyTemplate, s2.strategy_template_id)
        assert new_tpl.tp1_percent == Decimal("7")  # 변경
        # 나머지 원본 보존
        assert new_tpl.tp2_percent == Decimal("15")
        assert new_tpl.tp3_percent == Decimal("20")
        assert new_tpl.tp1_qty_ratio == Decimal("25")
        assert new_tpl.tp2_qty_ratio == Decimal("50")
        assert new_tpl.stop_loss_percent_of_capital == Decimal("50")

    def test_terminal_strategy_rejected(
        self, db_session, make_strategy, make_template
    ) -> None:
        """COMPLETED / STOPPED 등 종료된 strategy 는 거부."""
        tpl = make_template()
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="COMPLETED",
            current_position_qty=Decimal("0"),
            template=tpl,
        )
        with pytest.raises(HTTPException) as ei:
            update_strategy_settings_in_place(
                strategy_id=s.id,
                payload=StrategySettingsUpdate(tp1_percent=Decimal("5")),
                db=db_session, user_id=s.user_id,
            )
        assert ei.value.status_code == 400
        assert "in-place" in ei.value.detail.lower() or "종료" in ei.value.detail

    def test_other_user_strategy_returns_404(
        self, db_session, make_user, make_strategy, make_template
    ) -> None:
        owner = make_user()
        tpl = make_template()
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN",
            current_position_qty=Decimal("-0.5"),
            template=tpl, user=owner,
        )
        intruder = make_user()
        with pytest.raises(HTTPException) as ei:
            update_strategy_settings_in_place(
                strategy_id=s.id,
                payload=StrategySettingsUpdate(tp1_percent=Decimal("99")),
                db=db_session, user_id=intruder.id,
            )
        assert ei.value.status_code == 404

    def test_nonexistent_strategy_returns_404(
        self, db_session, make_user
    ) -> None:
        u = make_user()
        with pytest.raises(HTTPException) as ei:
            update_strategy_settings_in_place(
                strategy_id=99999,
                payload=StrategySettingsUpdate(tp1_percent=Decimal("5")),
                db=db_session, user_id=u.id,
            )
        assert ei.value.status_code == 404

    def test_side_leverage_stages_preserved_no_payload_for_them(
        self, db_session, make_strategy, make_template
    ) -> None:
        """side/leverage/stages_config 는 payload 에 받지 않음 → 원본 유지.

        (안전: 활성 포지션이 있는 상태에서 side/leverage/stages 변경은 위험.
        이 테스트는 schema 가 그 필드들을 거부하는지 + clone 시 보존되는지 확인.)
        """
        tpl = make_template(
            side="SHORT", leverage=10,
            stages_config={"capitals": [100, 200, 300], "trigger_percents": [None, 10, 20]},
        )
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN",
            current_position_qty=Decimal("-0.5"), current_stage=1, leverage=10,
            template=tpl,
        )

        # Pydantic 자체가 side/leverage/stages 같은 필드를 모름 (모델에 없음)
        # 그냥 TP/SL 만 update
        update_strategy_settings_in_place(
            strategy_id=s.id,
            payload=StrategySettingsUpdate(tp1_percent=Decimal("8")),
            db=db_session, user_id=s.user_id,
        )

        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        new_tpl = db_session.get(StrategyTemplate, s2.strategy_template_id)
        # 원본 template 의 side/leverage/stages 보존
        assert new_tpl.side == "SHORT"
        assert new_tpl.leverage == 10
        assert new_tpl.stages_config == {"capitals": [100, 200, 300], "trigger_percents": [None, 10, 20]}
        # strategy 의 leverage 도 그대로
        assert s2.leverage == 10

    def test_crisis_qty_ratios_update(
        self, db_session, make_strategy, make_template
    ) -> None:
        """v3 의 crisis_qty_ratios 도 in-place 갱신 가능."""
        tpl = make_template(crisis_qty_ratios=None)
        s = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="STAGE1_OPEN",
            current_position_qty=Decimal("-0.5"), current_stage=1,
            template=tpl,
        )
        update_strategy_settings_in_place(
            strategy_id=s.id,
            payload=StrategySettingsUpdate(crisis_qty_ratios={"TP1": 30, "TP2": 30}),
            db=db_session, user_id=s.user_id,
        )
        db_session.expire_all()
        s2 = db_session.get(StrategyInstance, s.id)
        new_tpl = db_session.get(StrategyTemplate, s2.strategy_template_id)
        assert new_tpl.crisis_qty_ratios == {"TP1": 30, "TP2": 30}

    def test_validates_negative_tp_rejected(self) -> None:
        """Pydantic gt=0 가드."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            StrategySettingsUpdate(tp1_percent=Decimal("-5"))
        with pytest.raises(ValidationError):
            StrategySettingsUpdate(tp1_qty_ratio=Decimal("0"))
        with pytest.raises(ValidationError):
            StrategySettingsUpdate(tp1_qty_ratio=Decimal("101"))  # le=100
