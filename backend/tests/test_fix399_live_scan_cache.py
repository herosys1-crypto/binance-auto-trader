"""⚡ Fix 399 — 실시간 급등락 스캔에 공유 캐시 (2026-09-24).

사장님 「klines 1위 호출자 확인해줘」 → Fix 393/394 계측으로 잡은 순위:

    분당 weight 1,182 (한도 2400 의 49%) 중
      paper_trading            311  (26%)   ← 1위
      long_bottom_detector     130  (10%)
      api:live-pump-dump/scan  121  (10%)   ← 화면. 절충 없이 줄일 수 있는 유일한 항목
      external_strategies      120  (10%)

`/live-pump-dump/scan` 한 번 = 60종목 × (15m + 5m) = **호출 120건**이고 화면은 60초마다 폴링한다.
캐시가 없어서 **데스크탑+모바일을 같이 열면 그대로 2배**가 된다.

TTL 45초 = 폴링(60초)보다 짧아 한 화면의 신선도는 그대로, 화면이 여러 개일 때만 하나로 묶인다.
판정 로직·밴드·신뢰도 문턱은 건드리지 않는다 (캐시 키에 파라미터를 모두 넣어 섞이지 않게).
"""
from __future__ import annotations

from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "app" / "api" / "v1" / "live_pump_dump.py"


@pytest.fixture(scope="module")
def src() -> str:
    return SRC.read_text(encoding="utf-8")


def test_ttl_is_45(src: str) -> None:
    assert "LIVE_SCAN_CACHE_TTL_SEC = 45" in src


def test_cache_key_includes_all_params(src: str) -> None:
    """파라미터가 다른 요청이 서로의 결과를 받으면 안 된다."""
    line = next(ln for ln in src.splitlines() if "_cache_key = " in ln)
    for param in ("max_symbols", "include_dump", "min_confidence"):
        assert param in line, f"{param} 누락: {line}"


def test_cache_read_before_exchange_calls(src: str) -> None:
    body = src[src.index("def scan_live_pump_dump("):]
    i_read = body.index("_redis.get(_cache_key)")
    i_call = body.index("get_24hr_ticker()")
    assert i_read < i_call, "캐시 조회가 거래소 호출보다 앞이어야 절감된다"


def test_cache_write_on_success(src: str) -> None:
    body = src[src.index("def scan_live_pump_dump("):]
    assert "_redis.setex(_cache_key, LIVE_SCAN_CACHE_TTL_SEC" in body
    assert body.index("result = {") < body.index("_redis.setex(_cache_key")


def test_cache_failure_never_breaks_screen(src: str) -> None:
    """레디스가 죽어도 스캔은 돌아야 한다."""
    body = src[src.index("def scan_live_pump_dump("):]
    blk = body[:body.index("account = db.execute")]
    assert "except Exception:" in blk and "_redis = None" in blk


def test_crlf_preserved() -> None:
    raw = SRC.read_bytes()
    assert b"\r\n" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n")
