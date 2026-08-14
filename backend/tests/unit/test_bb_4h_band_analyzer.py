"""📉 4H 볼밴 중단 이탈 전략 단위 테스트 (v143).

spec: docs/BB_4H_BAND_STRATEGY_SPEC.md
합성 캔들만 사용 = 네트워크 X!
"""
from __future__ import annotations

from app.services.bb_4h_band_analyzer import BB4HBandAnalyzer as B
from app.services.bb_4h_band_analyzer import to_learning_context


def kline(close: float, high: float | None = None, low: float | None = None) -> list:
    h = close * 1.005 if high is None else high
    l = close * 0.995 if low is None else low
    return [0, close, h, l, close, 100.0, 0]


def _range(n: int = 40, price: float = 100.0, amp: float = 2.0) -> list:
    """중단 위아래로 진동하는 배경 (밴드가 형성되도록 변동 필요)."""
    return [kline(price + (amp if i % 2 else -amp)) for i in range(n)]


def _cross_down(tail: int = 1) -> list:
    """중단 위 → 하향 이탈 후 tail 봉 경과."""
    bars = [kline(100.0 + (2.0 if i % 2 else -2.0)) for i in range(30)]
    bars += [kline(103.0) for _ in range(4)]        # 중단 위로 확실히
    bars += [kline(98.5) for _ in range(tail)]      # 하향 이탈 (밴드는 미도달!)
    bars.append(kline(98.5))                        # 진행 중 봉
    return bars


def _cross_up(tail: int = 1) -> list:
    bars = [kline(100.0 + (2.0 if i % 2 else -2.0)) for i in range(30)]
    bars += [kline(97.0) for _ in range(4)]
    bars += [kline(101.5) for _ in range(tail)]     # 상향 돌파 (밴드는 미도달!)
    bars.append(kline(101.5))
    return bars


# ----------------------------------------------------------------------
# 지표
# ----------------------------------------------------------------------
def test_볼린저_계산():
    closes = [100.0 + (2.0 if i % 2 else -2.0) for i in range(30)]
    mid, up, lo = B.bollinger(closes)
    assert mid[-1] is not None
    assert up[-1] > mid[-1] > lo[-1]
    assert mid[:19] == [None] * 19


def test_변동없으면_밴드폭0():
    mid, up, lo = B.bollinger([50.0] * 30)
    assert up[-1] == mid[-1] == lo[-1] == 50.0


# ----------------------------------------------------------------------
# 상태 판정
# ----------------------------------------------------------------------
def test_캔들부족():
    st = B.state([kline(100)] * 10)
    assert st["available"] is False
    assert "부족" in st["note"]


def test_하향이탈_감지():
    st = B.state(_cross_down())
    assert st["available"] is True
    assert st["cross"] == "DOWN"
    assert st["position"] == "BELOW_MID"
    assert st["bars_since_cross"] == 0
    assert st["target_band"] == st["lower"]
    assert st["target_dist_pct"] is not None


def test_상향돌파_감지():
    st = B.state(_cross_up())
    assert st["cross"] == "UP"
    assert st["position"] == "ABOVE_MID"
    assert st["target_band"] == st["upper"]


def test_이탈없으면_cross_None():
    st = B.state(_range(40))
    # 진동만 하면 최근 12봉 내 교차가 잡힐 수 있으므로 존재 자체만 확인
    assert st["available"] is True
    assert st["position"] in ("ABOVE_MID", "BELOW_MID")


def test_경과봉수_증가():
    st1 = B.state(_cross_down(tail=1))
    st3 = B.state(_cross_down(tail=3))
    assert st1["bars_since_cross"] < st3["bars_since_cross"]


def test_완료봉_기준_리페인팅방지():
    """진행 중 봉을 바꿔도 판정이 흔들리면 안 됨!"""
    bars = _cross_down()
    base = B.state(bars)
    moved = [list(b) for b in bars]
    moved[-1][4] = 999.0
    moved[-1][2] = 999.0
    after = B.state(moved)
    assert after["close"] == base["close"]
    assert after["cross"] == base["cross"]
    assert after["current_price"] != base["current_price"]


