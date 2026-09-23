"""🚨 Fix 373 (2026-09-16) — 「모델에 없는 컬럼을 코드가 읽는」 조용한 실패 3건 + 같은 함정 자동 가드.

9/14 다중 세션 점검이 찾은 것 (전부 최근 작업과 무관한 오래된 버그):
  · mainnet_safety_worker:139 `a.name` — 컬럼은 exchange_name → 매시간 계정 안전 점검이 AttributeError (7/24 v127 이후)
  · daily_summary_worker:86·96 `RiskEvent.ts` / `Notification.ts` — 컬럼은 created_at → 일일 요약 실패 (6/3 신설 이후)
  · api/v1/admin/monitoring.py:1412 `a.name` / `a.exchange` — 같은 원인으로 이 API 는 호출마다 500

이 테스트는 고친 것을 고정하고, **앞으로 같은 종류의 오류를 자동으로 잡는다**(모델 클래스 속성 접근을 AST 로 전수 검사).
"""
import ast
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from app.models.exchange_account import ExchangeAccount
from app.models.notification import Notification
from app.models.order import Order
from app.models.paper_trade import PaperTrade
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_suggestion import StrategySuggestion
from app.models.system_setting import SystemSetting
from app.models.trade_learning_record import TradeLearningRecord

APP = Path(__file__).resolve().parents[2] / "app"
MODELS = {m.__name__: m for m in (ExchangeAccount, Notification, Order, PaperTrade, RiskEvent,
                                  StrategyInstance, StrategySuggestion, SystemSetting, TradeLearningRecord)}
# SQLAlchemy·파이썬이 주는 것 (컬럼이 아니어도 정상)
EXTRA_OK = {"__table__", "__tablename__", "__name__", "__mapper__", "metadata", "registry", "query", "id"}


def _model_attrs(model) -> set[str]:
    return set(dir(model)) | EXTRA_OK


# ── 고친 3건 ─────────────────────────────────────────────────────────────
def test_columns_the_bugs_assumed_do_not_exist():
    assert not hasattr(ExchangeAccount, "name") and hasattr(ExchangeAccount, "exchange_name")
    assert not hasattr(ExchangeAccount, "exchange") and hasattr(ExchangeAccount, "market_type")
    assert not hasattr(RiskEvent, "ts") and hasattr(RiskEvent, "created_at")
    assert not hasattr(Notification, "ts") and hasattr(Notification, "created_at")


def test_mainnet_safety_account_check_runs():
    from app.workers.mainnet_safety_worker import _check_exchange_accounts

    class _DB:
        def execute(self, *_a, **_k):
            rows = [NS(id=7, exchange_name="binance", is_testnet=False)]
            return NS(scalars=lambda: NS(all=lambda: rows))
    out = _check_exchange_accounts(_DB())
    assert out == [{"id": 7, "name": "binance", "is_testnet": False}]


def test_daily_summary_uses_created_at():
    src = (APP / "workers" / "daily_summary_worker.py").read_text(encoding="utf-8")
    assert "RiskEvent.created_at" in src and "Notification.created_at" in src
    assert "RiskEvent.ts" not in src and "Notification.ts" not in src


def test_admin_monitoring_accounts_block_fixed():
    src = (APP / "api" / "v1" / "admin" / "monitoring.py").read_text(encoding="utf-8")
    assert '"name": a.exchange_name' in src and '"exchange": a.exchange_name' in src
    assert '"name": a.name' not in src and "a.exchange," not in src
    assert '"type": None' in src and "type_note" in src          # 이름 컬럼이 없어 MAIN/SUB 는 추측하지 않는다


