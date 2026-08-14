"""🔺 15m 천장 + 볼밴 중단 분석기 단위 테스트 (v140).

spec: docs/BB_TOP_15M_STRATEGY_SPEC.md
합성 캔들만 사용 = 네트워크 X!
"""
from __future__ import annotations

import math

from app.services.bb_top_analyzer import BBTopAnalyzer, to_learning_context


def kline(close: float, high: float | None = None, low: float | None = None,
          vol: float = 100.0, open_: float | None = None) -> list:
    o = close if open_ is None else open_
    h = max(o, close) * 1.002 if high is None else high
    l = min(o, close) * 0.998 if low is None else low
    return [0, o, h, l, close, vol, 0]


def _flat(n: int = 120, price: float = 100.0) -> list:
    """횡보 = 신호 없는 배경.

    ⚠️ 꼬리가 밴드보다 크면 BB 터치로 잡히므로,
       변동폭(±0.5)은 넉넉하게 / 꼬리는 아주 짧게 만듭니다.
    """
    bars = []
    for i in range(n):
        c = price + (0.5 if i % 2 else -0.5)
        bars.append(kline(c, high=c + 0.01, low=c - 0.1, vol=100))
    return bars


def _bearish_div(n_base: int = 140) -> list:
    """가격은 신고가 / RSI·MACD·OBV 는 못 따라옴 = 약세 다이버전스 + BB 상단 터치.

    1차 고점을 강하게 만들고(대량 거래량 상승),
    2차 고점은 더 높지만 힘없이(작은 거래량, 긴 윗꼬리) 만듭니다.
    """
    bars: list = []
    p = 100.0
    # 0) 완만한 상승 배경
    for i in range(n_base):
        p += 0.05
        bars.append(kline(p, vol=100))
    # 1) 1차 급등 = 강한 거래량 (OBV/RSI/MACD 크게 상승)
    for i in range(10):
        prev = p
        p += 1.6
        bars.append(kline(p, high=p + 0.2, low=prev, vol=900))
    peak1 = p
    # 2) 깊은 조정 = 대량 하락 거래량 (OBV 크게 깎임)
    for i in range(12):
        prev = p
        p -= 1.15
        bars.append(kline(p, high=prev, low=p - 0.2, vol=950))
    # 3) 2차 상승 = 1차 고점보다 살짝 높지만 힘없음 (작은 거래량)
    for i in range(8):
        prev = p
        p += 1.15
        bars.append(kline(p, high=p + 0.1, low=prev, vol=90))
    # 4) 마지막 봉 = 신고가 + 긴 윗꼬리 (BB 상단 관통)
    top = max(peak1 * 1.004, p + 2.5)
    bars.append(kline(p - 0.4, open_=p - 0.5, high=top, low=p - 0.9, vol=120))
    return bars


# ----------------------------------------------------------------------
# 지표 정확성
# ----------------------------------------------------------------------
def test_볼린저밴드_계산():
    closes = [10.0] * 25
    mid, up, lo = BBTopAnalyzer.bollinger(closes)
    assert mid[-1] == 10.0
    assert up[-1] == 10.0 and lo[-1] == 10.0, "변동 없으면 밴드 폭 0!"
    assert mid[:19] == [None] * 19, "기간 미달 구간은 None!"


def test_볼린저밴드_폭():
    closes = [10.0 if i % 2 else 12.0 for i in range(40)]
    mid, up, lo = BBTopAnalyzer.bollinger(closes)
    assert up[-1] > mid[-1] > lo[-1]
    assert math.isclose(mid[-1], 11.0, abs_tol=0.01)


def test_RSI_상승일변도는_100():
    closes = [float(100 + i) for i in range(40)]
    r = BBTopAnalyzer.rsi(closes)
    assert r[-1] == 100.0
    r2 = BBTopAnalyzer.rsi([float(100 - i) for i in range(40)])
    assert r2[-1] == 0.0


