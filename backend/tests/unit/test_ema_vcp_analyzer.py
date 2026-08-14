"""📐 EMA/VCP 멀티 타임프레임 분석 단위 테스트 (v137).

spec: docs/EMA_VCP_MTF_STRATEGY_SPEC.md

합성 캔들만 사용 = 네트워크 X!
"""
from __future__ import annotations

import math

from app.services.ema_vcp_analyzer import EMAVCPAnalyzer, to_learning_context


def kline(close: float, high: float | None = None, low: float | None = None,
          vol: float = 100.0) -> list:
    """Binance kline 형식 = [open_time, open, high, low, close, volume, close_time]."""
    high = close * 1.002 if high is None else high
    low = close * 0.998 if low is None else low
    return [0, close, high, low, close, vol, 0]


# ----------------------------------------------------------------------
# EMA
# ----------------------------------------------------------------------
def test_ema_series_길이와_시드():
    """EMA = 입력과 같은 길이, 앞부분 None, 시드 = SMA."""
    values = [float(i) for i in range(1, 11)]  # 1..10
    ema = EMAVCPAnalyzer.ema_series(values, 5)

    assert len(ema) == 10
    assert ema[:4] == [None] * 4
    assert ema[4] == 3.0  # (1+2+3+4+5)/5

    # 다음 값 = close*k + prev*(1-k), k = 2/6
    k = 2 / 6
    assert math.isclose(ema[5], 6 * k + 3.0 * (1 - k))


def test_ema_series_데이터_부족():
    assert EMAVCPAnalyzer.ema_series([1.0, 2.0], 5) == [None, None]
    assert EMAVCPAnalyzer.ema_series([], 5) == []


# ----------------------------------------------------------------------
# 4H = 나침반
# ----------------------------------------------------------------------
def _uptrend_4h(n: int = 80) -> list:
    return [kline(100 + i * 1.5) for i in range(n)]


def _downtrend_4h(n: int = 80) -> list:
    return [kline(200 - i * 1.5) for i in range(n)]


def test_4h_상승추세는_LONG만_허가():
    up = _uptrend_4h()
    long_r = EMAVCPAnalyzer.analyze_4h(up, "LONG")
    short_r = EMAVCPAnalyzer.analyze_4h(up, "SHORT")

    assert long_r["available"] is True
    assert long_r["direction"] == "UP"
    assert long_r["ok"] is True
    assert long_r["slope_pct"] > 0
    # 같은 차트에서 SHORT = 역방향 = 금지!
    assert short_r["ok"] is False


def test_4h_하락추세는_SHORT만_허가():
    down = _downtrend_4h()
    assert EMAVCPAnalyzer.analyze_4h(down, "SHORT")["ok"] is True
    assert EMAVCPAnalyzer.analyze_4h(down, "LONG")["ok"] is False


def test_4h_횡보는_양방향_모두_금지():
    flat = [kline(100 + (0.3 if i % 2 else -0.3)) for i in range(80)]
    r = EMAVCPAnalyzer.analyze_4h(flat, "LONG")
    assert r["direction"] == "FLAT"
    assert r["ok"] is False


def test_4h_캔들_부족은_판정불가():
    r = EMAVCPAnalyzer.analyze_4h([kline(100)] * 10, "LONG")
    assert r["available"] is False
    assert r["ok"] is False
    assert "부족" in r["note"]


# ----------------------------------------------------------------------
# 1H = 작전 지도 (VCP)
# ----------------------------------------------------------------------
# 수축 구간 시작 중심가 = 상승 마지막 종가 + 여유!
VCP_CENTER = 100 + 60 * 0.45 + 1.5  # = 128.5


