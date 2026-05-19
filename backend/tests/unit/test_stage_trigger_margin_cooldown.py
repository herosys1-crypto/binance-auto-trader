"""stage_trigger 마진부족(-2019) 쿨다운 헬퍼 회귀.

배경 (사용자 보고 2026-05-19):
- 13개 동시 전략으로 가용 증거금 소진 → 다음 단계 진입이 -2019
  "Margin is insufficient" 거부
- is_triggered=False 라 stage_trigger 가 매 10초 재시도 → 거래소 주문 spam
  (rate-limit 기여) + Telegram spam + 자동 해소 안 됨

Fix: -2019 감지 시 (strategy,stage) Redis 30분 쿨다운 + 알림 1회 (dedup).
쿨다운 중 그 단계 skip. ban guard / -4131 / flat-record 와 동일 클래스.
"""
from __future__ import annotations

from app.workers.stage_trigger_worker import (
    _is_margin_insufficient,
    _margin_cooldown_active,
    _set_margin_cooldown,
)


class _FakeRedis:
    """최소 Redis 모킹 — get/setex 만."""
    def __init__(self):
        self.store: dict[str, str] = {}

    def get(self, k):
        return self.store.get(k)

    def setex(self, k, ttl, v):
        self.store[k] = v


class TestIsMarginInsufficient:
    def test_detects_2019_code(self):
        e = Exception("Binance API error: status=400, code=-2019, msg=Margin is insufficient.")
        assert _is_margin_insufficient(e) is True

    def test_detects_message_only(self):
        assert _is_margin_insufficient(Exception("Margin is insufficient")) is True

    def test_other_error_not_matched(self):
        assert _is_margin_insufficient(Exception("code=-4131 PERCENT_PRICE")) is False
        assert _is_margin_insufficient(Exception("connection timeout")) is False


class TestMarginCooldown:
    def test_first_set_returns_true_then_dedup(self):
        """첫 설정 True(알림 발송), 같은 키 재설정 False(dedup)."""
        r = _FakeRedis()
        assert _margin_cooldown_active(r, 62, 3) is False  # 초기 없음
        assert _set_margin_cooldown(r, 62, 3) is True       # 첫 설정 → 알림
        assert _margin_cooldown_active(r, 62, 3) is True    # 이제 쿨다운 중
        assert _set_margin_cooldown(r, 62, 3) is False      # 재시도 → dedup (알림 X)

    def test_cooldown_isolated_per_strategy_stage(self):
        """쿨다운은 (strategy,stage) 단위 — 다른 전략/단계엔 영향 없음."""
        r = _FakeRedis()
        _set_margin_cooldown(r, 62, 3)
        assert _margin_cooldown_active(r, 62, 3) is True
        assert _margin_cooldown_active(r, 62, 4) is False  # 같은 전략 다른 단계
        assert _margin_cooldown_active(r, 99, 3) is False  # 다른 전략

    def test_redis_none_failopen(self):
        """redis 장애(None) 시: 쿨다운 비활성(False) + 설정은 True 반환(알림은 보냄)."""
        assert _margin_cooldown_active(None, 1, 1) is False
        assert _set_margin_cooldown(None, 1, 1) is True

    def test_redis_exception_failopen(self):
        """redis 호출 예외 시에도 안전 (거래 흐름 막지 않음)."""
        class _BrokenRedis:
            def get(self, k):
                raise RuntimeError("redis down")
            def setex(self, k, t, v):
                raise RuntimeError("redis down")
        rb = _BrokenRedis()
        assert _margin_cooldown_active(rb, 1, 1) is False
        assert _set_margin_cooldown(rb, 1, 1) is True
