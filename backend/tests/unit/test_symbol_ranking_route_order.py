"""GET /symbols/ranking — route 등록 순서 검증.

2026-05-06 (사용자 요청 24h/주/월 변동률 순위 기능 추가):
  /symbols/{symbol} catch-all 패턴 보다 /symbols/ranking specific path 가
  먼저 등록되어야 FastAPI 의 first-match 라우팅이 ranking 으로 매치됨.

  이 테스트는 router.routes 의 path 순서를 검증해서, 향후 코드 변경 시
  실수로 순서가 뒤집히면 즉시 발견되도록 가드.
"""
from __future__ import annotations

import pytest


def test_ranking_route_registered_before_catch_all_symbol():
    from app.api.v1.symbols import router
    paths = [r.path for r in router.routes]
    # 두 path 모두 존재
    assert "/symbols/ranking" in paths, "ranking endpoint 등록 누락"
    assert "/symbols/{symbol}" in paths, "get_symbol catch-all 누락"
    # ranking 이 catch-all 보다 먼저
    ranking_idx = paths.index("/symbols/ranking")
    symbol_idx = paths.index("/symbols/{symbol}")
    assert ranking_idx < symbol_idx, (
        f"/symbols/ranking 가 /symbols/{{symbol}} 보다 먼저 등록돼야 함 "
        f"(현재 ranking={ranking_idx}, symbol={symbol_idx}). "
        f"file 끝의 router.add_api_route(/{{symbol}}, ...) 가 누락됐을 수 있음."
    )


def test_period_keys_supported():
    """/symbols/ranking 에서 지원하는 period 목록 검증."""
    from app.api.v1.symbols import _PERIOD_TO_KLINE_PARAMS
    expected = {"1d", "2d", "3d", "4d", "5d", "6d", "7d", "1w", "2w", "1m", "3m", "6m", "1y"}
    actual = set(_PERIOD_TO_KLINE_PARAMS.keys())
    assert actual == expected, f"period 옵션 mismatch: {actual} != {expected}"


def test_each_period_has_cache_ttl():
    from app.api.v1.symbols import _PERIOD_TO_KLINE_PARAMS, _CACHE_TTL_SEC
    for period in _PERIOD_TO_KLINE_PARAMS:
        assert period in _CACHE_TTL_SEC, f"period {period} 의 cache TTL 누락"
        assert _CACHE_TTL_SEC[period] > 0, f"period {period} TTL 양수여야 함"


def test_short_period_short_ttl_long_period_long_ttl():
    """1d 는 짧은 TTL (60s), 1y 는 긴 TTL (4h+) — 신선도 vs API 부하 trade-off."""
    from app.api.v1.symbols import _CACHE_TTL_SEC
    assert _CACHE_TTL_SEC["1d"] <= 120, "1d cache 너무 길면 실시간성 떨어짐"
    assert _CACHE_TTL_SEC["1y"] >= 3600, "1y cache 너무 짧으면 API 부담"
