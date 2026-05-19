"""StrategyService.create_strategy_instance — 전체 계획자본 예약 가드 회귀.

배경 (사용자 보고 2026-05-19):
- 13개 동시 전략 → 다음 단계 진입이 Binance -2019 "Margin is insufficient"
- 원인: 생성 시 required_margin 을 availableBalance(이미 진입 단계만 반영)
  와만 비교 → 기존 전략들의 미진입 단계 미반영 → 다수 통과 후 누적 -2019
- 사용자 요청: "단계별 설정금액까지 포지션 진입한 걸로 계산해서 잔액 운영"

Fix: 모든 활성 전략을 「전체 단계 다 진입」 가정으로 계획 마진 합산(예약)
+ 신규 전략 계획 마진 ≤ 총 지갑잔액 사전 검증. 초과 시 ValueError.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.strategy_service import StrategyService


def _patch_binance(monkeypatch, *, available: str, total_wallet: str) -> None:
    """get_account mock — availableBalance 와 totalWalletBalance 분리 제어."""
    class _FakeClient:
        def __init__(self, **kwargs):
            pass

        def get_account(self):
            return {
                "availableBalance": available,
                "totalWalletBalance": total_wallet,
                "totalMarginBalance": total_wallet,
                "totalMaintMargin": "0",
                "positions": [],
            }

    monkeypatch.setattr("app.integrations.binance.client.BinanceClient", _FakeClient)
    monkeypatch.setattr("app.core.crypto.decrypt_text", lambda s: s)
    # whitelist / concurrent 가드가 먼저 걸리지 않도록 완화
    monkeypatch.setattr("app.core.config.settings.allowed_symbols_csv", None, raising=False)
    monkeypatch.setattr(
        "app.core.config.settings.max_concurrent_strategies_per_account", 50, raising=False
    )
    monkeypatch.setattr(
        "app.core.config.settings.allow_duplicate_symbol_strategies", True, raising=False
    )


class TestFullCapitalReservation:
    def test_over_reservation_blocked(
        self, db_session, make_user, make_exchange_account, make_symbol,
        make_template, make_strategy, monkeypatch,
    ) -> None:
        """기존 2전략 예약(각 100/10=10) + 신규 10 = 30 > 지갑 25 → 차단."""
        u = make_user()
        ea = make_exchange_account(user=u)
        tpl = make_template()  # total_capital=100, leverage=10
        # 기존 활성 전략 2개 (서로 다른 심볼 — dup 가드 회피)
        make_strategy(symbol_str="AAAUSDT", side="SHORT", status="STAGE1_OPEN",
                      user=u, exchange_account=ea, template=tpl, leverage=10)
        make_strategy(symbol_str="BBBUSDT", side="SHORT", status="STAGE2_OPEN",
                      user=u, exchange_account=ea, template=tpl, leverage=10)
        make_symbol("CCCUSDT")
        # availableBalance 는 넉넉(=이전 가드 통과), 지갑은 부족(=예약 가드 발동)
        _patch_binance(monkeypatch, available="10000", total_wallet="25")

        with pytest.raises(ValueError, match="전체 계획자본 초과"):
            StrategyService(db_session).create_strategy_instance(
                user_id=u.id, exchange_account_id=ea.id,
                strategy_template_id=tpl.id, symbol="CCCUSDT", side="SHORT",
                start_price=Decimal("100"),
            )

    def test_within_reservation_passes_guard(
        self, db_session, make_user, make_exchange_account, make_symbol,
        make_template, make_strategy, monkeypatch,
    ) -> None:
        """지갑 충분(1000)이면 예약 가드 통과 — 이 에러 안 남 (이후 단계는 별개)."""
        u = make_user()
        ea = make_exchange_account(user=u)
        tpl = make_template()
        make_strategy(symbol_str="AAAUSDT", side="SHORT", status="STAGE1_OPEN",
                      user=u, exchange_account=ea, template=tpl, leverage=10)
        make_symbol("CCCUSDT")
        _patch_binance(monkeypatch, available="10000", total_wallet="1000")

        # 예약 가드(전체 계획자본 초과) 는 통과해야 함. 그 외 사유로 실패할 순
        # 있으나 "전체 계획자본 초과" 메시지는 안 나와야 함.
        try:
            StrategyService(db_session).create_strategy_instance(
                user_id=u.id, exchange_account_id=ea.id,
                strategy_template_id=tpl.id, symbol="CCCUSDT", side="SHORT",
                start_price=Decimal("100"),
            )
        except ValueError as e:
            assert "전체 계획자본 초과" not in str(e), (
                f"지갑 충분한데 예약 가드가 잘못 발동: {e}"
            )

    def test_no_existing_strategies_only_new_counted(
        self, db_session, make_user, make_exchange_account, make_symbol,
        make_template, monkeypatch,
    ) -> None:
        """기존 활성 0건이면 신규 전략 계획 마진만 검증 (오탐 없음)."""
        u = make_user()
        ea = make_exchange_account(user=u)
        tpl = make_template()  # 100/10 = 10 USDT 필요
        make_symbol("CCCUSDT")
        # 지갑 5 < 신규 필요 10 → 예약 가드가 신규만으로도 차단
        _patch_binance(monkeypatch, available="10000", total_wallet="5")

        with pytest.raises(ValueError, match="전체 계획자본 초과"):
            StrategyService(db_session).create_strategy_instance(
                user_id=u.id, exchange_account_id=ea.id,
                strategy_template_id=tpl.id, symbol="CCCUSDT", side="SHORT",
                start_price=Decimal("100"),
            )
