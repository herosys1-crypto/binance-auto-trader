"""_update_peak_pnl — Redis 휘발 시 DB max_profit_pct fallback (2026-05-06 #103 사례).

배경:
  사용자 #103 FHEUSDT TP3 까지 발동 (피크 +20%) 후 가격 회귀로 +7% — 피크 대비
  -13% 인데 trailing TP 미발동. 원인: Redis peak key 휘발 → 새 peak=7% 로 reset
  → trailing 평가 7 <= 7-5=2 false → 미발동.

  Fix: _update_peak_pnl 이 db_max_profit_pct 인자 받아 fallback 으로 사용.
  true_peak = max(current, redis_stored, db_max_profit).
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


class FakeRedisClient:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value.encode("utf-8") if isinstance(value, str) else value


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeRedisClient()
    from app.services import risk_service as risk_module
    monkeypatch.setattr(risk_module, "get_redis_client", lambda: fake)
    return fake


@pytest.fixture
def risk_service(fake_redis):
    """RiskService 인스턴스 — DB 의존 없는 메서드만 테스트."""
    from app.services.risk_service import RiskService
    db = MagicMock()
    return RiskService(db)


class TestPeakPnlRedisFallback:
    def test_redis_empty_uses_db_fallback(self, risk_service, fake_redis):
        """Redis 비어있음 + DB max_profit=20 → peak = max(current=7, db=20) = 20."""
        peak = risk_service._update_peak_pnl(
            strategy_id=103,
            current_pnl_pct=Decimal("7"),
            db_max_profit_pct=Decimal("20"),
        )
        assert peak == Decimal("20"), (
            "Redis 휘발 시 DB max_profit_pct 로 fallback 해야 함 (#103 사례)"
        )
        # Redis 도 fallback 값으로 갱신됐어야
        stored = fake_redis.get("strategy:103:peak_pnl_pct")
        assert stored == b"20"

    def test_redis_stale_lower_than_db_uses_db(self, risk_service, fake_redis):
        """Redis 7 (stale) + DB 20 → peak 20 으로 보정."""
        fake_redis.set("strategy:103:peak_pnl_pct", "7", ex=300)
        peak = risk_service._update_peak_pnl(
            strategy_id=103,
            current_pnl_pct=Decimal("6"),
            db_max_profit_pct=Decimal("20"),
        )
        assert peak == Decimal("20")
        # Redis 도 보정됐어야
        stored = fake_redis.get("strategy:103:peak_pnl_pct")
        assert stored == b"20"

    def test_redis_higher_than_db_kept(self, risk_service, fake_redis):
        """Redis 25 (이번 사이클 갱신됐음) + DB 20 → peak 25."""
        fake_redis.set("strategy:103:peak_pnl_pct", "25", ex=300)
        peak = risk_service._update_peak_pnl(
            strategy_id=103,
            current_pnl_pct=Decimal("8"),
            db_max_profit_pct=Decimal("20"),
        )
        assert peak == Decimal("25")

    def test_current_higher_than_all_updates_redis(self, risk_service, fake_redis):
        """현재 PnL 이 가장 큰 경우 → Redis + return 모두 current."""
        fake_redis.set("strategy:103:peak_pnl_pct", "10", ex=300)
        peak = risk_service._update_peak_pnl(
            strategy_id=103,
            current_pnl_pct=Decimal("30"),
            db_max_profit_pct=Decimal("20"),
        )
        assert peak == Decimal("30")
        stored = fake_redis.get("strategy:103:peak_pnl_pct")
        assert stored == b"30"

    def test_db_none_fallback_works(self, risk_service, fake_redis):
        """DB max_profit None (신규 strategy) — Redis 또는 current 사용."""
        peak = risk_service._update_peak_pnl(
            strategy_id=103,
            current_pnl_pct=Decimal("7"),
            db_max_profit_pct=None,
        )
        assert peak == Decimal("7")  # Redis 비어있고 DB None → current

    def test_redis_failure_falls_back_to_db(self, risk_service, monkeypatch):
        """Redis 자체 raise → DB fallback 으로 max(current, db_max) 반환."""
        from app.services import risk_service as risk_module
        def _raise():
            raise RuntimeError("Redis connection lost")
        monkeypatch.setattr(risk_module, "get_redis_client", _raise)

        peak = risk_service._update_peak_pnl(
            strategy_id=103,
            current_pnl_pct=Decimal("7"),
            db_max_profit_pct=Decimal("20"),
        )
        assert peak == Decimal("20"), "Redis 장애 시에도 DB fallback 으로 trailing 보장"

    def test_103_scenario_full_recovery(self, risk_service, fake_redis):
        """#103 정확한 시나리오 시뮬: 피크 20.24, 현재 7, Redis 휘발.

        다음 evaluate_take_profit_level 호출 시:
          1. _update_pnl_extremes 가 max_profit_pct=20.24 (이전 갱신값) 보존
          2. _update_peak_pnl(7, db=20.24) → peak=20.24
          3. trailing 평가: 20.24 >= 5 ✓ AND 7 <= 20.24-5=15.24 ✓ → TRAILING_TP 발동
        """
        # Redis 휘발 시뮬
        peak = risk_service._update_peak_pnl(
            strategy_id=103,
            current_pnl_pct=Decimal("7"),
            db_max_profit_pct=Decimal("20.24"),
        )
        assert peak == Decimal("20.24")
        # trailing 조건 검증 (수동)
        TRAILING_PEAK_THRESHOLD = Decimal("5")
        TRAILING_RETRACE = Decimal("5")
        current = Decimal("7")
        # 조건: peak >= 5 AND current <= peak - 5 AND current < peak
        assert peak >= TRAILING_PEAK_THRESHOLD
        assert current <= (peak - TRAILING_RETRACE)
        assert current < peak
        # → trailing 발동돼야 ✓
