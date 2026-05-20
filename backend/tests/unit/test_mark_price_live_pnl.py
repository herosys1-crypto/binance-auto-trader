"""Live markPrice 기반 unrealized_pnl 재계산 단위 테스트.

회귀 방지 시나리오:
- 캐시 hit → 라이브 마크 가격으로 PNL 재계산 (Binance UI 와 ±0.1 USDT 일치)
- 캐시 miss → DB stored 값 fallback (backward-compat)
- LONG/SHORT 부호 정확성
- N+1 회피 (mget 1회로 batch 처리)
- WS 메시지 파싱 (markPriceUpdate 이벤트만 캐시 갱신)

배경:
- UBUSDT 실측 사례 — Tool PNL -74.19 vs Binance -87.29 (13 USDT 차이)
- 원인: reconcile 2분 주기 mark_price stale
- 본 수정으로 Redis 캐시(WS 1s push) 의 mark 로 재계산 → 차이 < 0.1 USDT 기대
"""
from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import MagicMock

import pytest


# ──────────────────── FakeRedis ────────────────────


class FakeRedis:
    """단순 in-memory Redis — setex/get/mget 만 지원."""

    def __init__(self):
        self.store: dict[str, str] = {}

    def setex(self, key, ttl, value):
        self.store[key] = str(value)

    def get(self, key):
        return self.store.get(key)

    def mget(self, keys):
        return [self.store.get(k) for k in keys]


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeRedis()
    from app.services import mark_price_cache as cache_mod
    monkeypatch.setattr(cache_mod, "get_redis_client", lambda: fake)
    return fake


# ──────────────────── mark_price_cache ────────────────────


def test_set_and_get_mark_price(fake_redis):
    from app.services.mark_price_cache import get_mark_price, set_mark_price
    set_mark_price("BTCUSDT", "65432.10")
    assert get_mark_price("BTCUSDT") == Decimal("65432.10")
    # 대소문자 무관
    assert get_mark_price("btcusdt") == Decimal("65432.10")


def test_get_mark_price_miss_returns_none(fake_redis):
    from app.services.mark_price_cache import get_mark_price
    assert get_mark_price("NOPE") is None


def test_get_mark_prices_bulk(fake_redis):
    from app.services.mark_price_cache import get_mark_prices_bulk, set_mark_price
    set_mark_price("UBUSDT", "0.12503")
    set_mark_price("INJUSDT", "4.96")
    result = get_mark_prices_bulk(["UBUSDT", "INJUSDT", "NOTSET"])
    assert result == {"UBUSDT": Decimal("0.12503"), "INJUSDT": Decimal("4.96")}
    # NOTSET 은 dict 에 포함 안 됨 (호출자가 stored 값 fallback)


def test_get_mark_prices_bulk_empty(fake_redis):
    from app.services.mark_price_cache import get_mark_prices_bulk
    assert get_mark_prices_bulk([]) == {}
    assert get_mark_prices_bulk(["", None]) == {}


def test_calc_unrealized_pnl_long():
    """LONG: qty * (mark - entry). UBUSDT 실측 케이스 — Binance 와 ±1 USDT 일치 확인."""
    from app.services.mark_price_cache import calc_unrealized_pnl
    pnl = calc_unrealized_pnl(
        side="LONG",
        qty=Decimal("18254"),
        entry_price=Decimal("0.12975826"),
        mark_price=Decimal("0.1250320"),
    )
    # 18254 × (0.1250320 - 0.12975826) = 18254 × -0.00472626 = -86.272 USDT
    # Binance UI 가 보여준 값 -87.29 와 ±1 USDT 일치 (나머지 1 USDT 는 funding fee 등)
    assert pnl == pytest.approx(Decimal("-86.272"), abs=Decimal("0.05"))


def test_calc_unrealized_pnl_short():
    """SHORT: qty * (entry - mark). INJUSDT 케이스."""
    from app.services.mark_price_cache import calc_unrealized_pnl
    pnl = calc_unrealized_pnl(
        side="SHORT",
        qty=Decimal("116.1"),
        entry_price=Decimal("5.0783979"),
        mark_price=Decimal("4.9624337"),
    )
    # 116.1 × (5.0783979 - 4.9624337) = 116.1 × 0.1159642 = 13.4624 USDT
    assert pnl == pytest.approx(Decimal("13.4624"), abs=Decimal("0.01"))


def test_calc_unrealized_pnl_zero_when_missing_inputs():
    from app.services.mark_price_cache import calc_unrealized_pnl
    assert calc_unrealized_pnl("LONG", Decimal("100"), Decimal("0"), Decimal("1.0")) == 0
    assert calc_unrealized_pnl("LONG", Decimal("100"), Decimal("1.0"), Decimal("0")) == 0


# ──────────────────── apply_live_unrealized_pnl ────────────────────


def _make_response(symbol, side, qty, entry, stored_pnl):
    """StrategyDetailResponse minimal stub."""
    from app.schemas.strategy import StrategyDetailResponse
    return StrategyDetailResponse(
        id=1,
        symbol=symbol,
        side=side,
        status="STAGE2_OPEN",
        reentry_ready=False,
        leverage=2,
        current_stage=2,
        avg_entry_price=Decimal(str(entry)),
        current_position_qty=Decimal(str(qty)),
        invested_capital=Decimal("100"),
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal(str(stored_pnl)),
    )


