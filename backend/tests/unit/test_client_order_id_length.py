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
        assert len(cid) <= 28, f"too long: {cid!r}"
        # v3 (2026-05-13): 하이픈 → 언더스코어, PREFERRED_UUID = 16
        assert cid.startswith("BTC_EXIT_"), f"포맷 변경: 하이픈 → 언더스코어 (Binance Futures 안전): {cid!r}"
        assert len(cid.split("_")[-1]) == 16, f"PREFERRED_UUID = 16: {cid!r}"

    def test_normal_usdt_pair_under_35(self):
        cid = ExecutionService._new_client_order_id("BTCUSDT", "ENTRY1")
        assert len(cid) <= 28, f"too long: {cid!r}"

    def test_long_symbol_with_long_suffix_capped_at_35(self):
        # 사용자 보고 케이스 — 8자 symbol + ENTRY10M (8자)
        cid = ExecutionService._new_client_order_id("SAGAUSDT", "ENTRY10M")
        assert len(cid) <= 28, (
            f"-4015 회귀: SAGAUSDT+ENTRY10M cid too long ({len(cid)} chars): {cid!r}"
        )

    def test_very_long_symbol_still_under_35(self):
        # 신규 listing 등 9자 이상 symbol 도 안전
        cid = ExecutionService._new_client_order_id("MATICUSDT", "ENTRY10M")
        assert len(cid) <= 28, f"too long: {cid!r}"

    def test_extreme_case_uses_min_uuid(self):
        # v3 (2026-05-13): 28자 cap + 14자 symbol + 8자 suffix → uuid 4자 (= 16^4 = 65536 unique).
        # sub-minute 단위 운영에 충분 (수 초 간격 retry 시 충돌 확률 매우 낮음).
        cid = ExecutionService._new_client_order_id("VERYLONGSYMBOL", "ENTRY10M")
        assert len(cid) <= 28
        # symbol_suffix_uuid 포맷 유지 — uuid 부분 최소 4자
        uuid_part = cid.split("_")[-1]
        assert len(uuid_part) >= 4, f"uuid too short ({len(uuid_part)} chars)"

    def test_uniqueness_realistic_short_window(self):
        # v3 (2026-05-13): 실 운영 시나리오 — 같은 symbol/suffix 으로 30회 연속 호출.
        # JELLYJELLYUSDT (가장 긴 testnet symbol 14자) + EXIT (4자) → uuid 8자 = 16^8 = 42억 unique.
        # 30 samples 충돌 확률 거의 0%.
        cids = {ExecutionService._new_client_order_id("JELLYJELLYUSDT", "EXIT") for _ in range(30)}
        assert len(cids) == 30, f"30회 중 충돌 — uuid randomness 문제 (총 unique: {len(cids)})"

    def test_all_suffix_variants_safe_with_8char_symbol(self):
        # 실 운영 모든 suffix 변형 — 8자 symbol 기준
        suffixes = ["EXIT", "ENTRY1", "ENTRY10", "ENTRY1M", "ENTRY10M", "ADHOC_M", "ADHOC_L"]
        for suf in suffixes:
            cid = ExecutionService._new_client_order_id("SAGAUSDT", suf)
            assert len(cid) <= 28, f"suffix {suf!r}: cid {len(cid)}자 ({cid!r})"

    def test_format_remains_parseable(self):
        # v3 (2026-05-13): symbol_suffix_uuid (underscore) 포맷
        cid = ExecutionService._new_client_order_id("BTCUSDT", "ENTRY1")
        parts = cid.split("_")
        assert len(parts) == 3
        assert parts[0] == "BTCUSDT"
        assert parts[1] == "ENTRY1"
        assert all(c in "0123456789abcdef" for c in parts[2])

    def test_no_hyphens_in_cid(self):
        # v3 신규 (2026-05-13 사용자 #26 fix): 하이픈 절대 없음 (Binance Futures 안전).
        for sym in ["BTCUSDT", "JELLYJELLYUSDT", "VERYLONGSYMBOL"]:
            for suf in ["EXIT", "ENTRY1", "ENTRY10M", "ADHOC_M"]:
                cid = ExecutionService._new_client_order_id(sym, suf)
                assert "-" not in cid, f"하이픈 발견 (Binance Futures reject 위험): {cid!r}"
                # alphanumeric + underscore 만 (Binance Futures 엄격 규칙)
                assert all(c.isalnum() or c == "_" for c in cid), f"금지 문자 포함: {cid!r}"