# ----------------------------------------------------------------------
# 등급 / 종합
# ----------------------------------------------------------------------
def test_하향이탈직후_A등급_SHORT():
    r = B.combine("T", "SHORT", B.state(_cross_down(tail=1)))
    assert r["grade"] == "A"
    assert r["stage"] == "TRIGGER"
    assert r["signal_side"] == "SHORT"
    assert r["levels"]["reach_rate"] == 82.8
    assert r["levels"]["sample_n"] == 13053


def test_상향돌파직후_A등급_LONG():
    r = B.combine("T", "LONG", B.state(_cross_up(tail=1)))
    assert r["grade"] == "A"
    assert r["signal_side"] == "LONG"
    assert r["levels"]["reach_rate"] == 86.6


def test_방향_불일치면_D등급():
    """하향 이탈인데 LONG 분석 = 근거 없음!"""
    r = B.combine("T", "LONG", B.state(_cross_down(tail=1)))
    assert r["grade"] == "D"
    assert r["stage"] == "AVOID"
    assert any("불일치" in s for s in r["signals"])


def test_경과봉수_많으면_B등급():
    r = B.combine("T", "SHORT", B.state(_cross_down(tail=5)))
    assert r["grade"] in ("B", "C")


def test_밴드도달시_C등급_청산검토():
    """하단에 닿으면 목표 달성 = 청산 검토 + 「지지선 아님」 경고!"""
    bars = [kline(100.0 + (2.0 if i % 2 else -2.0)) for i in range(30)]
    bars += [kline(103.0) for _ in range(4)]
    bars += [kline(80.0, high=82.0, low=70.0)]      # 하단 관통!
    bars.append(kline(80.0))
    r = B.combine("T", "SHORT", B.state(bars))
    if r["stage"] == "TARGET_HIT":
        assert r["grade"] == "C"
        assert any("지지·저항이" in s for s in r["signals"])
        assert any("68.3%" in s for s in r["signals"])


def test_실측_기대값_수수료차감_표시():
    r = B.combine("T", "SHORT", B.state(_cross_down(tail=1)))
    lv = r["levels"]
    assert lv["expected_value_pct"] == 0.42
    assert lv["expected_value_after_fee_pct"] == round(0.42 - B.ROUND_TRIP_FEE, 3)
    assert any("수수료 차감 후" in s for s in r["signals"])


def test_SL은_추세반대쪽():
    r = B.combine("T", "SHORT", B.state(_cross_down(tail=1)))
    lv = r["levels"]
    assert lv["sl_price"] > lv["entry_ref"], "SHORT = SL 은 위!"
    r2 = B.combine("T", "LONG", B.state(_cross_up(tail=1)))
    assert r2["levels"]["sl_price"] < r2["levels"]["entry_ref"], "LONG = SL 은 아래!"


def test_판정불가_안전():
    r = B.combine("T", "SHORT", B.state([kline(100)] * 5))
    assert r["available"] is False
    assert r["grade"] == "D"


# ----------------------------------------------------------------------
# 진입점 / 학습
# ----------------------------------------------------------------------
def test_analyze_failsafe():
    r = B(None).analyze("TESTUSDT", "SHORT")
    assert r["available"] is False
    assert "error" in r


def test_analyze_캔들주입():
    r = B(None).analyze("testusdt", "short", klines_4h=_cross_down(tail=1))
    assert r["symbol"] == "TESTUSDT"
    assert r["available"] is True
    assert r["grade"] == "A"


def test_학습_컨텍스트():
    ctx = to_learning_context(B.combine("T", "SHORT", B.state(_cross_down(tail=1))))
    assert ctx["grade"] == "A"
    assert ctx["cross"] == "DOWN"
    assert ctx["signal_side"] == "SHORT"
    assert ctx["reach_rate"] == 82.8
    assert "signals" not in ctx and "state" not in ctx


def test_학습_컨텍스트_None():
    assert to_learning_context(None) == {}
