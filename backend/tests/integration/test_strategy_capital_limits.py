"""StrategyService.create_strategy_instance 의 자본/동시성/심볼 가드 검증.

배경 (MAINNET-CHECKLIST 3-3, 2026-05-07):
- 동시 활성 strategy 수 한도가 하드코딩 10 → 환경변수화 (운영자 조정 가능)
- 단일 strategy 자본이 가용 잔액의 N% 초과 시 거부 — 자본 집중 차단
- 심볼 화이트리스트 — mainnet 초기 high-liquidity 만 허용

이 테스트는 가드 로직만 검증 (실제 Binance 호출 X). 가용 잔액 의존 가드는
BinanceClient.get_account 를 직접 monkeypatch.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.strategy_service import StrategyService


def _patch_binance_account(monkeypatch, available: str = "1000", positions: list | None = None) -> None:
    """BinanceClient 를 fake 로 교체 — get_account 만 mock."""
    class _FakeClient:
        def __init__(self, **kwargs):
            pass
        def get_account(self):
            return {
                "availableBalance": available,
                "totalMarginBalance": available,
                "totalMaintMargin": "0",
                "positions": positions or [],
            }
    # strategy_service 가 lazy import 하므로 정확한 import path 패치
    monkeypatch.setattr("app.integrations.binance.client.BinanceClient", _FakeClient)
    # decrypt 도 통과시킴 (테스트용 평문 enc)
    monkeypatch.setattr("app.core.crypto.decrypt_text", lambda s: s)


class TestSymbolWhitelist:
    def test_disallowed_symbol_rejected(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, monkeypatch
    ) -> None:
        """allowed_symbols_csv='BTCUSDT' 인데 SOLUSDT 진입 시도 → ValueError."""
        monkeypatch.setattr(
            "app.core.config.settings.allowed_symbols_csv", "BTCUSDT,ETHUSDT", raising=False
        )
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("SOLUSDT")
        tpl = make_template()

        with pytest.raises(ValueError, match="현재 허용되지 않습니다"):
            StrategyService(db_session).create_strategy_instance(
                user_id=u.id,
                exchange_account_id=ea.id,
                strategy_template_id=tpl.id,
                symbol="SOLUSDT",
                side="SHORT",
                start_price=Decimal("5000"),
            )

    def test_allowed_symbol_passes_whitelist(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, monkeypatch
    ) -> None:
        """BTCUSDT 는 화이트리스트에 있으므로 통과 (이후 잔액 mock 으로 끝까지 가능)."""
        monkeypatch.setattr(
            "app.core.config.settings.allowed_symbols_csv", "BTCUSDT,ETHUSDT", raising=False
        )
        _patch_binance_account(monkeypatch, available="100000")
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template()

        # 화이트리스트 통과 — 끝까지 진행 (생성 성공)
        instance = StrategyService(db_session).create_strategy_instance(
            user_id=u.id,
            exchange_account_id=ea.id,
            strategy_template_id=tpl.id,
            symbol="BTCUSDT",
            side="SHORT",
            start_price=Decimal("5000"),
        )
        assert instance.id > 0
        assert instance.symbol == "BTCUSDT"

    def test_empty_whitelist_allows_all(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, monkeypatch
    ) -> None:
        """allowed_symbols_csv 미설정 (None) → 모든 심볼 허용 (testnet/dev default)."""
        monkeypatch.setattr(
            "app.core.config.settings.allowed_symbols_csv", None, raising=False
        )
        _patch_binance_account(monkeypatch, available="100000")
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("DOGEUSDT")
        tpl = make_template()

        instance = StrategyService(db_session).create_strategy_instance(
            user_id=u.id,
            exchange_account_id=ea.id,
            strategy_template_id=tpl.id,
            symbol="DOGEUSDT",
            side="SHORT",
            start_price=Decimal("0.1"),
        )
        assert instance.symbol == "DOGEUSDT"

    def test_case_insensitive_whitelist(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, monkeypatch
    ) -> None:
        """allowed_symbols_csv 의 소문자도 허용 (set 비교 시 .upper() 정규화)."""
        monkeypatch.setattr(
            "app.core.config.settings.allowed_symbols_csv", "btcusdt", raising=False
        )
        _patch_binance_account(monkeypatch, available="100000")
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template()

        # 화이트리스트엔 소문자, 입력은 대문자 → 통과해야
        instance = StrategyService(db_session).create_strategy_instance(
            user_id=u.id,
            exchange_account_id=ea.id,
            strategy_template_id=tpl.id,
            symbol="BTCUSDT",
            side="SHORT",
            start_price=Decimal("5000"),
        )
        assert instance.id > 0


class TestMaxConcurrentStrategies:
    def test_default_limit_10(
        self, db_session, make_strategy, make_symbol, make_template, monkeypatch
    ) -> None:
        """default max_concurrent=10 — 10건 active 면 11번째 거부."""
        monkeypatch.setattr(
            "app.core.config.settings.max_concurrent_strategies_per_account", 10, raising=False
        )
        first = make_strategy(symbol_str="BTCUSDT", status="STAGE1_OPEN")
        for i in range(9):
            make_strategy(
                symbol_str=f"COIN{i}USDT",
                status="STAGE1_OPEN",
                exchange_account=first.exchange_account,
                user=first.user,
            )
        # 11번째 시도
        make_symbol("EXTRAUSDT")
        tpl = make_template()
        with pytest.raises(ValueError, match="동시 운영 한도"):
            StrategyService(db_session).create_strategy_instance(
                user_id=first.user_id,
                exchange_account_id=first.exchange_account_id,
                strategy_template_id=tpl.id,
                symbol="EXTRAUSDT",
                side="SHORT",
                start_price=Decimal("5000"),
            )

    def test_lower_limit_via_setting(
        self, db_session, make_strategy, make_symbol, make_template, monkeypatch
    ) -> None:
        """max_concurrent=2 로 설정 — 2건 active 면 3번째 거부 (mainnet 초기 권장)."""
        monkeypatch.setattr(
            "app.core.config.settings.max_concurrent_strategies_per_account", 2, raising=False
        )
        first = make_strategy(symbol_str="BTCUSDT", status="STAGE1_OPEN")
        make_strategy(
            symbol_str="ETHUSDT", status="STAGE1_OPEN",
            exchange_account=first.exchange_account, user=first.user,
        )
        # 2건 active. 3번째 거부.
        make_symbol("SOLUSDT")
        tpl = make_template()
        with pytest.raises(ValueError, match=r"동시 운영 한도 \(2개\)"):
            StrategyService(db_session).create_strategy_instance(
                user_id=first.user_id,
                exchange_account_id=first.exchange_account_id,
                strategy_template_id=tpl.id,
                symbol="SOLUSDT",
                side="SHORT",
                start_price=Decimal("100"),
            )

    def test_zero_setting_clamped_to_1(
        self, db_session, make_strategy, make_symbol, make_template, monkeypatch
    ) -> None:
        """0 설정은 1로 강제 (안전: 모든 거래 막힘 방어)."""
        monkeypatch.setattr(
            "app.core.config.settings.max_concurrent_strategies_per_account", 0, raising=False
        )
        first = make_strategy(symbol_str="BTCUSDT", status="STAGE1_OPEN")
        make_symbol("ETHUSDT")
        tpl = make_template()
        # 1건 이미 있음. 다음 거부 (clamp 1 = 한도).
        with pytest.raises(ValueError, match=r"동시 운영 한도 \(1개\)"):
            StrategyService(db_session).create_strategy_instance(
                user_id=first.user_id,
                exchange_account_id=first.exchange_account_id,
                strategy_template_id=tpl.id,
                symbol="ETHUSDT",
                side="SHORT",
                start_price=Decimal("100"),
            )


class TestMaxStrategyCapitalPct:
    def test_capital_above_pct_rejected(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, monkeypatch
    ) -> None:
        """available=1000, max_pct=5% → 한도 50. tpl total_capital=100 (10%) → 거부."""
        monkeypatch.setattr(
            "app.core.config.settings.max_strategy_capital_pct_of_balance", 5.0, raising=False
        )
        _patch_binance_account(monkeypatch, available="1000")
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        # 기본 tpl total_capital=100 (10% of 1000)
        tpl = make_template()

        with pytest.raises(ValueError, match="자본이 너무 큽니다"):
            StrategyService(db_session).create_strategy_instance(
                user_id=u.id,
                exchange_account_id=ea.id,
                strategy_template_id=tpl.id,
                symbol="BTCUSDT",
                side="SHORT",
                start_price=Decimal("5000"),
            )

    def test_capital_within_pct_passes(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, monkeypatch
    ) -> None:
        """available=10000, max_pct=5% → 한도 500. tpl=100 (1%) → 통과."""
        monkeypatch.setattr(
            "app.core.config.settings.max_strategy_capital_pct_of_balance", 5.0, raising=False
        )
        _patch_binance_account(monkeypatch, available="10000")
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template()

        instance = StrategyService(db_session).create_strategy_instance(
            user_id=u.id,
            exchange_account_id=ea.id,
            strategy_template_id=tpl.id,
            symbol="BTCUSDT",
            side="SHORT",
            start_price=Decimal("5000"),
        )
        assert instance.id > 0

    def test_none_setting_disables_check(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, monkeypatch
    ) -> None:
        """max_pct=None → 가드 비활성 (default). tpl=100 vs available=10 도 (잔액 부족 가드는 별도 발동)."""
        monkeypatch.setattr(
            "app.core.config.settings.max_strategy_capital_pct_of_balance", None, raising=False
        )
        # available 충분, capital_pct 가드 X
        _patch_binance_account(monkeypatch, available="100000")
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template()

        # 가드 비활성 → 정상 진행
        instance = StrategyService(db_session).create_strategy_instance(
            user_id=u.id,
            exchange_account_id=ea.id,
            strategy_template_id=tpl.id,
            symbol="BTCUSDT",
            side="SHORT",
            start_price=Decimal("5000"),
        )
        assert instance.id > 0

    def test_zero_setting_disables_check(
        self, db_session, make_user, make_exchange_account, make_symbol, make_template, monkeypatch
    ) -> None:
        """max_pct=0 도 비활성 (deploy-safe — 0 으로 모든 거래 막히는 사고 방어)."""
        monkeypatch.setattr(
            "app.core.config.settings.max_strategy_capital_pct_of_balance", 0.0, raising=False
        )
        _patch_binance_account(monkeypatch, available="1000")
        u = make_user()
        ea = make_exchange_account(user=u)
        make_symbol("BTCUSDT")
        tpl = make_template()

        instance = StrategyService(db_session).create_strategy_instance(
            user_id=u.id,
            exchange_account_id=ea.id,
            strategy_template_id=tpl.id,
            symbol="BTCUSDT",
            side="SHORT",
            start_price=Decimal("5000"),
        )
        assert instance.id > 0


class TestAllowedSymbolsParsing:
    def test_allowed_symbols_set_property(self) -> None:
        """allowed_symbols_set 의 CSV 파싱: 공백 제거, 대문자 정규화, 빈 토큰 무시."""
        from app.core.config import Settings
        s = Settings(allowed_symbols_csv=" btcusdt , ETHUSDT,, doge ")
        assert s.allowed_symbols_set == {"BTCUSDT", "ETHUSDT", "DOGE"}

    def test_allowed_symbols_set_none_when_empty(self) -> None:
        from app.core.config import Settings
        s1 = Settings(allowed_symbols_csv=None)
        s2 = Settings(allowed_symbols_csv="")
        s3 = Settings(allowed_symbols_csv="   ,  ,")  # 빈 토큰만
        assert s1.allowed_symbols_set is None
        assert s2.allowed_symbols_set is None
        assert s3.allowed_symbols_set is None
