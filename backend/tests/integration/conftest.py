"""Integration test scaffold — sqlite in-memory + Binance mock.

핵심 설계 결정:
1. **sqlite in-memory**: postgres testcontainer 대신 가벼운 sqlite. JSONB 는
   compiles directive 로 sqlite 에서 JSON 으로 컴파일되도록 변환.
2. **함수 스코프 isolation**: 각 테스트마다 새 engine + 스키마 생성/파괴.
3. **Binance mock**: `BinanceClient` 클래스를 fake 로 monkeypatch — get_position_risk
   호출을 테스트가 제어. reconcile_worker.py / zombie_guardian.py 양쪽에서
   참조하므로 두 모듈 모두 패치.
4. **Factory fixtures**: User/ExchangeAccount/Symbol/Template/Strategy 를 한 번에
   준비하는 헬퍼 — 보일러플레이트 최소화.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

# 모든 모델을 import 해서 Base.metadata 에 등록 — 한 곳에서 일괄 import.
import app.models  # noqa: F401 — registers all tables on Base
from app.db.base import Base
from app.models.account_kill_switch import AccountKillSwitch
from app.models.exchange_account import ExchangeAccount
from app.models.notification import Notification
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_stage_plan import StrategyStagePlan
from app.models.strategy_template import StrategyTemplate
from app.models.symbol import Symbol
from app.models.user import User


# ---------------------------------------------------------------------------
# JSONB → JSON for sqlite
# ---------------------------------------------------------------------------
# 모델은 postgres JSONB 사용. sqlite 에서는 JSON 으로 컴파일되도록 redirect.
# (sqlite JSON1 extension 이 기본 활성화 — Python 3.9+ 보장)
@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(type_, compiler, **kw):  # type: ignore[no-untyped-def]
    return "JSON"


# ---------------------------------------------------------------------------
# Engine + session fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def engine():
    """함수 스코프 sqlite in-memory engine. 테스트마다 새 schema."""
    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
    )

    # 외래키 활성화 (sqlite 기본 OFF)
    @event.listens_for(eng, "connect")
    def _enable_fk(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)
    eng.dispose()


@pytest.fixture
def db_session(engine):
    """함수 스코프 ORM session. test 종료 시 close."""
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    s = Session()
    try:
        yield s
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Factory fixtures — 도메인 객체 빠르게 만들기
# ---------------------------------------------------------------------------
@pytest.fixture
def make_user(db_session):
    counter = {"n": 0}

    def _factory(**overrides) -> User:
        counter["n"] += 1
        defaults = dict(
            email=f"test{counter['n']}@example.com",
            password_hash="x",
            full_name=f"Test User {counter['n']}",
        )
        defaults.update(overrides)
        u = User(**defaults)
        db_session.add(u)
        db_session.commit()
        db_session.refresh(u)
        return u
    return _factory


@pytest.fixture
def make_exchange_account(db_session, make_user):
    def _factory(*, user: User | None = None, **overrides) -> ExchangeAccount:
        u = user or make_user()
        defaults = dict(
            user_id=u.id,
            exchange_name="binance",
            market_type="usds_m_futures",
            api_key_enc="enc:apikey",
            api_secret_enc="enc:secret",
            is_testnet=True,
            is_active=True,
        )
        defaults.update(overrides)
        a = ExchangeAccount(**defaults)
        db_session.add(a)
        db_session.commit()
        db_session.refresh(a)
        return a
    return _factory


@pytest.fixture
def make_symbol(db_session):
    """Symbol 은 unique 라 같은 이름으로 두 번 호출되면 기존 row 재사용."""

    def _factory(symbol: str = "BTCUSDT", **overrides) -> Symbol:
        existing = db_session.execute(
            select(Symbol).where(Symbol.symbol == symbol)
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        defaults = dict(
            symbol=symbol,
            base_asset=symbol.replace("USDT", "") or "BTC",
            quote_asset="USDT",
            status="TRADING",
            price_precision=2,
            quantity_precision=3,
            tick_size=Decimal("0.01"),
            step_size=Decimal("0.001"),
            min_qty=Decimal("0.001"),
            min_notional=Decimal("5"),
        )
        defaults.update(overrides)
        s = Symbol(**defaults)
        db_session.add(s)
        db_session.commit()
        db_session.refresh(s)
        return s
    return _factory


@pytest.fixture
def make_template(db_session):
    counter = {"n": 0}

    def _factory(name: str | None = None, **overrides) -> StrategyTemplate:
        counter["n"] += 1
        if name is None:
            name = f"tpl_{counter['n']}"
        defaults = dict(
            name=name,
            strategy_type="OPTION_C",
            side="SHORT",
            leverage=10,
            total_capital=Decimal("100"),
            stages_config={"capitals": [50, 50], "trigger_percents": [None, None]},
            tp1_percent=Decimal("5"),
            tp2_percent=Decimal("10"),
            tp3_percent=Decimal("15"),
            tp1_qty_ratio=Decimal("25"),
            tp2_qty_ratio=Decimal("50"),
            tp3_qty_ratio=Decimal("100"),
            stop_loss_percent_of_capital=Decimal("50"),
            reentry_policy="manual_ready",
        )
        defaults.update(overrides)
        t = StrategyTemplate(**defaults)
        db_session.add(t)
        db_session.commit()
        db_session.refresh(t)
        return t
    return _factory


@pytest.fixture
def make_strategy(db_session, make_user, make_exchange_account, make_symbol, make_template):
    """미리 셋업된 환경에서 StrategyInstance 1건 생성."""

    def _factory(
        *,
        symbol_str: str = "BTCUSDT",
        side: str = "SHORT",
        status: str = "STAGE1_OPEN",
        current_position_qty: Decimal | int | float | str = Decimal("-0.5"),
        avg_entry_price: Decimal | int | float | str | None = Decimal("50000"),
        leverage: int = 10,
        user: User | None = None,
        exchange_account: ExchangeAccount | None = None,
        symbol_obj: Symbol | None = None,
        template: StrategyTemplate | None = None,
        **strategy_overrides,
    ) -> StrategyInstance:
        u = user or make_user()
        ea = exchange_account or make_exchange_account(user=u)
        sym = symbol_obj or make_symbol(symbol_str)
        tpl = template or make_template()

        s = StrategyInstance(
            user_id=u.id,
            exchange_account_id=ea.id,
            strategy_template_id=tpl.id,
            symbol_id=sym.id,
            symbol=sym.symbol,
            side=side,
            start_price=Decimal("50000"),
            leverage=leverage,
            total_capital=Decimal("100"),
            current_position_qty=Decimal(str(current_position_qty)),
            avg_entry_price=Decimal(str(avg_entry_price)) if avg_entry_price is not None else None,
            status=status,
        )
        for k, v in strategy_overrides.items():
            setattr(s, k, v)
        db_session.add(s)
        db_session.commit()
        db_session.refresh(s)
        return s
    return _factory


# ---------------------------------------------------------------------------
# Binance client mock
# ---------------------------------------------------------------------------
class FakeBinanceClient:
    """reconcile_worker / zombie_guardian 가 호출하는 BinanceClient 의 fake 대체.

    각 테스트가 `position_risk_responses` dict 를 채워 응답을 설정.
        key = "ALL"             → get_position_risk()  (no-arg) 의 반환값
        key = "<SYMBOL>"        → get_position_risk(symbol="<SYMBOL>") 반환값

    값은 list[dict] (Binance API 와 동일 포맷).
    """

    # 인스턴스가 아닌 클래스 레벨에 두어 monkeypatch 후에도 상태 공유.
    position_risk_responses: dict[str, list[dict]] = {}

    def __init__(self, *args, **kwargs) -> None:  # noqa: D401
        # 생성자 인자는 모두 무시 — fake 라서.
        self.kwargs = kwargs

    def get_position_risk(self, symbol: str | None = None) -> list[dict]:
        if symbol is None:
            return list(self.__class__.position_risk_responses.get("ALL", []))
        return list(self.__class__.position_risk_responses.get(symbol, []))

    @classmethod
    def reset(cls) -> None:
        cls.position_risk_responses = {}

    @classmethod
    def set_position(
        cls,
        symbol: str,
        *,
        position_amt: str = "0",
        entry_price: str = "0",
        mark_price: str = "0",
        unrealized_pnl: str = "0",
        liquidation_price: str = "0",
        position_side: str = "SHORT",
    ) -> None:
        """심볼별 포지션 응답 설정."""
        item = {
            "symbol": symbol,
            "positionSide": position_side,
            "positionAmt": position_amt,
            "entryPrice": entry_price,
            "markPrice": mark_price,
            "unRealizedProfit": unrealized_pnl,
            "liquidationPrice": liquidation_price,
            "marginType": "cross",
            "isolatedMargin": "0",
            "leverage": "10",
            "breakEvenPrice": "0",
        }
        cls.position_risk_responses[symbol] = [item]
        # ALL 응답에도 추가 (orphan detection 이 사용)
        all_list = cls.position_risk_responses.setdefault("ALL", [])
        # 같은 symbol+side 가 이미 있으면 교체
        all_list[:] = [
            x for x in all_list
            if not (x.get("symbol") == symbol and x.get("positionSide") == position_side)
        ]
        all_list.append(item)


@pytest.fixture
def fake_binance(monkeypatch):
    """BinanceClient 를 FakeBinanceClient 로 교체. 매 테스트마다 reset."""
    FakeBinanceClient.reset()
    # reconcile_worker 모듈에서 import 한 BinanceClient 패치
    monkeypatch.setattr(
        "app.workers.reconcile_worker.BinanceClient",
        FakeBinanceClient,
    )
    # zombie_guardian.detect_orphan_exchange_positions 가 lazy import 하므로
    # app.integrations.binance.client.BinanceClient 도 같이 패치.
    monkeypatch.setattr(
        "app.integrations.binance.client.BinanceClient",
        FakeBinanceClient,
    )
    yield FakeBinanceClient
    FakeBinanceClient.reset()


@pytest.fixture
def identity_decrypt() -> Callable[[str], str]:
    """encrypted text 를 그대로 반환하는 decrypt 함수 (테스트용)."""
    return lambda enc: enc


# ---------------------------------------------------------------------------
# SessionLocal patch — reconcile_worker 가 자체 세션을 만들지 않게
# ---------------------------------------------------------------------------
@pytest.fixture
def patched_sessionlocal(monkeypatch, engine):
    """reconcile_worker._do_reconcile 가 호출하는 SessionLocal() 을
    test engine 에 묶인 sessionmaker 로 교체.

    이 fixture 가 호출되면 reconcile worker 가 만든 session 도 같은 sqlite
    in-memory DB 를 보게 됨 → 테스트가 set up 한 데이터를 reconcile 이 봄.
    """
    test_session_factory = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, future=True
    )
    monkeypatch.setattr("app.workers.reconcile_worker.SessionLocal", test_session_factory)
    return test_session_factory


# ---------------------------------------------------------------------------
# Telegram 차단 — NotificationService.send_system_alert 가 외부 호출 안 하게
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _no_telegram(monkeypatch):
    """모든 통합 테스트에서 Telegram 외부 호출 차단.

    settings.telegram_bot_token 이 None 이면 NotificationService 가 자동 skip
    하지만, 환경 변수가 설정돼 있을 수도 있으니 명시적으로 차단.
    """
    monkeypatch.setattr("app.core.config.settings.telegram_bot_token", None, raising=False)
    monkeypatch.setattr("app.core.config.settings.telegram_chat_id", None, raising=False)