def test_MACD_히스토그램_길이():
    closes = [100 + i * 0.5 for i in range(80)]
    h = BBTopAnalyzer.macd_hist(closes)
    assert len(h) == len(closes)
    assert h[-1] is not None
    assert h[10] is None, "초기 구간은 None!"


def test_OBV_방향():
    closes = [100, 101, 102, 101, 103]
    vols = [10, 20, 30, 40, 50]
    o = BBTopAnalyzer.obv(closes, vols)
    assert o == [0, 20, 50, 10, 60]


# ----------------------------------------------------------------------
# 천장 탐지
# ----------------------------------------------------------------------
def test_횡보에서는_신호없음():
    r = BBTopAnalyzer.analyze_15m(_flat(150), "SHORT")
    assert r["available"] is True
    assert r["div_count"] == 0
    assert r["bb_touch"] is False


def test_약세_다이버전스_탐지():
    r = BBTopAnalyzer.analyze_15m(_bearish_div(), "SHORT")
    assert r["available"] is True
    assert r["price_extreme"] is True, "가격이 직전 고점을 넘어야 함!"
    assert r["div_count"] >= 2, f"다이버전스 2개 이상이어야 함: {r}"
    assert r["bb_touch"] is True, "BB 상단 고가 터치!"
    assert r["wick"] is True, "긴 윗꼬리!"


def test_캔들_부족은_판정불가():
    r = BBTopAnalyzer.analyze_15m([kline(100)] * 30, "SHORT")
    assert r["available"] is False
    assert "부족" in r["note"]


def test_BB터치는_고가기준_종가아님():
    """실측상 「고가 터치」가 「종가 돌파」보다 정확 (13.8% vs 12.5%)."""
    bars = _flat(150)
    # 마지막 봉: 고가만 밴드 위로, 종가는 안쪽
    bars[-1] = kline(100.0, high=200.0, low=99.0, vol=100)
    r = BBTopAnalyzer.analyze_15m(bars, "SHORT")
    assert r["bb_touch"] is True, "고가가 상단을 넘으면 터치 인정!"
    assert r["pct_b"] < 1.0, "종가는 밴드 안 = %B < 1"


# ----------------------------------------------------------------------
# 볼밴 중단
# ----------------------------------------------------------------------
def test_BB중단_위치판정():
    r15 = BBTopAnalyzer.analyze_15m(_flat(150), "SHORT")
    st = BBTopAnalyzer.bb_mid_state(r15, "SHORT")
    assert st["available"] is True
    assert st["position"] in ("AT_MID", "ABOVE_MID", "BELOW_MID")
    assert st["target_pct"] is not None


def test_BB중단_먼_경우():
    r15 = BBTopAnalyzer.analyze_15m(_bearish_div(), "SHORT")
    st = BBTopAnalyzer.bb_mid_state(r15, "SHORT")
    assert st["position"] == "ABOVE_MID", "급등 후 = 중단 위!"
    assert st["target_pct"] > 0.5


def test_BB중단_판정불가_안전():
    st = BBTopAnalyzer.bb_mid_state({"available": False}, "SHORT")
    assert st["available"] is False


# ----------------------------------------------------------------------
# 등급 / 종합
# ----------------------------------------------------------------------
def _combine(klines, side="SHORT", k1=None, k4=None):
    r15 = BBTopAnalyzer.analyze_15m(klines, side)
    return BBTopAnalyzer.combine(
        "TESTUSDT", side, r15,
        BBTopAnalyzer.bb_mid_state(r15, side),
        BBTopAnalyzer.htf_trend(k1 or []), BBTopAnalyzer.htf_trend(k4 or []),
    )


def test_등급_다이버전스_BB터치면_A이상():
    r = _combine(_bearish_div())
    assert r["available"] is True
    assert r["grade"] in ("S", "A"), f"다이버전스+BB터치 = S/A: {r['grade']}"
    assert r["stage"] == "TRIGGER"
    assert r["score"] >= 60


