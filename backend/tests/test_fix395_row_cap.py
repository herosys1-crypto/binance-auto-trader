"""🩹 Fix 395 — 「종료 숨김」을 끄면 화면이 멈추던 것 (2026-09-23).

사장님: "종료숨김 기능를 사용했는데 이런 페이지가 나오는데 문제를 해결해줘"
        (브라우저 「페이지가 응답할 때까지 기다리거나 페이지를 종료할 수 있습니다」 창)

원인: 목록 렌더가 `tbody.innerHTML = sorted.map(...)` 로 **필터 통과 행 전부**를 한 번에 그린다.
      사장님 화면은 전체 1,816건이고 행마다 배지·셀렉트·버튼이 여러 개라, 종료 숨김을 끄면
      수 MB HTML 을 한 번에 파싱·레이아웃하면서 메인 스레드가 수십 초 잠긴다.
      (진행 중만 보는 기본 상태는 49건이라 멈추지 않았다 = 그래서 지금까지 안 드러났다.)

해법: 한 번에 그리는 행을 200 으로 끊고(「Claude가 정함」), 나머지는 「+200 더 보기」·「전부 표시」
      버튼으로 늘린다. 토글할 때마다 상한을 되돌려 다시 멈추지 않게 한다.
      데이터·정렬·필터 규칙은 건드리지 않는다 (UI 층만).
"""
from __future__ import annotations

from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
JS = STATIC / "js" / "strategies-list.js"
HTML = STATIC / "index.html"


@pytest.fixture(scope="module")
def js() -> str:
    return JS.read_text(encoding="utf-8")


def test_row_limit_is_200(js: str) -> None:
    assert "const STRATEGY_ROW_LIMIT = 200;" in js
    assert "let _strategyRowLimit = STRATEGY_ROW_LIMIT;" in js


def test_render_uses_capped_slice(js: str) -> None:
    """렌더는 잘라낸 목록으로 한다 — 원본(sorted)을 그대로 그리면 다시 멈춘다."""
    assert "tbody.innerHTML = _rows.map(s => {" in js
    assert "tbody.innerHTML = sorted.map(s => {" not in js
    i_slice = js.index("const _rows = _totalRows > _strategyRowLimit")
    i_render = js.index("tbody.innerHTML = _rows.map")
    assert i_slice < i_render


def test_show_more_row_and_buttons(js: str) -> None:
    """나머지 건수를 알려 주고 늘릴 수 있다."""
    assert "_hiddenByCap > 0" in js
    assert "showMoreStrategies(STRATEGY_ROW_LIMIT)" in js or "showMoreStrategies(${STRATEGY_ROW_LIMIT})" in js
    assert "전부 표시" in js
    assert "function showMoreStrategies(step)" in js


def test_toggle_resets_the_cap(js: str) -> None:
    """토글 때마다 상한 복원 — 「전부 표시」 뒤에 토글해도 다시 멈추지 않는다."""
    fn = js[js.index("function onHideTerminatedChange()"):]
    fn = fn[:fn.index("}")]
    assert "_strategyRowLimit = STRATEGY_ROW_LIMIT" in fn
    assert "refreshStrategies()" in fn


def test_checkbox_calls_new_handler() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert 'id="hide-terminated" onchange="onHideTerminatedChange()"' in html
    assert 'id="hide-terminated" onchange="refreshStrategies()"' not in html


@pytest.mark.parametrize("path", [JS, HTML])
def test_crlf_preserved(path: Path) -> None:
    """프로젝트 규칙 8 — 이 파일들은 CRLF 다."""
    raw = path.read_bytes()
    assert b"\r\n" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n")
