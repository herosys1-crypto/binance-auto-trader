"""Fix 466 — 예약 생성 「진입 신호」 선택 + 일목 실험실 카드 「적용 결과」 화면."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = STATIC / "js"

EXPECTED = {
    f"ichikijun:{iv}_{f}_{e}_{x}"
    for iv in ("1h", "4h", "1d") for f in ("src", "loose")
    for e in ("now", "pb") for x in ("r2", "r15", "r2kj")
}


def _select_html() -> str:
    m = re.search(r'<select id="cm-entry-signal".*?</select>', HTML, re.S)
    assert m, "#cm-entry-signal 이 없다"
    return m.group(0)


def test_entry_signal_select_has_36_variants_and_champion():
    sel = _select_html()
    vals = re.findall(r'<option value="([^"]*)"', sel)
    assert "" in vals and "ichikijun" in vals
    variants = [v for v in vals if v.startswith("ichikijun:")]
    assert len(variants) == 36 and set(variants) == EXPECTED


def _strip_comments(js: str) -> str:
    return "\n".join(l for l in js.splitlines() if not l.lstrip().startswith("//"))


def test_submit_paths_send_entry_signal_only_when_scheduled():
    for name in ("cm-submit.js", "multi-symbol.js"):
        js = _strip_comments((JS / name).read_text(encoding="utf-8"))
        assert "cm-entry-signal" in js, name
        # 값 읽기도, 본문 삽입도 scheduled 조건 안
        assert re.search(r"scheduled\s*\?\s*\(\(document\.getElementById\('cm-entry-signal'\)", js), name
        assert re.search(r"\.\.\.\(scheduled && _entrySig466 \? \{ entry_signal: _entrySig466 \} : \{\}\)", js), name
        assert len(re.findall(r"entry_signal", js)) == 1, f"{name}: entry_signal 이 조건 밖에도 있다"


def test_list_badge_for_ichikijun_signal():
    js = (JS / "helpers.js").read_text(encoding="utf-8")
    assert "startsWith('ichikijun')" in js and "🗾 일목" in js
    assert "ichikijunSignalBadge(s)" in js.split("function scheduledBadge")[1].split("function ")[0]


def test_lab_card_reads_applied():
    js = (JS / "ichikijun-lab-board.js").read_text(encoding="utf-8")
    assert "data.applied" in js and "ichikijun-lab-applied" in js
    assert "아직 일목 신호 예약 없음" in js
    assert 'id="ichikijun-lab-applied"' in HTML


def test_cache_busters_bumped():
    for f in ("helpers", "cm-submit", "multi-symbol", "ichikijun-lab-board"):
        assert re.search(rf'/static/js/{f}\.js\?v=fix466"', HTML), f


def test_fix469_entry_signal_sticky_with_buttons():
    """🗾 Fix 469 — 「진입 신호」 가 모달 맨 아래(스크롤해야 보임)가 아니라 버튼과 함께 아래에 고정된다."""
    import pathlib
    html = (pathlib.Path(__file__).resolve().parents[1] / "app/static/index.html").read_text(encoding="utf-8")
    bar = html.split('id="cm-action-bar"', 1)[1].split('id="cm-submit" onclick="submitCreate()"', 1)[0]
    assert "position:sticky" in html.split('id="cm-action-bar"', 1)[1][:120]
    assert 'id="cm-entry-signal"' in bar and 'id="cm-submit-scheduled"' in bar
    assert html.count('id="cm-entry-signal"') == 1