def test_등급D_신호없음():
    r = _combine(_flat(150))
    assert r["grade"] == "D"
    assert r["stage"] == "NONE"
    assert r["score"] == 0


def test_레벨_BB중단이_1차목표():
    r = _combine(_bearish_div())
    lv = r["levels"]
    assert lv["bb_mid"] is not None
    assert lv["bb_upper"] > lv["bb_mid"] > lv["bb_lower"]
    assert lv["expected_bars_to_mid"] == BBTopAnalyzer.MID_MEDIAN_BARS
    assert lv["tp1_target_pct"] is not None


def test_RSI과매수는_점수에_반영안됨():
    """실측: RSI≥70 조건을 더하면 적중률 32%→22% 하락 → 점수 제외!"""
    r = _combine(_bearish_div())
    # 점수 = 다이버전스 + BB터치 + 꼬리 + 보조 만으로 구성
    t15 = r["tf_15m"]
    expected = (
        (BBTopAnalyzer.W_DIV_RSI if t15["div_rsi"] else 0)
        + (BBTopAnalyzer.W_DIV_OBV if t15["div_obv"] else 0)
        + (BBTopAnalyzer.W_DIV_MACD if t15["div_macd"] else 0)
        + (BBTopAnalyzer.W_BB_TOUCH if t15["bb_touch"] else 0)
        + (BBTopAnalyzer.W_WICK if t15["wick"] else 0)
    )
    assert r["score"] == min(expected, 100), "RSI 임계값이 점수에 섞이면 안 됨!"


def test_상위추세는_거부권_없음():
    """1H/4H가 반대여도 등급이 D로 떨어지면 안 됨 (사장님: 보조 역할!)."""
    up_htf = [kline(100 + i * 0.8) for i in range(80)]   # 강한 상승 = 천장과 반대
    r = _combine(_bearish_div(), k1=up_htf, k4=up_htf)
    assert r["grade"] in ("S", "A"), "상위 추세가 반대여도 15m 신호가 유지돼야 함!"
    assert any("거부권 없음" in s for s in r["signals"])


def test_상위추세_일치시_가산():
    down_htf = [kline(200 - i * 0.8) for i in range(80)]
    r_with = _combine(_bearish_div(), k1=down_htf, k4=down_htf)
    r_without = _combine(_bearish_div())
    assert r_with["score"] >= r_without["score"], "추세 일치 = 보조 가산!"


def test_analyze_failsafe():
    r = BBTopAnalyzer(None).analyze("TESTUSDT", "SHORT")
    assert r["available"] is False
    assert r["grade"] == "D"
    assert "error" in r


def test_analyze_캔들주입():
    r = BBTopAnalyzer(None).analyze(
        "testusdt", "short",
        klines_15m=_bearish_div(), klines_1h=[], klines_4h=[],
    )
    assert r["symbol"] == "TESTUSDT"
    assert r["side"] == "SHORT"
    assert r["available"] is True
    assert r["grade"] in ("S", "A")


def test_LONG_바닥은_대칭구조():
    """헌법 5번 = 대칭성. (실측 검증은 천장 쪽만 된 상태!)"""
    r = BBTopAnalyzer.analyze_15m(_flat(150), "LONG")
    assert r["available"] is True
    assert r["side"] == "LONG"


# ----------------------------------------------------------------------
# 학습 저장
# ----------------------------------------------------------------------
def test_학습_컨텍스트():
    ctx = to_learning_context(_combine(_bearish_div()))
    assert ctx["grade"] in ("S", "A")
    assert ctx["div_count"] >= 2
    assert ctx["bb_touch"] is True
    assert "bb_mid_position" in ctx
    assert "tf_15m" not in ctx and "signals" not in ctx


def test_학습_컨텍스트_None():
    assert to_learning_context(None) == {}
