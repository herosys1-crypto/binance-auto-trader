"""🗂 Fix 381 (2026-09-19 사장님) — 관제실 = 전략 한 줄씩 · 순서대로 · 누르면 펼침.

사장님: "자동매매 전략 모두 한눈에 관리할수 있게 정리해서 한줄로 순서를 정해서 나열하고
        선택하면 풀다운 메뉴로 볼수있게 정리해줘 자동매매 전략이 너무 많이 복잡해"

고정: ① 모든 줄이 순서표에 있다(새 전략이 빠지면 여기서 걸린다) ② 번호가 겹치지 않고 1부터 이어진다
      ③ 사장님 사상 순서가 맨 앞 ④ overview 가 번호 순으로 준다 ⑤ 화면이 한 줄 + 펼침으로 그린다
"""
from pathlib import Path

from app.services import auto_control as AC
from app.services import auto_control_state as S

APP = Path(__file__).resolve().parents[1] / "app"


def test_every_line_is_in_the_order():
    ids = [AC.line_id(p) for p in AC.panels()]
    order = AC.line_order()
    assert len(ids) == len(set(ids)), "줄 식별자가 겹친다"
    missing = [i for i in ids if i not in order]
    assert not missing, f"순서표(LINE_ORDER)에 없는 줄 — 새 전략이면 알맞은 묶음에 넣을 것: {missing}"
    extra = [i for i in order if i not in ids]
    assert not extra, f"화면에 없는 줄이 순서표에 남아 있다: {extra}"


def test_numbers_are_contiguous():
    nums = sorted(n for n, _s in AC.line_order().values())
    assert nums == list(range(1, len(nums) + 1))


def test_doctrine_first():
    assert [s for s, _ in AC.LINE_ORDER][:2] == ["① 사장님 핵심", "② 볼밴 계열"]
    first = AC.LINE_ORDER[0][1]
    assert first[:2] == ("top_short", "bottom_long"), "사장님 사상 ① 급등 정점 SHORT · ② 저점 LONG 이 맨 앞"


def test_overview_is_sorted_with_sections(monkeypatch):
    monkeypatch.setattr(S, "_rows", lambda db, keys: {})
    monkeypatch.setattr(S, "_family_counts", lambda db: ({}, {}, None))
    monkeypatch.setattr(S, "_shadow_counts", lambda: {})
    monkeypatch.setattr(S, "_kill_switches", lambda db: [])
    ov = S.build(None)
    orders = [p["order"] for p in ov["panels"]]
    assert orders == sorted(orders) and orders[0] == 1 and 999 not in orders
    assert ov["sections"][:6] == [s for s, _ in AC.LINE_ORDER]
    assert all(p["section"] in ov["sections"] for p in ov["panels"])
    assert ov["panels"][0]["id"] == "top_short"


def test_screen_is_one_line_with_dropdown():
    js = (APP / "static" / "js" / "auto-control.js").read_text(encoding="utf-8")
    html = (APP / "static" / "auto-control.html").read_text(encoding="utf-8")
    for token in ("function toggleItem(", "function openAll(", "p.order", "p.section === sec", "class=\"drop\"",
                  "localStorage.setItem(OPEN_KEY"):
        assert token in js, token
    assert "try {" in js.split("function saveOpen()")[1][:120], "저장소 접근은 try 로 감싼다"
    assert ".item.open .drop { display: block; }" in html
    # Fix 374 안전장치는 그대로
    for token in ("function isTurnOn(", "confirm(", "['on', '적용']", "['중단', '허용']"):
        assert token in js, token
