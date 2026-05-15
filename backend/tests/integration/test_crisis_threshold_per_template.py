"""크라이시스 임계 template 별 사용자 정의 (alembic 0015, 사용자 요청 2026-05-14).

배경:
이전엔 hardcoded -50%. 사용자 위험 선호 다양:
- 보수적: -60%, -70%, -80% (더 깊은 손실에서만 진입)
- 비활성: -100% (영원히 미발동)

검증:
1. NULL → global default -50% 사용 (기존 동작 유지)
2. -60 / -70 / -80 → 그 임계 사용
3. -100 → 어떤 손실로도 미발동
4. 기존 다른 진입 조건 (모든 단계 진입) 은 동일 적용
"""
from __future__ import annotations

from decimal import Decimal


class TestTemplateCrisisThresholdNull:
    """template.crisis_max_loss_threshold = NULL → global -50% 사용 (기존 동작)."""

    def test_null_uses_global_minus_50(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy
    ):
        from app.services.risk_service import RiskService
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        # NULL = global default -50% 사용
        tpl = make_template(stages_config={"capitals": ["100"] * 3})
        # crisis_max_loss_threshold 안 넘김 → NULL
        s = make_strategy(
            user=u, exchange_account=ea, template=tpl,
            current_stage=3, max_loss_pct=Decimal("-55"),
        )
        rs = RiskService(db_session)
        assert rs._should_trigger_crisis_mode(s, Decimal("0")) is True, (
            "NULL → global -50% → max_loss=-55 면 진입 ✓"
        )

    def test_null_above_minus_50_no_crisis(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy
    ):
        from app.services.risk_service import RiskService
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(stages_config={"capitals": ["100"] * 3})
        s = make_strategy(
            user=u, exchange_account=ea, template=tpl,
            current_stage=3, max_loss_pct=Decimal("-45"),
        )
        rs = RiskService(db_session)
        assert rs._should_trigger_crisis_mode(s, Decimal("0")) is False


class TestTemplateCrisisThresholdConservative:
    """더 보수적 임계 (-60, -70, -80) — 그 임계 이하만 진입."""

    def test_minus_60_threshold(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy
    ):
        from app.services.risk_service import RiskService
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(
            stages_config={"capitals": ["100"] * 3},
            crisis_max_loss_threshold=Decimal("-60"),
        )
        s_below = make_strategy(
            user=u, exchange_account=ea, template=tpl,
            current_stage=3, max_loss_pct=Decimal("-55"),
        )
        s_at = make_strategy(
            user=u, exchange_account=ea, template=tpl,
            current_stage=3, max_loss_pct=Decimal("-60"),
        )
        rs = RiskService(db_session)
        # -55 > -60 (덜 깊은 손실) → 미발동
        assert rs._should_trigger_crisis_mode(s_below, Decimal("0")) is False, (
            "임계 -60, max_loss -55 면 미달 → 미발동"
        )
        # -60 == -60 → 발동
        assert rs._should_trigger_crisis_mode(s_at, Decimal("0")) is True, (
            "임계 -60, max_loss -60 면 정확 도달 → 발동"
        )

    def test_minus_80_very_conservative(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy
    ):
        from app.services.risk_service import RiskService
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(
            stages_config={"capitals": ["100"] * 3},
            crisis_max_loss_threshold=Decimal("-80"),
        )
        # -75 < -80 (덜 깊음) → 미발동
        s = make_strategy(
            user=u, exchange_account=ea, template=tpl,
            current_stage=3, max_loss_pct=Decimal("-75"),
        )
        rs = RiskService(db_session)
        assert rs._should_trigger_crisis_mode(s, Decimal("0")) is False
        # -85 < -80 → 발동
        s2 = make_strategy(
            user=u, exchange_account=ea, template=tpl,
            current_stage=3, max_loss_pct=Decimal("-85"),
        )
        assert rs._should_trigger_crisis_mode(s2, Decimal("0")) is True


class TestTemplateCrisisThresholdDisabled:
    """-100 = 크라이시스 비활성 (어떤 손실로도 미발동)."""

    def test_minus_100_never_triggers(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy
    ):
        from app.services.risk_service import RiskService
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(
            stages_config={"capitals": ["100"] * 3},
            crisis_max_loss_threshold=Decimal("-100"),
        )
        # -50, -90, -200 모두 미발동
        for ml in [Decimal("-50"), Decimal("-90"), Decimal("-200")]:
            s = make_strategy(
                user=u, exchange_account=ea, template=tpl,
                current_stage=3, max_loss_pct=ml,
            )
            rs = RiskService(db_session)
            assert rs._should_trigger_crisis_mode(s, Decimal("0")) is False, (
                f"-100 임계 = 비활성 → max_loss {ml} 도 미발동"
            )

    def test_below_minus_100_also_disabled(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy
    ):
        """더 깊은 음수 (-150, -200 등) 도 비활성."""
        from app.services.risk_service import RiskService
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(
            stages_config={"capitals": ["100"] * 3},
            crisis_max_loss_threshold=Decimal("-150"),
        )
        s = make_strategy(
            user=u, exchange_account=ea, template=tpl,
            current_stage=3, max_loss_pct=Decimal("-200"),
        )
        rs = RiskService(db_session)
        assert rs._should_trigger_crisis_mode(s, Decimal("0")) is False


class TestStageRequirementStillApplies:
    """크라이시스 임계 변경해도 「모든 단계 진입」 조건은 그대로 적용."""

    def test_partial_stage_no_crisis_even_with_minus_50(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, make_strategy
    ):
        from app.services.risk_service import RiskService
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template(
            stages_config={"capitals": ["100"] * 5},
            crisis_max_loss_threshold=Decimal("-50"),
        )
        # stage 3/5 만 진입 + max_loss -60% — 깊은 손실이지만 모든 단계 미진입 → 미발동
        s = make_strategy(
            user=u, exchange_account=ea, template=tpl,
            current_stage=3, max_loss_pct=Decimal("-60"),
        )
        rs = RiskService(db_session)
        assert rs._should_trigger_crisis_mode(s, Decimal("0")) is False, (
            "current_stage=3 < total_stages=5 면 임계 도달해도 미발동"
        )
