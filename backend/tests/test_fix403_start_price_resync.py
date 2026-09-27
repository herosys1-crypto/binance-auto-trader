"""🩹 Fix 403 — 심볼을 바꾸면 시작가도 새 현재가로 갱신 (2026-09-27).

사장님 「시작가 자동 갱신도 고쳐줘」.

사장님 화면 실측(9/27, Fix 402 를 유발한 그 화면):
    차트 현재가 **123.61** (24h +27.55%) ← 새로 고른 심볼
    시작가·단계가 **0.0307** 대               ← 옛 심볼 기준으로 남은 값
  → 미리보기가 깨졌고(가격 0 계열 오류), 그대로 「전략 시작」을 누르면 **엉뚱한 가격에 예약 주문**이
    들어간다. 옛 코드는 시작가가 **비어 있을 때만** 채웠다(`!value || <= 0`).

판정 두 가지로 갈아준다:
  ① 시작가를 채운 심볼(`_cmStartPriceSymbol`)이 지금 심볼과 다르다.
  ② 기록이 없어도(직접 타이핑) 현재가와 **20배 이상** 벌어졌다 (123.61 vs 0.0307 = 4,000배).
「수정 모드」(editingStrategyId)는 건드리지 않는다 — 사장님 사상 v39: 1단계 = 옛 평단 보존.
갱신하면 toast 로 무엇이 왜 바뀌었는지 알린다 (조용히 바꾸지 않는다).
"""
from __future__ import annotations

from pathlib import Path

import pytest

JS = Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "cm-market-info.js"


@pytest.fixture(scope="module")
def src() -> str:
    return JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def block(src: str) -> str:
    i = src.index("const startInp = document.getElementById('cm-start-price');")
    return src[i:i + 2600]


def test_tracks_which_symbol_filled_it(src: str) -> None:
    assert "let _cmStartPriceSymbol = null;" in src
    # fillStartPrice 가 값을 넣을 때 기록한다
    fn = src[src.index("function fillStartPrice(mode)"):]
    assert "_cmStartPriceSymbol = (document.getElementById('cm-symbol').value" in fn


def test_refreshes_when_symbol_changed(block: str) -> None:
    assert "_cmStartPriceSymbol !== symbol" in block
    assert "symbolChanged" in block
    assert "fillStartPrice('current')" in block


def test_refreshes_when_way_off_without_record(block: str) -> None:
    """직접 타이핑해 기록이 없어도 현재가와 20배 이상이면 갈아준다."""
    assert "ratio >= 20" in block
    assert "Math.max(cur / have, have / cur)" in block


def test_edit_mode_untouched(block: str) -> None:
    """수정 모드에서는 옛 시작가를 보존한다 (사장님 사상 v39)."""
    assert "editingStrategyId" in block
    assert "!editing &&" in block


def test_tells_the_user(block: str) -> None:
    """조용히 바꾸지 않는다 — 옛 값과 이유를 알린다."""
    assert "시작가를 ${symbol} 현재가로 갱신했습니다" in block
    assert "옛 값" in block


def test_empty_case_still_filled(block: str) -> None:
    """옛 동작(비어 있으면 채움)은 그대로."""
    assert "!startInp.value || Number(startInp.value) <= 0" in block


def test_claims_typed_value_for_current_symbol(block: str) -> None:
    """직접 입력한 값은 이 심볼 것으로 기록 → 다음 심볼 변경 때 갱신된다."""
    assert "_cmStartPriceSymbol = symbol;" in block


def test_crlf_preserved() -> None:
    raw = JS.read_bytes()
    assert b"\r\n" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n")
