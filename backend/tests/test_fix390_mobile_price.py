"""🩹 Fix 390 — 모바일에서 「심볼 선택 → 현재가」가 안 나오던 것 (2026-09-23).

사장님: "모바일에서 심볼을 선택했는데 현재가가 나오지 않아 데스크탑에서는 문제없는데"

운영 로그 실측(3시간, `market/ticker24h`·`klines`, testnet=false):
    200 = 126 · **503 = 70** · **502 = 42**
  · 502 는 전부 타이핑 중간의 부분 심볼 (`symbol=M`, `MINA`, `BROCCOL`, `NIL` …).
    모바일 자동완성은 고르는 순간 input/change 가 안 튀는 경우가 있어(iOS datalist,
    v92 에서 이미 겪음) 화면이 그 **실패 상태로 굳는다**. 데스크탑은 change 가 떠서
    전체 심볼로 다시 받아오므로 정상으로 보였다 = 기기 차이의 정체.
  · 503 은 Binance IP 차단(418) 구간(Fix 116) — 이때는 두 기기 모두 안 나온다.

세 가지 방어를 화면 코드에 고정한다 (UI 층만 — 시세 라우터·매매 판정 무변경):
  ① 완성되지 않은 심볼은 아예 보내지 않는다 (datalist 목록 대조).
  ② 값이 바뀌었는데 이벤트가 안 온 경우를 0.8초 주기로 따라잡는다 (모달 열려 있을 때만).
  ③ 503 은 남은 시간을 적고 자동 재시도한다.
추가: 계정 라디오를 못 읽을 때의 기본값을 testnet → **mainnet** 으로 바꿨다
      (운영은 mainnet 이고, testnet 으로 나가면 502 가 된다).
"""
from __future__ import annotations

from pathlib import Path

import pytest

JS_DIR = Path(__file__).resolve().parent.parent / "app" / "static" / "js"
MARKET = JS_DIR / "cm-market-info.js"
LOADERS = JS_DIR / "cm-loaders.js"


@pytest.fixture(scope="module")
def market() -> str:
    return MARKET.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def loaders() -> str:
    return LOADERS.read_text(encoding="utf-8")


def test_partial_symbol_is_not_requested(market: str) -> None:
    """① 부분 심볼은 fetch 앞에서 막힌다 (502 + 실패 표시 방지)."""
    assert "function _cmSymbolLooksComplete(sym)" in market
    body = market[market.index("async function loadCmMarketInfo()"):]
    guard = body.index("_cmSymbolLooksComplete(symbol)")
    first_fetch = body.index("market/ticker24h")
    assert guard < first_fetch, "심볼 완성 검사가 시세 요청보다 앞에 있어야 한다"


def test_symbol_checked_against_datalist(market: str) -> None:
    """목록이 로딩돼 있으면 목록에 있는 심볼만 보낸다."""
    fn = market[market.index("function _cmSymbolLooksComplete"):market.index("async function loadCmMarketInfo")]
    assert "cm-symbol-list" in fn
    assert "return false" in fn, "목록에 없으면 보내지 않는다"
    assert "USDT" in fn, "목록 로딩 전에는 접미사로 판단한다"


def test_mainnet_is_the_default(market: str) -> None:
    """계정 라디오를 못 읽으면 mainnet (testnet 이면 502 가 된다)."""
    line = next(ln for ln in market.splitlines() if "const isTestnet" in ln)
    assert line.rstrip().endswith(": false;"), line


def test_ban_503_retries_itself(market: str) -> None:
    """③ 차단(503) 이면 남은 시간을 적고 자동 재시도한다."""
    assert "조회 잠시 불가" in market
    assert "_cmBanRetryTimer = setTimeout(() => loadCmMarketInfo()" in market


def test_value_watcher_only_while_modal_open(loaders: str) -> None:
    """② 이벤트가 안 와도 값 변화를 따라잡되, 모달이 닫혀 있으면 아무 것도 안 한다."""
    blk = loaders[loaders.index("symEl.addEventListener('input', trigger);"):]
    blk = blk[:blk.index("symEl.dataset.bound")]
    assert "setInterval(" in blk
    assert "create-modal" in blk
    assert "classList.contains('hidden')" in blk
    assert "symEl.addEventListener('blur', trigger);" in blk


@pytest.mark.parametrize("path", [MARKET, LOADERS])
def test_crlf_preserved(path: Path) -> None:
    """프로젝트 규칙 8 — 이 파일들은 CRLF 다."""
    raw = path.read_bytes()
    assert b"\r\n" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n")
