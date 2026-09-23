"""🚨 Fix 397 — 헤지 모드에서 같은 종목의 반대 다리를 집어 쓰던 것 (2026-09-23).

사장님 화면 (#4564 AGTUSDT LONG): `↑ 65,838  10/1700  1%` · `+14.85 (+148.53%)`
  · 실제 증거금 = 65,838 × 0.018249 ÷ 2 = **600.75** (거래소 isolatedMargin 610)
  · 그런데 분모가 **10** 으로 찍혔다 → 같은 종목 S4 SHORT(#4549)의 증거금 **10.23** 이다.

원인: `/exchange-accounts/{id}/binance-positions` 응답이 `positions[종목]` 으로만 키를 잡는다.
      헤지 모드는 한 종목에 LONG·SHORT 두 다리가 동시에 있으므로 **뒤에 온 다리가 앞 다리를
      덮는다.** 화면은 그 값을 증거금·ROI·마진율 정렬·Binance 대조에 그대로 썼다.
      (메모리에 이미 「헤지모드 대조 키 = (symbol, side)」로 남아 있던 함정 — 이 경로만 빠져 있었다.)

수정:
  · 백엔드: `positions_by_side["{종목}|{LONG|SHORT}"]` 를 **추가**한다.
    옛 `positions[종목]` 은 그대로 둔다 (이 맵을 세거나 훑는 화면이 있어 호환 유지).
  · 화면: `_bnPosFor(s)` 한 곳으로 모아 방향까지 맞춰 찾고, 옛 키는 **방향이 같을 때만** 쓴다.
  · 덤: 마크가격 조회가 존재하지 않는 캐시 키('acctId:SYMBOL')를 보고 있어 늘 역산 폴백이던 것도 고쳤다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app"
ACCOUNTS = APP / "api" / "v1" / "exchange_accounts.py"
LIST_JS = APP / "static" / "js" / "strategies-list.js"
ACTIONS_JS = APP / "static" / "js" / "strategy-actions.js"


@pytest.fixture(scope="module")
def api_src() -> str:
    return ACCOUNTS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def js() -> str:
    return LIST_JS.read_text(encoding="utf-8")


class TestBackend:
    def test_by_side_map_returned(self, api_src: str) -> None:
        assert "positions_by_side: dict = {}" in api_src
        assert '"positions_by_side": positions_by_side' in api_src

    def test_by_side_key_includes_direction(self, api_src: str) -> None:
        assert "positions_by_side[f\"{p['symbol']}|{_side}\"] = _entry" in api_src

    def test_entry_carries_position_side(self, api_src: str) -> None:
        """화면이 옛 키를 쓸 때 방향을 검증할 수 있게 값에도 방향을 넣는다."""
        assert '"position_side": _side,' in api_src

    def test_legacy_symbol_key_kept(self, api_src: str) -> None:
        """옛 키를 지우면 포지션 수를 세는 화면들이 깨진다 — 유지."""
        assert 'positions[p["symbol"]] = _entry' in api_src


class TestFrontend:
    def test_helper_prefers_side_key(self, js: str) -> None:
        fn = js[js.index("function _bnPosFor(s)"):]
        fn = fn[:fn.index("\n}")]
        assert "positions_by_side" in fn
        assert "sym + '|' + side" in fn
        assert "legacySide !== side" in fn, "옛 키는 방향이 같을 때만 쓴다"
        assert fn.index("positions_by_side") < fn.index("acct.positions || {}"), "방향 키를 먼저 본다"

    def test_all_lookups_go_through_helper(self, js: str) -> None:
        """종목만으로 찾는 코드가 남아 있으면 같은 사고가 반복된다."""
        assert "(acctData.positions || {})[s.symbol]" not in js
        assert "?.positions || {})[s.symbol]" not in js
        assert js.count("_bnPosFor(s)") >= 4

    def test_mark_price_uses_real_cache(self, js: str) -> None:
        """존재하지 않는 'acctId:SYMBOL' 키를 보던 것 수정."""
        assert "(s.exchange_account_id || '?') + ':' + (s.symbol || '').toUpperCase()" not in js
        assert "_bp.mark_price || _bp.markPrice" in js

    def test_actions_js_also_direction_aware(self) -> None:
        src = ACTIONS_JS.read_text(encoding="utf-8")
        assert "_bnPosFor(strategy)" in src


@pytest.mark.parametrize("path", [ACCOUNTS, LIST_JS, ACTIONS_JS])
def test_crlf_preserved(path: Path) -> None:
    """프로젝트 규칙 8 — 이 파일들은 CRLF 다."""
    raw = path.read_bytes()
    assert b"\r\n" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n")
