"""🔀 20% 급등 지속/전환 판별기 단위 테스트 (v146)."""
from __future__ import annotations

from app.services.pump_continuation_analyzer import PumpContinuationAnalyzer as P
from app.services.pump_continuation_analyzer import to_learning_context


def kline(o, c, h=None, l=None, v=100.0):
    h = max(o, c) * 1.001 if h is None else h
    l = min(o, c) * 0.999 if l is None else l
    return [0, o, h, l, c, v, 0]


def build(move_pct: float, vol_mult: float = 1.0, close_pos: float = 0.5,
          accel_up: bool = False, n_pre: int = 40) -> list:
    """20% 급등 시나리오 합성 (5m).

    close_pos: 마지막 봉에서 종가가 봉 범위의 어디에 위치하는가.
    """
    bars = [kline(100.0, 100.0, 100.5, 99.5, 100.0) for _ in range(n_pre)]
    steps = P.WINDOW
    start, end = 100.0, 100.0 * (1 + move_pct / 100)
    prev = start
    for i in range(steps):
        # accel_up=True 면 뒤로 갈수록 상승폭 확대
        frac = ((i + 1) / steps) ** (0.5 if accel_up else 1.0)
        px = start + (end - start) * frac
        v = 100.0 * (vol_mult if i >= steps - 6 else 1.0)
        bars.append(kline(prev, px, max(prev, px) * 1.002, min(prev, px) * 0.998, v))
        prev = px
    # 마지막 봉의 종가 위치 조정
    last = bars[-1]
    lo, hi = last[3], last[2]
    last[4] = lo + (hi - lo) * close_pos
    return bars


# ----------------------------------------------------------------------
def test_횡보는_급등아님():
    bars = [kline(100.0, 100.0) for _ in range(80)]
    m = P.measure(bars)
    assert m["available"] is True
    assert m["is_pump"] is False
    assert abs(m["move_pct"]) < 1


def test_20퍼_급등_감지():
    m = P.measure(build(22.0))
    assert m["is_pump"] is True
    assert m["move_pct"] > 20


def test_캔들부족():
    m = P.measure([kline(100, 100)] * 10)
    assert m["available"] is False
    assert "부족" in m["note"]


def test_거래량비율_측정():
    low = P.measure(build(22.0, vol_mult=1.0))
    high = P.measure(build(22.0, vol_mult=6.0))
    assert high["vol_ratio"] > low["vol_ratio"]
    assert high["vol_ratio"] >= P.VOL_STRONG


def test_종가위치_측정():
    top = P.measure(build(22.0, close_pos=0.95))
    bot = P.measure(build(22.0, close_pos=0.05))
    assert top["close_pos"] > 0.8
    assert bot["close_pos"] < 0.2


# ----------------------------------------------------------------------
# 판별 — 사장님 요구: 롱/숏 동시 판단
# ----------------------------------------------------------------------
def test_지속신호_거래량폭발_고가마감_LONG():
    """거래량 4배+ AND 종가 상단 → 지속 = LONG 짧게!"""
    r = P.combine("T", P.measure(build(22.0, vol_mult=8.0, close_pos=0.9)))
    assert r["kind"] == "CONTINUE"
    assert r["side"] == "LONG"
    assert r["grade"] == "A"
    lv = r["levels"]
    assert lv["tp_pct"] == P.LONG_TP
    assert lv["tp_price"] > lv["entry_ref"] > lv["sl_price"]
    assert lv["max_stages"] == 3, "사장님 지시 = 최대 3단계!"


def test_전환신호_둔화_거래량마름_SHORT():
    """가속 둔화 AND 거래량 마름 → 전환 = SHORT!"""
    bars = build(22.0, vol_mult=0.2, close_pos=0.3)
    m = P.measure(bars)
    if m["accel"] < 0 and m["vol_ratio"] < 1.0:
        r = P.combine("T", m)
        assert r["kind"] == "REVERSE"
        assert r["side"] == "SHORT"
        lv = r["levels"]
        assert lv["tp_price"] < lv["entry_ref"] < lv["sl_price"], "SHORT = TP 아래!"


def test_중립은_진입안함():
    """어느 신호도 아니면 side=None (동전던지기 구간!)"""
    m = P.measure(build(22.0, vol_mult=2.0, close_pos=0.5))
    r = P.combine("T", m)
    if r["kind"] == "NEUTRAL":
        assert r["side"] is None
        assert r["grade"] == "C"
        assert any("동전던지기" in s for s in r["signals"])


def test_급등아니면_D등급():
    r = P.combine("T", P.measure([kline(100.0, 100.0) for _ in range(80)]))
    assert r["grade"] == "D"
    assert r["side"] is None


def test_기저비율_항상_노출():
    """41:49 라는 사실을 사장님께 항상 보여줘야 함!"""
    r = P.combine("T", P.measure(build(22.0, vol_mult=8.0, close_pos=0.9)))
    assert any("동전던지기" in s for s in r["signals"])
    assert any(str(P.BASE_CONTINUE) in s for s in r["signals"])


def test_100퍼_희귀성_경고():
    """20%→100% 는 0.4% 라는 걸 반드시 표시!"""
    r = P.combine("T", P.measure(build(22.0, vol_mult=8.0, close_pos=0.9)))
    assert any("+100% 0.4%" in s for s in r["signals"])


def test_표본부족_경고():
    r = P.combine("T", P.measure(build(22.0, vol_mult=8.0, close_pos=0.9)))
    assert any("확정된 우위는 아닙니다" in s for s in r["signals"])


def test_LONG은_짧게_SHORT보다_TP작음():
    """사장님 지시: 지속 상승은 LONG **짧게**"""
    assert P.LONG_TP < P.SHORT_TP


# ----------------------------------------------------------------------
def test_analyze_failsafe():
    r = P(None).analyze("TESTUSDT")
    assert r["available"] is False
    assert "error" in r


def test_analyze_캔들주입():
    r = P(None).analyze("testusdt", klines_5m=build(22.0, vol_mult=8.0, close_pos=0.9))
    assert r["symbol"] == "TESTUSDT"
    assert r["available"] is True
    assert r["side"] == "LONG"


def test_학습_컨텍스트():
    ctx = to_learning_context(
        P.combine("T", P.measure(build(22.0, vol_mult=8.0, close_pos=0.9))))
    assert ctx["kind"] == "CONTINUE"
    assert ctx["side"] == "LONG"
    assert ctx["vol_ratio"] >= P.VOL_STRONG
    assert "signals" not in ctx and "measure" not in ctx


def test_학습_컨텍스트_None():
    assert to_learning_context(None) == {}
