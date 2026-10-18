"""Fix 465 — 일목 기준선 실험실 카드: 화면 연결 + 읽기 전용 보장."""
import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
JS = APP / "static" / "js" / "ichikijun-lab-board.js"


def test_index_loads_lab_script_and_card():
    html = (APP / "static" / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<script src="/static/js/ichikijun-lab-board\.js\?v=[^"]+"', html)
    assert 'id="ichikijun-lab-card"' in html


def test_lab_js_reads_board_only():
    js = JS.read_text(encoding="utf-8")
    assert "/ichikijun-lab/board" in js
    assert "document.hidden" in js and "600000" in js
    # 주문·전략 시작 계열 API 호출 금지 (읽기 전용)
    calls = re.findall(r"api\(\s*[`'\"]([^`'\"]+)", js)
    assert calls == ["/ichikijun-lab/board"]
    for bad in ("/orders", "/strategies", "method: 'POST'", 'method: "POST"', "<button"):
        assert bad not in js
