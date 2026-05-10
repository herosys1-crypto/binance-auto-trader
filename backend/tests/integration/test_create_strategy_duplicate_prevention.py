"""StrategyService.create_strategy_instance — 중복 방지 에러 메시지 회귀.

배경 (사용자 보고 2026-05-04):
- LABUSDT SHORT #97 가 STOPPING 상태에서 사용자가 새 LABUSDT SHORT 만들려고 시도
- 백엔드가 차단했지만 메시지가 "기존 전략을 종료한 후" 만 안내
- 사용자: "이미 정지 눌렀는데 어떻게 더 종료해?" 혼란

Fix:
- STOPPING 케이스에 명확한 가이드 추가 (reconcile 30초 자동 정리 또는 force-stop)
- 그 외 active 케이스는 기존 안내 유지

이 테스트는 ValueError 메시지의 가이드 분기를 보장.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.strategy_service import StrategyService


def _try_create_duplicate(svc: StrategyService, *, user_id: int, exchange_account_id: int,
                          template_id: int, symbol: str, side: str) -> ValueError:
    """중복 체크에서 raise 되도록 호출 — 잡아서 ValueError 반환."""
    with pytest.raises(ValueError) as ei:
        svc.create_strategy_instance(
            user_id=user_id,
            exchange_account_id=exchange_account_id,
            strategy_template_id=template_id,
            symbol=symbol,
            side=side,
            start_price=Decimal("2.5"),
        )
    return ei.value


class TestDuplicatePreventionMessages:
    def test_stopping_strategy_blocks_with_force_stop_hint(
        self,
        db_session,
        make_user,
        make_exchange_account,
        make_symbol,
        make_template,
        make_strategy,
        monkeypatch,
    ) -> None:
        # 2026-05-10: env 의 whitelist + dup toggle 영향 차단 (위 테스트와 동일 사유)
        monkeypatch.setattr("app.core.config.settings.allowed_symbols_csv", None, raising=False)
        monkeypatch.setattr(
            "app.core.config.settings.allow_duplicate_symbol_strategies", False, raising=False,
        )
        u = make_user()
        ea = make_exchange_account(user=u)
        sym = make_symbol("LABUSDT")
        tpl = make_template(side="SHORT")
        existing = make_strategy(
            symbol_str="LABUSDT", side="SHORT", status="STOPPING",
            current_position_qty=Decimal("-100"),
            user=u, exchange_account=ea, symbol_obj=sym, template=tpl,
        )

        err = _try_create_duplicate(
            StrategyService(db_session),
            user_id=u.id, exchange_account_id=ea.id, template_id=tpl.id,
            symbol="LABUSDT", side="SHORT",
        )
        msg = str(err)
        assert f"#{existing.id}" in msg
        # STOPPING 전용 가이드: 청산 중 상태 + 30초 자동 정리 안내
        assert "청산 중" in msg
        assert "30초" in msg

    @pytest.mark.parametrize(
        "active_status",
        ["STAGE1_OPEN", "STAGE2_OPEN_PENDING", "TP1_DONE_PARTIAL"],
    )
    def test_non_stopping_active_blocks_with_generic_hint(
        self,
        active_status: str,
        db_session,
        make_user,
        make_exchange_account,
        make_symbol,
        make_template,
        make_strategy,
        monkeypatch,
    ) -> None:
        # 2026-05-10 (사용자 자유 거래 모드 도입 사후): env 의 whitelist + dup toggle 영향
        # 차단해 본 테스트의 가설 (LABUSDT 가 같은 symbol+side 중복으로 차단) 만 검증.
        monkeypatch.setattr("app.core.config.settings.allowed_symbols_csv", None, raising=False)
        monkeypatch.setattr(
            "app.core.config.settings.allow_duplicate_symbol_strategies", False, raising=False,
        )
        u = make_user()
        ea = make_exchange_account(user=u)
        sym = make_symbol("LABUSDT")
        tpl = make_template(side="SHORT")
        existing = make_strategy(
            symbol_str="LABUSDT", side="SHORT", status=active_status,
            current_position_qty=Decimal("-50"),
            user=u, exchange_account=ea, symbol_obj=sym, template=tpl,
        )

        err = _try_create_duplicate(
            StrategyService(db_session),
            user_id=u.id, exchange_account_id=ea.id, template_id=tpl.id,
            symbol="LABUSDT", side="SHORT",
        )
        msg = str(err)
        assert f"#{existing.id}" in msg
        # generic hint — 정지/긴급 종료 안내, STOPPING 전용 가이드 없음
        assert ("정지" in msg) or ("긴급 종료" in msg)
        assert "30초" not in msg  # STOPPING 전용 안내 미포함
        assert "청산 중" not in msg

    def test_terminal_strategy_does_not_block(
        self,
        db_session,
        make_user,
        make_exchange_account,
        make_symbol,
        make_template,
        make_strategy,
    ) -> None:
        """COMPLETED / STOPPED / REENTRY_READY 는 종료 분류 — 새 전략 진입 시 차단 안 함.

        (단, 후속 잔액 체크에서 다른 ValueError 가 날 수 있음 — 이 테스트는 중복 가드만 검증.)
        """
        u = make_user()
        ea = make_exchange_account(user=u)
        sym = make_symbol("LABUSDT")
        tpl = make_template(side="SHORT")
        # COMPLETED 전략 미리 등록
        make_strategy(
            symbol_str="LABUSDT", side="SHORT", status="COMPLETED",
            current_position_qty=Decimal("0"),
            user=u, exchange_account=ea, symbol_obj=sym, template=tpl,
        )

        # 신규 시도 — 중복 가드 통과 후 다른 단계 (잔액/Binance 호출) 에서 실패할 것.
        # 메시지가 "중복" 관련이 아니어야 함을 검증.
        with pytest.raises(ValueError) as ei:
            StrategyService(db_session).create_strategy_instance(
                user_id=u.id, exchange_account_id=ea.id,
                strategy_template_id=tpl.id, symbol="LABUSDT", side="SHORT",
                start_price=Decimal("2.5"),
            )
        msg = str(ei.value)
        # 중복 가드 메시지가 아니어야 함 (다른 단계 — 잔액/Binance — 에서 실패)
        assert "이미 진행 중" not in msg
        assert "통합 포지션만 허용" not in msg
