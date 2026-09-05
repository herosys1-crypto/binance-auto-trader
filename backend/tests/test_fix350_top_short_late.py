"""⏰ Fix 350 — 정점 SHORT: 1h hist 가 이미 2봉 하락 중이면(정점 지남) 늦은 진입으로 보류.

실거래 7일: 1h 이미 하락 후 진입 66건 승률 9% vs 1h 상승 중 49건 29%.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app"


def test_배선_위치_Fix346_다음_생성_전():
    s = (ROOT / "workers" / "auto_short_at_top_worker.py").read_text(encoding="utf-8")
    i_346 = s.find("[Fix346] %s 국면 판정 오류")
    i_350 = s.find('get_bool("top_short_skip_if_1h_down", True)')
    i_cr = s.find('strategy_type_suffix="_SAJANGNIM_TOP"')
    assert 0 < i_346 < i_350 < i_cr
    assert '_hr350(bc, symbol, "SHORT", "1h", use_completed=True, min_bars=2)' in s, "1h 완성봉 2봉 연속"
    assert "if _down1h is True:" in s, "판정 불가(None)는 막지 않는다"


def test_1h_2봉_하락_판정은_check_hist_rising_min_bars_로():
    from app.services import trend_4h_gate as G
    c = [100.0] * 70
    for i in range(1, 9):
        c.append(c[-1] * (1 - 0.02 * i))            # 1h 가속 하락 = SHORT 내 편 = 이미 정점 지남
    rows = [[0, 0, 0, 0, str(x), "1"] for x in c] + [[0, 0, 0, 0, str(c[-1]), "1"]]

    class _BC:
        def get_klines(self, symbol, interval, limit):
            assert interval == "1h"
            return rows
    ok, d = G.check_hist_rising(_BC(), "X", "SHORT", "1h", use_completed=True, min_bars=2)
    assert ok is True, d
