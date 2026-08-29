"""🚨 Fix 226 — 관찰 시점 지표를 남겨 「수치화」의 재료를 만든다.

사장님 verbatim (2026-08-30):
  "다시 상승하기 힘들다지 없다는건 아니야. 찾으면 너무 좋은데 많이 학습이 필요해.
   **초기에 상승하는 심볼들의 차트와 보조지표를 찾아서 학습해서 수치화** 해야해"

market_observation_worker 는 이미 4시간마다 **급등 50 / 급락 50** 을 저장하고
(사장님이 원하신 바로 그 기준), 1시간마다 1h/4h/24h **결과**를 채운다.
빠진 것은 **관찰 시점의 지표**뿐이었다 — 그래서 "어떤 지표 조합이 그 뒤 상승으로
이어졌나" 를 물어볼 수가 없었다.

    관찰 시점 지표  ×  그 뒤 결과  =  수치화의 근거

🚨 OBV 는 반드시 **비율**로 저장한다. 기존 obv_slope_pct 는 (끝-처음)/|처음| 형태라
   시작값이 0 근처면 폭발한다 — 실측 최대값 **2,249,160** 의 유력한 원인이다.
"""
from __future__ import annotations

from app.workers.market_observation_worker import _IND_TFS, _indicator_snapshot


class _FakeChartAnalyzer:
    """analyze_timeframe 를 대신한다 — 실제 반환 필드명과 같아야 한다."""

    payload: dict = {}
    calls: list = []

    @classmethod
    def analyze_timeframe(cls, bc, symbol, tf, limit=None):
        cls.calls.append((symbol, tf, limit))
        return cls.payload.get(tf)


def _series(n=40, base=100.0, step=1.0):
    return [base + step * i for i in range(n)]


def _payload(*, obv_up=True, macd_peak_then_drop=True):
    closes = _series()
    vols = [1000.0] * 40
    obv = [i * 1000.0 for i in range(40)] if obv_up else [(40 - i) * 1000.0 for i in range(40)]
    if macd_peak_then_drop:
        hist = [0.1] * 18 + [5.0, 3.0]          # 직전이 최고, 현재는 축소
    else:
        hist = [0.1] * 20
    return {
        "closes": closes, "volumes": vols, "obv": obv, "macd_hist": hist,
        "rsi_now": 68.0, "rsi_prev": 72.0,
        "cci_now": 150.0, "cci_prev": 210.0,
        "bb_up_last": 145.0, "bb_mid_last": 120.0, "bb_lo_last": 95.0,
    }


def _patch(monkeypatch, per_tf):
    _FakeChartAnalyzer.payload = per_tf
    _FakeChartAnalyzer.calls = []
    import app.services.chart_analyzer as ca

    monkeypatch.setattr(ca, "ChartAnalyzer", _FakeChartAnalyzer)


def test_both_timeframes_are_captured(monkeypatch):
    """4시간(확정된 흐름) + 15분(진입 타이밍) 둘 다 필요하다."""
    assert [tf for tf, _ in _IND_TFS] == ["15m", "4h"]
    _patch(monkeypatch, {"15m": _payload(), "4h": _payload()})
    snap = _indicator_snapshot(object(), "TESTUSDT")
    assert set(snap.keys()) == {"15m", "4h"}


def test_macd_peak_ratio_is_recorded(monkeypatch):
    """사장님이 물으신 「macd 막대 최고점 대비 조정 수치」."""
    _patch(monkeypatch, {"15m": _payload(), "4h": _payload()})
    d = _indicator_snapshot(object(), "TESTUSDT")["15m"]
    assert d["macd_hist_max20"] == 5.0
    assert d["macd_hist_prev"] == 5.0 and d["macd_hist"] == 3.0
    assert abs(d["macd_from_peak"] - 0.6) < 1e-9, "최고점의 60% 로 축소 = 0.6"


def test_obv_direction_is_bounded(monkeypatch):
    """🚨 OBV 는 -1~+1 로 묶여야 한다 — 2,249,160 같은 값이 다시 나오면 안 된다."""
    _patch(monkeypatch, {"15m": _payload(obv_up=True), "4h": _payload(obv_up=False)})
    snap = _indicator_snapshot(object(), "TESTUSDT")
    for tf in ("15m", "4h"):
        v = snap[tf]["obv_dir_20"]
        assert -1.0 <= v <= 1.0, f"{tf} obv_dir_20={v} 가 범위를 벗어났다"
    assert snap["15m"]["obv_dir_20"] > 0, "상승 OBV 가 양수가 아니다"
    assert snap["4h"]["obv_dir_20"] < 0, "하락 OBV 가 음수가 아니다"


def test_obv_would_explode_with_the_old_formula():
    """음성 대조군 (헌법 170) — 옛 산식이 실제로 폭발하는지 보여준다.

    이게 폭발하지 않으면 새 산식을 쓸 이유가 없다는 뜻이므로, 대조군으로 고정한다.
    """
    obv = [0.0001] + [i * 1000.0 for i in range(1, 20)]
    old = (obv[-1] - obv[0]) / abs(obv[0]) * 100.0     # 옛 방식
    assert old > 1_000_000, f"옛 산식이 폭발하지 않는다: {old}"


def test_band_position_is_normalized(monkeypatch):
    """밴드 내 위치 0=하단 / 0.5=중단 / 1=상단. 밖이면 범위를 넘는다."""
    _patch(monkeypatch, {"15m": _payload(), "4h": _payload()})
    d = _indicator_snapshot(object(), "TESTUSDT")["15m"]
    # close=139, lo=95, up=145 → (139-95)/(145-95) = 0.88
    assert abs(d["bb_pos"] - 0.88) < 1e-9


def test_failure_of_one_timeframe_does_not_kill_the_snapshot(monkeypatch):
    """한 시간대가 실패해도 관찰 저장 자체는 계속돼야 한다."""
    _patch(monkeypatch, {"15m": _payload(), "4h": None})
    snap = _indicator_snapshot(object(), "TESTUSDT")
    assert "15m" in snap and "4h" not in snap


def test_exception_is_swallowed(monkeypatch):
    """분석이 예외를 던져도 빈 dict 를 돌려줄 뿐 관찰을 막지 않는다."""
    class _Boom:
        @staticmethod
        def analyze_timeframe(*a, **k):
            raise RuntimeError("boom")

    import app.services.chart_analyzer as ca

    monkeypatch.setattr(ca, "ChartAnalyzer", _Boom)
    assert _indicator_snapshot(object(), "TESTUSDT") == {}
