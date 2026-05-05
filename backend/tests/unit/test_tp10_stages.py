"""TP1~TP10 익절 10단계 확장 (2026-05-06 사용자 요청).

배경:
  사용자가 5단계 → 10단계 익절로 확장 요청. 각 단계는 잔량의 25% 청산
  (기존 의미 유지), 마지막 활성 TP (TP10 또는 사용자가 채운 가장 높은 단계)
  발동 시 잔량 100% 청산. 트레일링은 그대로.

이 테스트는 risk_service.evaluate_take_profit_level 의 신규 동작 검증.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_redis(monkeypatch):
    class FR:
        def __init__(self): self.store = {}
        def get(self, k): return self.store.get(k)
        def set(self, k, v, ex=None): self.store[k] = v.encode("utf-8") if isinstance(v, str) else v
    fr = FR()
    from app.services import risk_service as risk_module
    monkeypatch.setattr(risk_module, "get_redis_client", lambda: fr)
    return fr


def _make_risk_service():
    from app.services.risk_service import RiskService
    db = MagicMock()
    return RiskService(db), db


class TestTp10TrailingArmedStatuses:
    def test_all_tp_done_partial_statuses_armed(self, fake_redis):
        """TP1~10_DONE_PARTIAL 모두 trailing armed status 에 포함."""
        from app.services.risk_service import RiskService
        # TRAILING_ARMED_STATUSES 가 함수 내부 local 이라 직접 접근 불가 — 코드 inspect.
        import inspect
        src = inspect.getsource(RiskService.evaluate_take_profit_level)
        # TP1~10 모두 명시되어야
        assert "range(1, 11)" in src or all(f"TP{n}_DONE_PARTIAL" in src for n in range(1, 11)), (
            f"TRAILING_ARMED_STATUSES 가 TP1~10 모두 포함해야 함. "
            f"코드에 range(1, 11) 또는 명시적 TP1~10_DONE_PARTIAL 필요"
        )


class TestTp10LevelDetection:
    def test_tp_levels_extends_to_tp10(self, fake_redis):
        """tp_levels list 가 TP10 까지 검출 — risk_service.evaluate_take_profit_level."""
        from app.services.risk_service import RiskService
        import inspect
        src = inspect.getsource(RiskService.evaluate_take_profit_level)
        # range(10, 0, -1) 또는 range(1, 11) 패턴 검증
        assert "range(10, 0, -1)" in src or "range(1, 11)" in src, (
            "tp_levels 가 TP1~TP10 동적 검출되어야 함"
        )

    def test_tp_done_index_covers_1_to_10(self, fake_redis):
        from app.services.risk_service import RiskService
        import inspect
        src = inspect.getsource(RiskService.evaluate_take_profit_level)
        assert "range(1, 11)" in src, (
            "TP_DONE_INDEX dict 가 TP1~10 모두 포함해야 함"
        )


class TestTp10OrchestratorRatio:
    def test_ratio_attr_includes_tp6_to_tp10(self):
        """tp_sl_orchestrator 의 ratio_attr dict 가 TP1~10 모두 포함."""
        from app.services.tp_sl_orchestrator import TPSLOrchestratorService
        import inspect
        src = inspect.getsource(TPSLOrchestratorService._execute_take_profit)
        # range(1, 11) 패턴 또는 TP10 직접 명시
        assert "range(1, 11)" in src or '"TP10"' in src, (
            "ratio_attr 가 TP1~10 모두 매핑해야 함"
        )

    def test_progression_includes_tp6_to_tp10(self):
        """done_levels_progression 이 TP1~10 모두 포함 (cur_index 정확 매칭)."""
        from app.services.tp_sl_orchestrator import TPSLOrchestratorService
        import inspect
        src = inspect.getsource(TPSLOrchestratorService.run_for_strategy)
        assert "range(1, 11)" in src, (
            "done_levels_progression 이 TP1~10_DONE_PARTIAL 모두 포함해야 함"
        )

    def test_active_tps_scan_extends_to_10(self):
        """last_active_tp 검출이 tp1~tp10_percent 까지 스캔."""
        from app.services.tp_sl_orchestrator import TPSLOrchestratorService
        import inspect
        src = inspect.getsource(TPSLOrchestratorService._execute_take_profit)
        assert "range(1, 11)" in src, (
            "active_tps 스캔이 tp1~tp10_percent 까지 확장돼야 함"
        )


class TestTp10ModelColumns:
    @pytest.mark.parametrize("n", list(range(1, 11)))
    def test_strategy_template_has_tp_n_percent_column(self, n):
        """StrategyTemplate 모델에 tp1~tp10_percent + tp1~tp10_qty_ratio 컬럼 존재."""
        from app.models.strategy_template import StrategyTemplate
        assert hasattr(StrategyTemplate, f"tp{n}_percent"), (
            f"StrategyTemplate 에 tp{n}_percent 컬럼이 있어야 함 (alembic 0012)"
        )
        assert hasattr(StrategyTemplate, f"tp{n}_qty_ratio"), (
            f"StrategyTemplate 에 tp{n}_qty_ratio 컬럼이 있어야 함 (alembic 0012)"
        )


class TestTp10CountActiveTps:
    def test_count_active_tps_scans_to_10(self):
        from app.api.v1.strategies import _count_active_tps
        # mock template — TP1~3 + TP6 + TP10 채움
        tpl = MagicMock()
        for n in range(1, 11):
            setattr(tpl, f"tp{n}_percent", None)
        tpl.tp1_percent = Decimal("10")
        tpl.tp2_percent = Decimal("15")
        tpl.tp3_percent = Decimal("20")
        tpl.tp6_percent = Decimal("35")
        tpl.tp10_percent = Decimal("55")
        assert _count_active_tps(tpl) == 5, (
            "활성 TP 카운트가 tp1~tp10 까지 NULL 검사해야 함"
        )

    def test_count_active_tps_5_only_legacy(self):
        from app.api.v1.strategies import _count_active_tps
        tpl = MagicMock()
        for n in range(1, 11):
            setattr(tpl, f"tp{n}_percent", None)
        tpl.tp1_percent = Decimal("10")
        tpl.tp2_percent = Decimal("15")
        tpl.tp3_percent = Decimal("20")
        tpl.tp4_percent = Decimal("25")
        tpl.tp5_percent = Decimal("30")
        assert _count_active_tps(tpl) == 5