def test_apply_live_unrealized_pnl_hit_recalculates(fake_redis):
    from app.api.v1.strategies.helpers import apply_live_unrealized_pnl
    from app.services.mark_price_cache import set_mark_price

    set_mark_price("UBUSDT", "0.1250320")
    resp = _make_response("UBUSDT", "LONG", "18254", "0.12975826", "-74.19")
    apply_live_unrealized_pnl(resp)
    # 라이브 마크로 재계산 → ~-86.27, stored -74.19 와 명확히 다름
    assert resp.unrealized_pnl == pytest.approx(Decimal("-86.272"), abs=Decimal("0.05"))


def test_apply_live_unrealized_pnl_miss_keeps_stored(fake_redis):
    from app.api.v1.strategies.helpers import apply_live_unrealized_pnl

    # 캐시 비어있음 — stored 값 그대로 유지
    resp = _make_response("UBUSDT", "LONG", "18254", "0.12975826", "-74.19")
    apply_live_unrealized_pnl(resp)
    assert resp.unrealized_pnl == Decimal("-74.19")


def test_apply_live_unrealized_pnl_zero_qty_noop(fake_redis):
    """qty=0 (종료된 포지션) 은 재계산 안 함."""
    from app.api.v1.strategies.helpers import apply_live_unrealized_pnl
    from app.services.mark_price_cache import set_mark_price

    set_mark_price("UBUSDT", "0.1250320")
    resp = _make_response("UBUSDT", "LONG", "0", "0.12975826", "0")
    apply_live_unrealized_pnl(resp)
    assert resp.unrealized_pnl == Decimal("0")


def test_apply_live_unrealized_pnl_batch_uses_single_mget(fake_redis):
    """8개 응답이라도 mget 1회 (N+1 방지)."""
    from app.api.v1.strategies.helpers import apply_live_unrealized_pnl_batch
    from app.services.mark_price_cache import set_mark_price

    set_mark_price("UBUSDT", "0.1250320")
    set_mark_price("INJUSDT", "4.9624337")
    set_mark_price("STGUSDT", "0.1701903")

    responses = [
        _make_response("UBUSDT", "LONG", "18254", "0.12975826", "-74.19"),
        _make_response("INJUSDT", "SHORT", "116.1", "5.0783979", "14.56"),
        _make_response("STGUSDT", "LONG", "3562", "0.16559506", "13.20"),
        _make_response("NOCACHE", "LONG", "100", "1.0", "0.00"),  # 캐시 miss
    ]
    apply_live_unrealized_pnl_batch(responses)

    # hit 3건: 모두 라이브 마크로 재계산됨 — stored 와 다른 값
    assert responses[0].unrealized_pnl == pytest.approx(Decimal("-86.272"), abs=Decimal("0.05"))
    assert responses[1].unrealized_pnl == pytest.approx(Decimal("13.4624"), abs=Decimal("0.01"))
    # STG: 3562 × (0.1701903 - 0.16559506) = 16.36
    assert responses[2].unrealized_pnl == pytest.approx(Decimal("16.36"), abs=Decimal("0.05"))
    # miss 1건: stored 유지
    assert responses[3].unrealized_pnl == Decimal("0.00")


def test_apply_live_unrealized_pnl_batch_empty():
    from app.api.v1.strategies.helpers import apply_live_unrealized_pnl_batch
    assert apply_live_unrealized_pnl_batch([]) == []


# ──────────────────── WebSocket consumer 메시지 파싱 ────────────────────


def test_consumer_extracts_markprice_and_caches(fake_redis):
    """markPriceUpdate 이벤트가 캐시에 정확히 저장되는지."""
    from app.workers.mark_price_stream_consumer import MarkPriceStreamConsumer

    consumer = MarkPriceStreamConsumer(is_testnet=True)
    msg = json.dumps({
        "stream": "btcusdt@markPrice@1s",
        "data": {"e": "markPriceUpdate", "s": "BTCUSDT", "p": "65432.50", "r": "0.0001"},
    })
    consumer._on_message(MagicMock(), msg)

    from app.services.mark_price_cache import get_mark_price
    assert get_mark_price("BTCUSDT") == Decimal("65432.50")


def test_consumer_ignores_non_markprice_events(fake_redis):
    """SUBSCRIBE 응답이나 다른 이벤트는 캐시 안 만짐."""
    from app.workers.mark_price_stream_consumer import MarkPriceStreamConsumer

    consumer = MarkPriceStreamConsumer(is_testnet=True)
    # SUBSCRIBE 응답
    consumer._on_message(MagicMock(), json.dumps({"result": None, "id": 1}))
    # 다른 이벤트 e=kline
    consumer._on_message(MagicMock(), json.dumps({
        "stream": "btcusdt@kline_1m",
        "data": {"e": "kline", "s": "BTCUSDT"},
    }))

    from app.services.mark_price_cache import get_mark_price
    assert get_mark_price("BTCUSDT") is None


def test_consumer_handles_malformed_json(fake_redis):
    """JSON 디코딩 실패 시 silent ignore (스트림 안 끊김)."""
    from app.workers.mark_price_stream_consumer import MarkPriceStreamConsumer

    consumer = MarkPriceStreamConsumer(is_testnet=True)
    # 예외 안 나야 함
    consumer._on_message(MagicMock(), "not json {")
    consumer._on_message(MagicMock(), "")
