"""🛡️ Fix 242 — 진입 시점 지표 **복원**의 산수를 고정한다.

사장님 지시 (2026-08-31):
  "수동관리의 손실 차트와 보조지표를 분석해서 자동매매는 이것도 활용해서
   수익을 만들 전략을 만들어줘"

`entry_context` 가 12.1% 밖에 안 채워져 있어 과거 진입의 지표를 알 수 없다.
그래서 **진입 시각까지의 캔들을 거래소에서 다시 받아** 지표를 복원한다.

🚨 복원한 지표가 틀리면 그 위에서 만든 전략이 통째로 틀린다.
   선례: `obv_slope_pct` 에 단위 3가지가 섞여 학습 표본이 전멸한 적이 있다(Fix 228).
   그래서 부호와 방향을 여기서 고정한다.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "analyze_entry_patterns.py"
)


def _mod():
    spec = importlib.util.spec_from_file_location("_entry_patterns", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


UP = [100.0 + i for i in range(40)]
DOWN = [140.0 - i for i in range(40)]
FLAT = [100.0] * 40


def test_rsi_direction():
    """RSI 부호가 뒤집히면 LONG/SHORT 게이트가 정반대로 적용된다."""
    m = _mod()
    assert m._rsi(UP) > 90, "상승장 RSI 가 높지 않다"
    assert m._rsi(DOWN) < 10, "하락장 RSI 가 낮지 않다"


def test_rsi_needs_enough_bars():
    m = _mod()
    assert m._rsi([1.0, 2.0, 3.0]) is None


def test_bb_position_bounds():
    """볼밴 위치: 0=하단 / 0.5=중단 / 1=상단. 사장님 ① 「상단 밖」 판정의 근거."""
    m = _mod()
    up, dn = m._bb_pos(UP), m._bb_pos(DOWN)
    assert 0.5 < up <= 1.2, up
    assert -0.2 <= dn < 0.5, dn
    assert m._bb_pos(FLAT) is None, "변동이 0 이면 위치를 정의할 수 없다"


def test_macd_hist_positive_on_accelerating_rise():
    """가속 상승 = 히스토그램 양수. 이 부호가 정점 판정의 입력이다."""
    m = _mod()
    acc = [100.0] * 30 + [100.0 + i ** 1.6 for i in range(1, 25)]
    assert m._macd_hist(acc) > 0


def test_macd_hist_none_on_short_series():
    m = _mod()
    assert m._macd_hist([1.0, 2.0, 3.0]) is None


def test_ema_length_contract():
    """EMA 길이가 어긋나면 MACD 정렬이 밀려 조용히 틀린 값이 나온다."""
    m = _mod()
    assert len(m._ema(UP, 12)) == len(UP) - 12 + 1
    assert m._ema([1.0, 2.0], 12) == []


def test_retracement_is_wired_in():
    """🎯 사장님 사상 ⑤ 가 실제로 복원 대상에 들어 있는가."""
    m = _mod()
    keys = {k for k, _n, _note in m.KEYS}
    assert "retrace_4h" in keys, "되돌림 비율이 분석 대상에서 빠졌다"
    assert "obv_dir_4h" in keys, "OBV 방향(사장님 사상 ④)이 빠졌다"
    assert "bb_pos_4h" in keys, "4H 볼밴 위치(사장님 사상 ①)가 빠졌다"


def test_manual_auto_split_matches_quick_prefix():
    """수동/자동 구분 기준이 분석 도구와 같아야 두 리포트를 나란히 볼 수 있다."""
    src = _SCRIPT.read_text(encoding="utf-8")
    assert 'name.startswith("_quick_")' in src