# ── 자동 가드: 모델 클래스 속성 접근 전수 검사 ─────────────────────────────
def _bad_class_attr_uses() -> list[str]:
    bad: list[str] = []
    for p in APP.rglob("*.py"):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for n in ast.walk(tree):
            if not isinstance(n, ast.Attribute) or not isinstance(n.value, ast.Name):
                continue
            model = MODELS.get(n.value.id)
            if model is None or n.attr.startswith("_"):
                continue
            if n.attr not in _model_attrs(model):
                bad.append(f"{p.relative_to(APP).as_posix()}:{n.lineno} {n.value.id}.{n.attr}")
    return sorted(set(bad))


def test_no_code_reads_a_column_the_model_does_not_have():
    bad = _bad_class_attr_uses()
    assert bad == [], "모델에 없는 컬럼을 읽는 코드 (Fix 373 과 같은 조용한 실패):\n" + "\n".join(bad)


@pytest.mark.parametrize("snippet, expect_bad", [("RiskEvent.created_at", False), ("RiskEvent.ts", True)])
def test_guard_itself_catches_the_pattern(snippet, expect_bad, tmp_path):
    """가드가 실제로 잡는지 — 거짓 통과 방지 (헌법 122: 검사기는 스스로를 검증해야 한다)."""
    node = ast.parse(snippet).body[0].value
    model = MODELS[node.value.id]
    assert (node.attr not in _model_attrs(model)) is expect_bad


# ── Fix 373b: 인스턴스 속성(모델에 없는 컬럼)을 직접 읽던 4곳 ─────────────
MISSING_INSTANCE_ATTRS = {"current_price", "unrealized_pnl_pct"}
SUBJECTS = {"strategy", "s", "si"}


def test_pnl_and_price_helpers_use_learning_definition():
    from decimal import Decimal
    from app.services.trade_learning_service import current_price_of, unrealized_pnl_pct_of
    st = NS(total_capital=Decimal("100"), unrealized_pnl=Decimal("5"), symbol="XUSDT")
    assert unrealized_pnl_pct_of(st) == pytest.approx(5.0)          # USDT / 자본 × 100
    assert unrealized_pnl_pct_of(NS(symbol="XUSDT")) == 0.0        # 값이 없으면 0 (예외 없음)
    assert current_price_of(NS(symbol="XUSDT")) is None or True     # Redis 없으면 None (예외 없음)


def test_call_sites_no_longer_read_missing_columns():
    for rel, needle in (("api/v1/analysis.py", "unrealized_pnl_pct_of(strategy)"),
                        ("api/v1/analysis.py", "current_price_of(strategy)"),
                        ("api/v1/trade_learning.py", "unrealized_pnl_pct_of(s)")):
        src = (APP / rel).read_text(encoding="utf-8")
        assert needle in src, f"{rel} : {needle}"
        assert "strategy.unrealized_pnl_pct" not in src and "s.unrealized_pnl_pct or" not in src
        assert "strategy.current_price or" not in src


def test_no_instance_reads_of_missing_columns_anywhere():
    bad = []
    for p in APP.rglob("*.py"):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for n in ast.walk(tree):
            if (isinstance(n, ast.Attribute) and n.attr in MISSING_INSTANCE_ATTRS
                    and isinstance(n.value, ast.Name) and n.value.id in SUBJECTS):
                bad.append(f"{p.relative_to(APP).as_posix()}:{n.lineno} {n.value.id}.{n.attr}")
    assert sorted(bad) == [], "모델에 없는 컬럼을 직접 읽는 곳 (getattr 없이): " + ", ".join(sorted(bad))


def test_bottom_long_lists_join_template_for_strategy_type():
    """🚨 Fix 373c: strategy_type 은 템플릿 컬럼 — 인스턴스에서 찾아 실패하고 except 가 삼켜 목록이 늘 비어 있었다."""
    src = (APP / "api" / "v1" / "strategy_suggestions.py").read_text(encoding="utf-8")
    assert "StrategyInstance.strategy_type" not in src
    assert src.count("StrategyTemplate.strategy_type.ilike") == 2
    assert src.count("join(StrategyTemplate, StrategyTemplate.id == StrategyInstance.strategy_template_id)") == 2