def _vcp_setup_1h() -> list:
    """상승 톱니(= 파동 여러 번) → 변동성 수축 + 거래량 고갈 = 교과서 VCP."""
    bars: list = []

    # 1) 상승 톱니 61봉 = 조정 때 EMA20 아래로 이탈 → 재돌파 반복!
    #    (= 「첫 반등 무시」 필터를 통과하는 2번째 이상 파동!)
    for i in range(61):
        base = 100 + i * 0.45
        close = base - 7.0 if i % 7 in (5, 6) else base
        bars.append(kline(close, close + 1.0, close - 1.0, vol=100))

    # 2) 수축 구간 18봉 = 변동폭 2.0 → 1.2 → 0.5, 거래량 100 → 70 → 45
    for i in range(18):
        center = VCP_CENTER + i * 0.15
        amp, vol = [(2.0, 100.0), (1.2, 70.0), (0.5, 45.0)][i // 6]
        close = center + (amp * 0.2 if i % 2 else -amp * 0.2)
        bars.append(kline(close, center + amp, center - amp, vol=vol))

    # 3) 진행 중 봉!
    bars.append(kline(VCP_CENTER + 2.0, VCP_CENTER + 2.4, VCP_CENTER + 1.6, vol=30))
    return bars


def test_1h_vcp_셋업_완성():
    r = EMAVCPAnalyzer.analyze_1h(_vcp_setup_1h(), "LONG")

    assert r["available"] is True
    assert r["aligned"] is True, "정배열 10>20>50 이어야 함"
    assert r["vcp_contracting"] is True, f"수축 인정 실패: {r['vcp_ranges']}"
    assert r["volume_dry"] is True, f"거래량 고갈 실패: {r['vol_ratio']}"
    assert r["rally_count"] >= 2, "톱니 상승 = 파동 2회 이상이어야 함"
    assert r["first_rally_only"] is False
    assert r["setup_complete"] is True
    # 변동폭이 실제로 계단식 축소!
    assert r["vcp_ranges"][0] > r["vcp_ranges"][1] > r["vcp_ranges"][2]
    # 돌파선 = 수축 구간 고점!
    assert r["breakout_level"] >= VCP_CENTER + 2.0


def test_1h_첫반등만이면_셋업_미완성():
    """단조 상승 = EMA20 교차 1회 = 「첫 반등」 = 영상 원칙상 관망!"""
    bars = [kline(100 + i * 0.8, 100 + i * 0.8 + 1, 100 + i * 0.8 - 1) for i in range(61)]
    for i in range(18):
        center = 148 + i * 0.15
        amp, vol = [(2.0, 100.0), (1.2, 70.0), (0.5, 45.0)][i // 6]
        bars.append(kline(center, center + amp, center - amp, vol=vol))
    bars.append(kline(150.0))

    r = EMAVCPAnalyzer.analyze_1h(bars, "LONG")
    assert r["rally_count"] <= 1
    assert r["first_rally_only"] is True
    assert r["setup_complete"] is False, "첫 반등만이면 셋업 완성 금지!"


def test_1h_거래량_안마르면_셋업_미완성():
    """수축은 됐는데 거래량이 안 줄면 = 매도세 미고갈 = 셋업 X."""
    bars = _vcp_setup_1h()
    for b in bars[61:79]:
        b[5] = 100.0  # 거래량 그대로!
    r = EMAVCPAnalyzer.analyze_1h(bars, "LONG")

    assert r["vcp_contracting"] is True
    assert r["volume_dry"] is False
    assert r["setup_complete"] is False


def test_1h_캔들_부족은_판정불가():
    r = EMAVCPAnalyzer.analyze_1h([kline(100)] * 30, "LONG")
    assert r["available"] is False
    assert r["setup_complete"] is False


# ----------------------------------------------------------------------
# 15m = 방아쇠
# ----------------------------------------------------------------------
def _breakout_15m(level_break_close: float = 102.0, spike_vol: float = 300.0) -> list:
    bars = [kline(100 + (0.2 if i % 2 else -0.2), 100.5, 99.5, vol=100) for i in range(40)]
    # 마지막 완료봉 = 돌파 + 거래량 폭발!
    bars.append(kline(level_break_close, level_break_close + 0.3, 99.8, vol=spike_vol))
    # 진행 중 봉!
    bars.append(kline(level_break_close + 0.2, level_break_close + 0.5,
                      level_break_close - 0.2, vol=60))
    return bars


def test_15m_돌파_거래량폭발_감지():
    r = EMAVCPAnalyzer.analyze_15m(_breakout_15m(), "LONG", breakout_level=101.0)

    assert r["available"] is True
    assert r["breakout_closed"] is True, "직전 완료봉 종가가 돌파선 위!"
    assert r["breakout_intrabar"] is True
    assert r["volume_spike"] is True
    assert r["vol_spike_ratio"] >= 1.5
    # 손절 = 직전 스윙 로우!
    assert r["stop_loss"] <= 100
    assert r["risk_pct"] > 0


def test_15m_거래량_없는_돌파는_휩쏘_주의():
    r = EMAVCPAnalyzer.analyze_15m(_breakout_15m(spike_vol=90.0), "LONG", breakout_level=101.0)
    assert r["breakout_closed"] is True
    assert r["volume_spike"] is False, "거래량 없는 돌파 = 폭발 아님!"


def test_15m_돌파선_미달이면_대기():
    r = EMAVCPAnalyzer.analyze_15m(_breakout_15m(), "LONG", breakout_level=110.0)
    assert r["breakout_closed"] is False
    assert r["breakout_intrabar"] is False


def test_15m_SHORT은_하향돌파_스윙하이_손절():
    bars = [kline(100 + (0.2 if i % 2 else -0.2), 100.5, 99.5, vol=100) for i in range(40)]
    bars.append(kline(98.0, 100.2, 97.8, vol=300))
    bars.append(kline(97.8, 98.0, 97.5, vol=60))

    r = EMAVCPAnalyzer.analyze_15m(bars, "SHORT", breakout_level=99.0)
    assert r["breakout_closed"] is True
    assert r["volume_spike"] is True
    assert r["stop_loss"] >= 100, "SHORT 손절 = 스윙 하이!"


# ----------------------------------------------------------------------
# 종합 = 등급
# ----------------------------------------------------------------------
def _combine(side: str = "LONG", k4=None, k1=None, k15=None, level=101.0):
    r4 = EMAVCPAnalyzer.analyze_4h(k4 if k4 else _uptrend_4h(), side)
    r1 = EMAVCPAnalyzer.analyze_1h(k1 if k1 else _vcp_setup_1h(), side)
    r15 = EMAVCPAnalyzer.analyze_15m(
        k15 if k15 else _breakout_15m(), side,
        breakout_level=level if level is not None else r1.get("breakout_level"),
    )
    return EMAVCPAnalyzer.combine("TESTUSDT", side, r4, r1, r15)


def test_등급A_모든조건_충족():
    r = _combine()
    assert r["available"] is True
    assert r["grade"] == "A"
    assert r["stage"] == "TRIGGER"
    assert r["score"] >= 80
    assert r["levels"]["stop_loss"] is not None
    assert r["levels"]["exit_full_1h_ema20"] is not None


def test_등급B_셋업완성_돌파대기():
    """돌파선을 아득히 위로 두면 = 돌파 X = B등급 (셋업 완성, 대기!)"""
    r = _combine(level=999.0)
    assert r["grade"] == "B"
    assert r["stage"] == "SETUP"


def test_등급D_4H_역방향이면_진입금지():
    """4H 상승인데 SHORT = 역방향 = 무조건 D (다른 조건 무관!)"""
    r = _combine(side="SHORT")
    assert r["grade"] == "D"
    assert r["stage"] == "AVOID"
    assert any("금지" in s for s in r["signals"])


def test_등급C_추세만_OK():
    """4H OK, 1H 셋업 미완성 (첫 반등만) = C = 관망!"""
    bars = [kline(100 + i * 0.8, 100 + i * 0.8 + 1, 100 + i * 0.8 - 1) for i in range(79)]
    bars.append(kline(163.0))
    r = _combine(k1=bars)
    assert r["grade"] == "C"
    assert r["stage"] == "WATCH"


def test_데이터_부족이면_판정불가_예외없음():
    r = EMAVCPAnalyzer.combine(
        "TESTUSDT", "LONG",
        EMAVCPAnalyzer.analyze_4h([], "LONG"),
        EMAVCPAnalyzer.analyze_1h([], "LONG"),
        EMAVCPAnalyzer.analyze_15m([], "LONG", None),
    )
    assert r["available"] is False
    assert r["grade"] == "D"
    assert r["stage"] == "UNKNOWN"


def test_analyze_클라이언트_없으면_failsafe():
    """네트워크 실패해도 = 예외 X, available=False (신호로 새면 안 됨!)"""
    r = EMAVCPAnalyzer(None).analyze("TESTUSDT", "LONG")
    assert r["available"] is False
    assert r["grade"] == "D"
    assert "error" in r


def test_analyze_캔들_직접주입():
    r = EMAVCPAnalyzer(None).analyze(
        "testusdt", "long",
        klines_4h=_uptrend_4h(),
        klines_1h=_vcp_setup_1h(),
        klines_15m=_breakout_15m(),
    )
    assert r["symbol"] == "TESTUSDT"
    assert r["side"] == "LONG"
    assert r["available"] is True
    assert r["grade"] in ("A", "B")


# ----------------------------------------------------------------------
# 학습 저장용 압축
# ----------------------------------------------------------------------
def test_학습_컨텍스트_압축():
    full = _combine()
    ctx = to_learning_context(full)

    assert ctx["grade"] == "A"
    assert ctx["available"] is True
    assert ctx["trend_4h"] == "UP"
    assert ctx["trend_ok"] is True
    assert ctx["vcp_contracting"] is True
    assert ctx["volume_spike"] is True
    assert "levels" in ctx
    # 압축 = 무거운 tf_* 원본은 빠져야 함!
    assert "tf_1h" not in ctx
    assert "signals" not in ctx


def test_학습_컨텍스트_None_안전():
    assert to_learning_context(None) == {}
    assert to_learning_context({}) == {}
