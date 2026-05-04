"""auto_reentry_worker 통합 — 실패 시 status persist 회귀 방어.

이전 (2026-05-04 fix 전):
- StrategyService.create_strategy_instance 가 raise → except 블록 진입
- strategy.last_error_message = ... (in-memory)
- db.rollback() → 메모리 변경도 같이 롤백 (영구히 lost)
- strategy.status 가 REENTRY_READY 그대로 → 다음 사이클 무한 retry

Fix 후:
- rollback 으로 진행중 변경 정리
- 새로 fetch 한 strategy 에 REENTRY_FAILED + last_error_message 명시 set + commit
- Sentry 캡처

이 테스트는 fix 동작 보장:
- 실패 케이스: 거래소 계정 inactive → REENTRY_FAILED 즉시 commit
- 예외 케이스: StrategyService 가 raise → REENTRY_FAILED 로 status 전환 + 메시지 persist
- 영구 실패 후 두 번째 사이클에 다시 후보로 안 잡힘
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.strategy_instance import StrategyInstance
from app.workers import auto_reentry_worker as arw


@pytest.fixture
def patched_arw_session(monkeypatch, engine):
    """auto_reentry_worker._do (run_auto_reentry_once) 가 만드는 SessionLocal 도
    test engine 을 쓰도록 패치."""
    from sqlalchemy.orm import sessionmaker
    test_session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    monkeypatch.setattr("app.workers.auto_reentry_worker.SessionLocal", test_session_factory)
    return test_session_factory


@pytest.fixture
def identity_decrypt():
    return lambda enc: enc


def _make_reentry_ready(make_strategy, make_template, **kwargs):
    """REENTRY_READY 상태 + reentry_policy=auto + delay 경과한 strategy 생성."""
    tpl = make_template(reentry_policy="auto", reentry_delay_seconds=600)
    past = datetime.now(timezone.utc) - timedelta(seconds=700)
    strategy = make_strategy(
        symbol_str=kwargs.pop("symbol_str", "BTCUSDT"),
        side=kwargs.pop("side", "SHORT"),
        status="REENTRY_READY",
        reentry_ready=True,
        stopped_at=past,
        template=tpl,
        **kwargs,
    )
    return strategy, tpl


# ============================================================================
# 거래소 계정 inactive 분기
# ============================================================================
class TestInactiveAccountBranch:
    def test_inactive_account_marks_failed_immediately(
        self,
        db_session,
        make_user,
        make_template,
        make_exchange_account,
        make_symbol,
        make_strategy,
        identity_decrypt,
        patched_arw_session,
    ) -> None:
        u = make_user()
        # 비활성 계정 직접 만들기 (factory 기본 is_active=True 라 override)
        ea = make_exchange_account(user=u, is_active=False)
        sym = make_symbol("BTCUSDT")
        tpl = make_template(reentry_policy="auto", reentry_delay_seconds=600)
        # sqlite 는 tzinfo 무시하므로 비교 시 type mismatch 회피 위해 naive UTC 사용.
        past = (datetime.now(timezone.utc) - timedelta(seconds=700)).replace(tzinfo=None)
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="REENTRY_READY",
            reentry_ready=True, stopped_at=past,
            user=u, exchange_account=ea, symbol_obj=sym, template=tpl,
        )
        sid = strategy.id

        arw.run_auto_reentry_once(identity_decrypt)

        db_session.expire_all()
        s = db_session.get(StrategyInstance, sid)
        assert s.status == "REENTRY_FAILED"
        assert "Exchange account inactive" in (s.last_error_message or "")


# ============================================================================
# StrategyService raise → REENTRY_FAILED 전환
# ============================================================================
class TestExceptionBranchPersistFailure:
    def test_create_strategy_failure_persists_reentry_failed(
        self,
        db_session,
        make_user,
        make_exchange_account,
        make_symbol,
        make_template,
        make_strategy,
        identity_decrypt,
        patched_arw_session,
        monkeypatch,
    ) -> None:
        """StrategyService.create_strategy_instance 가 raise 해도 REENTRY_FAILED + 메시지 persist."""
        u = make_user()
        ea = make_exchange_account(user=u, is_active=True)
        sym = make_symbol("BTCUSDT")
        tpl = make_template(reentry_policy="auto", reentry_delay_seconds=600)
        # sqlite 는 tzinfo 무시하므로 비교 시 type mismatch 회피 위해 naive UTC 사용.
        past = (datetime.now(timezone.utc) - timedelta(seconds=700)).replace(tzinfo=None)
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="REENTRY_READY",
            reentry_ready=True, stopped_at=past,
            user=u, exchange_account=ea, symbol_obj=sym, template=tpl,
        )
        sid = strategy.id

        # _fetch_current_price 패치 — 정상 응답으로 진행되게
        monkeypatch.setattr(arw, "_fetch_current_price", lambda symbol, is_testnet: Decimal("50000"))
        # StrategyService.create_strategy_instance 패치 — raise 강제
        from app.services import strategy_service as ss

        def _raise(*args, **kwargs):
            raise ValueError("simulated balance check failure")

        monkeypatch.setattr(ss.StrategyService, "create_strategy_instance", _raise)

        arw.run_auto_reentry_once(identity_decrypt)

        db_session.expire_all()
        s = db_session.get(StrategyInstance, sid)
        assert s.status == "REENTRY_FAILED", (
            "예외 발생 시 status 가 REENTRY_FAILED 로 persist 돼야 함 "
            "(이전엔 rollback 으로 in-memory 변경이 lost)"
        )
        assert "auto_reentry failed" in (s.last_error_message or "")
        assert "simulated balance check failure" in (s.last_error_message or "")

    def test_failed_strategy_not_picked_up_in_next_cycle(
        self,
        db_session,
        make_user,
        make_exchange_account,
        make_symbol,
        make_template,
        make_strategy,
        identity_decrypt,
        patched_arw_session,
        monkeypatch,
    ) -> None:
        """REENTRY_FAILED 로 전환된 strategy 는 다음 사이클에 후보로 안 잡힘 (무한 retry 방지)."""
        u = make_user()
        ea = make_exchange_account(user=u, is_active=False)  # 실패 트리거
        sym = make_symbol("BTCUSDT")
        tpl = make_template(reentry_policy="auto", reentry_delay_seconds=600)
        # sqlite 는 tzinfo 무시하므로 비교 시 type mismatch 회피 위해 naive UTC 사용.
        past = (datetime.now(timezone.utc) - timedelta(seconds=700)).replace(tzinfo=None)
        strategy = make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="REENTRY_READY",
            reentry_ready=True, stopped_at=past,
            user=u, exchange_account=ea, symbol_obj=sym, template=tpl,
        )
        sid = strategy.id

        # 1차 실행 → REENTRY_FAILED
        arw.run_auto_reentry_once(identity_decrypt)
        db_session.expire_all()
        s = db_session.get(StrategyInstance, sid)
        assert s.status == "REENTRY_FAILED"

        # _fetch_current_price 호출 횟수 추적용 spy — 두 번째 사이클에 호출되면 후보 잡혔다는 뜻.
        call_count = {"n": 0}

        def _spy_price(symbol, is_testnet):
            call_count["n"] += 1
            return Decimal("50000")

        monkeypatch.setattr(arw, "_fetch_current_price", _spy_price)

        # 2차 실행 → status REENTRY_FAILED 라 select 결과 0
        arw.run_auto_reentry_once(identity_decrypt)
        assert call_count["n"] == 0, (
            "REENTRY_FAILED 인 strategy 는 다음 사이클에서 후보로 안 잡혀야 함 — "
            "_fetch_current_price 가 호출되지 않아야 정상"
        )


# ============================================================================
# Sentry capture 호출 검증
# ============================================================================
class TestSentryCaptureOnFailure:
    def test_exception_path_calls_sentry_capture(
        self,
        db_session,
        make_user,
        make_exchange_account,
        make_symbol,
        make_template,
        make_strategy,
        identity_decrypt,
        patched_arw_session,
        monkeypatch,
    ) -> None:
        captured: list[dict] = []

        def _spy_capture(message, **kwargs):
            captured.append({"message": message, **kwargs})

        monkeypatch.setattr(arw, "capture_strategy_event", _spy_capture)
        monkeypatch.setattr(arw, "_fetch_current_price", lambda s, t: Decimal("50000"))
        from app.services import strategy_service as ss
        monkeypatch.setattr(
            ss.StrategyService, "create_strategy_instance",
            lambda *a, **kw: (_ for _ in ()).throw(ValueError("boom")),
        )

        u = make_user()
        ea = make_exchange_account(user=u, is_active=True)
        sym = make_symbol("BTCUSDT")
        tpl = make_template(reentry_policy="auto", reentry_delay_seconds=600)
        # sqlite 는 tzinfo 무시하므로 비교 시 type mismatch 회피 위해 naive UTC 사용.
        past = (datetime.now(timezone.utc) - timedelta(seconds=700)).replace(tzinfo=None)
        make_strategy(
            symbol_str="BTCUSDT", side="SHORT", status="REENTRY_READY",
            reentry_ready=True, stopped_at=past,
            user=u, exchange_account=ea, symbol_obj=sym, template=tpl,
        )

        arw.run_auto_reentry_once(identity_decrypt)

        assert len(captured) == 1
        evt = captured[0]
        assert "auto_reentry failed" in evt["message"]
        assert evt.get("level") == "error"
        assert evt.get("symbol") == "BTCUSDT"
        assert evt.get("side") == "SHORT"
        assert evt.get("tags", {}).get("event_type") == "AUTO_REENTRY_FAILED"
