"""Fix 471 — 일목 실험실 카드의 「🏁 검증 통과」 표시: 읽기 전용 유지 확인."""
import re
from pathlib import Path

JS = Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "ichikijun-lab-board.js"


def test_js_handles_promo():
    js = JS.read_text(encoding="utf-8")
    assert "promo" in js and "status" in js and "검증 통과" in js
    assert "검증 통과 후보 아직 없음" in js and "missing" in js
    assert "<th>관문</th>" in js
    for g in ("G1", "G7"):
        assert g in js
    assert "100% 확실한 전략은 없다" in js


def test_js_still_read_only():
    js = JS.read_text(encoding="utf-8")
    calls = re.findall(r"api\(\s*[`'\"]([^`'\"]+)", js)
    assert calls == ["/ichikijun-lab/board"]
    for bad in ("POST", "/orders", "<button"):
        assert bad not in js
