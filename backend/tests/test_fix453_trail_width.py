"""📏 Fix 453 — 트레일링 되돌림 폭 변형 (3%p · 8%p) 가상 기록 (사장님 10/14 「2번 진행해줘」)."""
from app.services import paper_trading as PT


def _bar(ts, o, h, l, c):
    return [ts, o, h, l, c, 1000.0]


def test_definitions():
    assert PT.EXIT_VARIANTS["live_trail3"] == {"trail_retrace": 3.0}
    assert PT.EXIT_VARIANTS["live_trail8"] == {"trail_retrace": 8.0}
    assert PT.TRAIL_RETRACE == 5.0 and PT.VERSION == 2


def test_width_changes_exit_point():
    # TP1(107.5) 뒤 최고 ROI +20(110) → 되돌림: 3%p 는 ROI +17(108.5) 에서, 5%p 는 +15(107.5), 8%p 는 +12(106)
    bars = [_bar(0, 100, 110, 100, 109), _bar(1, 109, 109, 107, 107.2), _bar(2, 107, 107, 105.5, 106)]
    r = lambda **kw: PT.run_live_like("LONG", 100.0, bars, tp1_pct=15.0, variants=(), **kw)  # noqa: E731
    t3, t5, t8 = r(trail_retrace=3.0), r(), r(trail_retrace=8.0)
    assert (t3["hit"], t3["exit_bar"]) == ("TRAIL", 1)
    assert (t5["hit"], t5["exit_bar"]) == ("TRAIL", 1)
    assert (t8["hit"], t8["exit_bar"]) == ("TRAIL", 2)
    # 실현: 25% × 15 + 75% × 되돌림 지점
    assert t3["roi"] == round(0.25 * 15 + 0.75 * 17, 4)
    assert t5["roi"] == round(0.25 * 15 + 0.75 * 15, 4)
    assert t8["roi"] == round(0.25 * 15 + 0.75 * 12, 4)
    assert r(trail_retrace=5.0) == t5                    # 기본값과 같다 = live 엔진 불변
