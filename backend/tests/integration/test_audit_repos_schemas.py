"""audit fix 회귀 (repos + schemas):
1. ExchangeAccountRepository.get_first_active_binance(user_id) — user 격리
2. RiskEventResponse.strategy_instance_id Optional — NULL 직렬화 안전
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.exchange_account import ExchangeAccount
from app.repositories.exchange_account_repository import ExchangeAccountRepository
from app.schemas.risk import RiskEventResponse


# ============================================================================
# get_first_active_binance — user_id 격리
# ============================================================================
class TestGetFirstActiveBinanceUserFilter:
    def test_user_id_returns_only_owner_account(
        self, db_session, make_user, make_exchange_account
    ) -> None:
        u_a = make_user()
        u_b = make_user()
        # u_a 가 먼저 등록 (ID 작음), u_b 가 나중에 등록 (ID 큼)
        ea_a = make_exchange_account(user=u_a)
        ea_b = make_exchange_account(user=u_b)

        # u_b 의 user_id 로 호출 → ea_b 만 반환 (ea_a 가 먼저 active 라도 격리)
        repo = ExchangeAccountRepository(db_session)
        result_b = repo.get_first_active_binance(user_id=u_b.id)
        assert result_b is not None
        assert result_b.id == ea_b.id

        result_a = repo.get_first_active_binance(user_id=u_a.id)
        assert result_a.id == ea_a.id

    def test_user_id_none_returns_any_active_account_legacy(
        self, db_session, make_user, make_exchange_account
    ) -> None:
        """user_id=None → legacy 동작 (모든 user 의 첫 active)."""
        u = make_user()
        ea = make_exchange_account(user=u)
        repo = ExchangeAccountRepository(db_session)
        result = repo.get_first_active_binance(user_id=None)
        assert result is not None
        assert result.id == ea.id

    def test_user_with_no_account_returns_none(
        self, db_session, make_user, make_exchange_account
    ) -> None:
        """user_id 가 active 계정 없으면 None — 다른 user 의 계정 노출 안 함."""
        u_a = make_user()
        make_exchange_account(user=u_a)  # u_a 의 계정 있음
        u_b = make_user()  # u_b 는 계정 없음
        repo = ExchangeAccountRepository(db_session)
        result = repo.get_first_active_binance(user_id=u_b.id)
        assert result is None

    def test_inactive_account_excluded(
        self, db_session, make_user, make_exchange_account
    ) -> None:
        u = make_user()
        make_exchange_account(user=u, is_active=False)  # inactive
        repo = ExchangeAccountRepository(db_session)
        result = repo.get_first_active_binance(user_id=u.id)
        assert result is None


# ============================================================================
# RiskEventResponse — Optional strategy_instance_id
# ============================================================================
class TestRiskEventResponseOptionalStrategyId:
    def test_null_strategy_instance_id_serializes(self) -> None:
        """alembic 0008 이후 시스템 이벤트는 NULL strategy_instance_id 가능."""
        # NULL 필드 직렬화 — 이전엔 ValidationError
        resp = RiskEventResponse(
            id=1,
            strategy_instance_id=None,
            event_type="LISTEN_KEY_EXPIRED",
            severity="WARN",
            title="시스템 이벤트",
            message=None,
            event_payload=None,
            created_at=datetime.now(timezone.utc),
        )
        assert resp.strategy_instance_id is None

    def test_int_strategy_instance_id_serializes(self) -> None:
        """기존 strategy 별 이벤트도 그대로 직렬화."""
        resp = RiskEventResponse(
            id=2,
            strategy_instance_id=42,
            event_type="STOP_LOSS_TRIGGERED",
            severity="CRITICAL",
            title="손절",
            message="...",
            event_payload={"x": 1},
            created_at=datetime.now(timezone.utc),
        )
        assert resp.strategy_instance_id == 42

    def test_validate_from_orm_with_null(self) -> None:
        """from_attributes=True 로 ORM 객체 → schema 직렬화 시 NULL 허용."""
        from types import SimpleNamespace
        fake_row = SimpleNamespace(
            id=3, strategy_instance_id=None,
            event_type="ZOMBIE_ORPHAN_EXCHANGE_POSITION",
            severity="CRITICAL", title="orphan", message="...",
            event_payload={"acct": 5}, created_at=datetime.now(timezone.utc),
        )
        resp = RiskEventResponse.model_validate(fake_row)
        assert resp.strategy_instance_id is None
        assert resp.title == "orphan"
