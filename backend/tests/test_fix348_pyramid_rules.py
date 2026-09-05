"""🎯 Fix 348 — 피라미딩 개선 (정지 아님): 「유리 이동 ≥3% + 15m hist 3봉 가속 + SHORT 만」.

사장님 2026-09-04: "정지가 아니라 개선안을 찾아줘"
실측(7일 194건 재시뮬): 정점 SHORT 추가는 이동≥3%+3봉 가속에서만 양수(+10.4), 저점 LONG 은 전 조건 음수.
"""
from pathlib import Path

from app.services import trend_4h_gate as G
from app.workers import success_pyramiding_worker as W

ROOT = Path(__file__).resolve().parents[1] / "app"


class _DB:
    def __init__(self, **kv):
        self._kv = kv

    def get(self, _model, key):
        v = self._kv.get(key)
        return None if v is None else type("R", (), {"value": v})()


def _bc_from(closes):
    rows = [[0, 0, 0, 0, str(c), "1"] for c in closes] + [[0, 0, 0, 0, str(closes[-1]), "1"]]   # 마지막 = 진행중 봉

    class _BC:
        def get_klines(self, symbol, interval, limit):
            return rows
    return _BC()


def _flat_then_surge(n_flat=70, n_surge=8, step=0.02):
    c = [100.0] * n_flat
    for i in range(1, n_surge + 1):
        c.append(c[-1] * (1 + step * i))
    return c


def test_min_bars_3_은_가속만_통과():
    c = _flat_then_surge()
    ok1, _ = G.check_hist_rising(_bc_from(c), "X", "LONG", "15m", use_completed=True, min_bars=1)
    ok3, d3 = G.check_hist_rising(_bc_from(c), "X", "LONG", "15m", use_completed=True, min_bars=3)
    assert ok1 is True and ok3 is True, d3
    # 급등 뒤 3봉 되돌림 → hist 가 꺾인다 = 3봉 가속 실패 (EMA 지연 때문에 1봉 뒤에는 아직 오를 수 있다)
    c2 = c + [c[-1] * 0.97, c[-1] * 0.94, c[-1] * 0.91]
    ok3b, d3b = G.check_hist_rising(_bc_from(c2), "X", "LONG", "15m", use_completed=True, min_bars=3)
    assert ok3b is False, d3b


def test_min_bars_는_SHORT_대칭():
    c = [100.0] * 70
    for i in range(1, 9):
        c.append(c[-1] * (1 - 0.02 * i))       # 가속 하락 = SHORT 내 편
    ok, d = G.check_hist_rising(_bc_from(c), "X", "SHORT", "15m", use_completed=True, min_bars=3)
    assert ok is True, d
    okL, _ = G.check_hist_rising(_bc_from(c), "X", "LONG", "15m", use_completed=True, min_bars=3)
    assert okL is False


def test_피라미딩_게이트가_15m_3봉_가속을_쓴다(monkeypatch):
    calls = []

    def fake(bc, symbol, side, tf, *, use_completed=False, min_bars=1):
        calls.append((tf, use_completed, min_bars))
        return True, {"tf": tf}
    monkeypatch.setattr(G, "check_hist_rising", fake)
    ok, why, det = G.check_pyramid_trend(None, "X", "SHORT", db=_DB())
    assert ok is True and calls[0] == ("15m", True, 3) and det["accel_bars"] == 3
    calls.clear()
    G.check_pyramid_trend(None, "X", "SHORT", db=_DB(pyramid_hist_accel_bars="1"))
    assert calls[0] == ("15m", True, 1), "설정으로 옛 1봉 미분 복귀"


def test_최소_이동_기본_3_설정_가능():
    assert W._min_move_pct(_DB()) == 3.0
    assert W._min_move_pct(_DB(pyramid_min_move_pct="5")) == 5.0
    assert W._min_move_pct(_DB(pyramid_min_move_pct="999")) == 3.0, "범위 밖은 기본"


def test_허용_방향_기본_SHORT():
    assert W._allowed_sides(_DB()) == {"SHORT"}
    assert W._allowed_sides(_DB(pyramid_sides="LONG,SHORT")) == {"LONG", "SHORT"}
    assert W._allowed_sides(_DB(pyramid_sides="garbage")) == {"SHORT"}


def test_워커_배선_순서_ROI_다음에_방향_이동():
    s = (ROOT / "workers" / "success_pyramiding_worker.py").read_text(encoding="utf-8")
    i_roi = s.find('_bump("roi_below_trigger")')
    i_side = s.find('_bump("side_not_allowed")')
    i_move = s.find('_bump("move_below_min")')
    i_ind = s.find('_bump("indicator_not_rising")')
    assert 0 < i_roi < i_side < i_move < i_ind, "ROI → 방향 → 이동폭 → 지표 순서"
    assert "if price_pct < _min_move:" in s


def test_실측_근거가_남아_있다():
    s = (ROOT / "workers" / "success_pyramiding_worker.py").read_text(encoding="utf-8")
    for token in ("+10.4", "−205.0", "정지가 아니라 개선안"):
        assert token in s, token
