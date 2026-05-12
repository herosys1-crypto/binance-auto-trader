"""Binance newClientOrderId 안전 cap 회귀 (사용자 보고 -4015).

이력:
- 2026-05-12 v1: 35자 cap (Binance error msg "less than 36 chars" 기준)
- 2026-05-13 v2: 32자 cap — 35자 적용 후에도 #26 JELLYJELLYUSDT 에서 -4015 재발.
  Binance Futures 실제 한도가 36 보다 작은 것으로 추정 (32 추정).
  안전하게 32자로 줄임 — 어떤 Binance 정책 변경에도 충돌 안 함.

Fix:
uuid 길이를 가용 공간에 맞게 동적 산출 (선호 18, 최소 8). 전체 32자 cap.
"""
from __future__ import annotations

from app.services.execution_service import ExecutionService


class TestClientOrderIdLength:
    def test_short_symbol_short_suffix_uses_full_uuid(self):
        cid = ExecutionService._new_client_order_id("BTC", "EXIT")
        assert len(cid) <= 32, f"too long: {cid!r}"
        # 가용 공간 충분 → uuid 18자 그대로
        assert cid.startswith("BTC-EXIT-")
        assert len(cid.split("-")[-1]) == 18

    def test_normal_usdt_pair_under_35(self):
        cid = ExecutionService._new_client_order_id("BTCUSDT", "ENTRY1")
        assert len(cid) <= 32, f"too long: {cid!r}"

    def test_long_symbol_with_long_suffix_capped_at_35(self):
        # 사용자 보고 케이스 — 8자 symbol + ENTRY10M (8자)
        cid = ExecutionService._new_client_order_id("SAGAUSDT", "ENTRY10M")
        assert len(cid) <= 32, (
            f"-4015 회귀: SAGAUSDT+ENTRY10M cid too long ({len(cid)} chars): {cid!r}"
        )

    def test_very_long_symbol_still_under_35(self):
        # 신규 listing 등 9자 이상 symbol 도 안전
        cid = ExecutionService._new_client_order_id("MATICUSDT", "ENTRY10M")
        assert len(cid) <= 32, f"too long: {cid!r}"

    def test_extreme_case_uses_min_uuid(self):
        # 극단 케이스: 매우 긴 symbol — uuid 최소 8자라도 보장
        cid = ExecutionService._new_client_order_id("VERYLONGSYMBOL", "ENTRY10M")
        assert len(cid) <= 32
        # uuid 부분이 최소 8자 이상이어야 충돌 방지
        # "VERYLONGSYMBOL-ENTRY10M-" = 24자, 35-24=11자 → 11자 uuid (>=8 ✓)
        uuid_part = cid.split("-")[-1]
        assert len(uuid_part) >= 8, f"uuid too short ({len(uuid_part)} chars), 충돌 위험"

    def test_uniqueness_within_minimum_uuid(self):
        # 짧은 uuid (8자) 라도 매 호출마다 unique 해야 함
        cids = {ExecutionService._new_client_order_id("VERYLONGSYMBOL", "ENTRY10M") for _ in range(100)}
        assert len(cids) == 100, "100회 호출 중 충돌 발생 — uuid randomness 문제"

    def test_all_suffix_variants_safe_with_8char_symbol(self):
        # 실 운영 모든 suffix 변형 — 8자 symbol 기준
        suffixes = ["EXIT", "ENTRY1", "ENTRY10", "ENTRY1M", "ENTRY10M", "ADHOC_M", "ADHOC_L"]
        for suf in suffixes:
            cid = ExecutionService._new_client_order_id("SAGAUSDT", suf)
            assert len(cid) <= 32, f"suffix {suf!r}: cid {len(cid)}자 ({cid!r})"

    def test_format_remains_parseable(self):
        # symbol-suffix-uuid 포맷 유지 — 후속 디버깅/검색 가능해야
        cid = ExecutionService._new_client_order_id("BTCUSDT", "ENTRY1")
        parts = cid.split("-")
        assert len(parts) == 3
        assert parts[0] == "BTCUSDT"
        assert parts[1] == "ENTRY1"
        assert all(c in "0123456789abcdef" for c in parts[2])
