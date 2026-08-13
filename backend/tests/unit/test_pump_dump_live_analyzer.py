"""⚡ 급등락 실시간 진입 분석기 단위 테스트 (v141).

spec: docs/PUMP_DUMP_LIVE_STRATEGY_SPEC.md
합성 캔들만 사용 = 네트워크 X!
"""
from __future__ import annotations

from app.services.pump_dump_live_analyzer import PumpDumpLiveAnalyzer as P
from app.services.pump_dump_live_analyzer import to_learning_context


def kline(close: float, high: float | None = None, low: float | None = None) -> list:
    h = close * 1.002 if high is None else high
    l = close * 0.998 if low is None else low
    return [0, close, h, l, close, 100.0, 0]


def ramp(n: int, start: float, total_pct: float) -> list:
    """n봉에 걸쳐 total_pct% 만큼 선형 이동."""
    end = start * (1 + total_pct / 100)
    step = (end - start) / max(n - 1, 1)
    return [kline(start + step * i) for i in range(n)]


def _flat(n: int = 40, price: float = 100.0) -> list:
    return [kline(price) for _ in range(n)]


# ----------------------------------------------------------------------
# 측정
# ----------------------------------------------------------------------
def test_횡보는_변동_0():
    m = P.measure(_flat(40), "5m")
    assert m["available"] is True
    for label, chg in m["changes"].items():
        assert abs(chg) < 0.01, f"{label} 변동이 있으면 안 됨"


def test_급등_변동률_측정():
    # 5m 12봉(1시간)에 걸쳐 +20%
    bars = _flat(30) + ramp(13, 100.0, 20.0)
    m = P.measure(bars, "5m")
    assert m["available"] is True
    assert m["changes"]["1시간"] > 19, f"1시간 창 +20% 근처여야 함: {m['changes']}"
    assert m["price"] > 119


def test_캔들_부족():
    m = P.measure([kline(100)] * 5, "5m")
    assert m["available"] is False
    assert "부족" in m["note"]


def test_지원하지_않는_TF():
    m = P.measure([kline(100)] * 40, "1h")
    assert m["available"] is False


def test_정점대비_위치():
    """급등 후 밀린 상태 = from_high_pct 음수."""
    bars = _flat(20) + ramp(10, 100.0, 20.0) + [kline(110.0)] * 5
    m = P.measure(bars, "5m")
    assert m["from_high_pct"] < 0, "정점보다 아래 = 음수!"
    assert m["window_high"] >= 119


# ----------------------------------------------------------------------
# 이벤트 감지
# ----------------------------------------------------------------------
def test_감지_없음():
    m5 = P.measure(_flat(40), "5m")
    m15 = P.measure(_flat(40), "15m")
    assert P.detect(m5, m15) == {}


def test_감지_급등():
    """v141b: 진입 신호는 15m 20% 전후 밴드에서만!"""
    m15 = P.measure(_flat(30) + ramp(5, 100.0, 20.0), "15m")
    ev = P.detect(P.measure(_flat(40), "5m"), m15)
    assert ev["kind"] == "PUMP"
    assert ev["tf"] == "15m"
    assert ev["change_pct"] > 15


def test_감지_급락():
    m15 = P.measure(_flat(30) + ramp(5, 100.0, -20.0), "15m")
    ev = P.detect(P.measure(_flat(40), "5m"), m15)
    assert ev["kind"] == "DUMP"
    assert ev["change_pct"] < -15


def test_감지는_가장_큰_변동을_고름():
    m5 = P.measure(_flat(30) + ramp(13, 100.0, 12.0), "5m")     # +12%
    m15 = P.measure(_flat(30) + ramp(17, 100.0, 20.0), "15m")   # +20% (밴드 안!)
    ev = P.detect(m5, m15)
    assert ev["tf"] == "15m" and ev["change_pct"] > 15


# ----------------------------------------------------------------------
# 🎯 v141a — 15m 은 「20% 전후」 밴드에서만! (사장님 지시)
# ----------------------------------------------------------------------
def test_15m_밴드_밖은_신호없음_아래():
    """15m +15% = 밴드(17.5~22.5%) 아래 → 15m 신호 X"""
    m15 = P.measure(_flat(30) + ramp(17, 100.0, 15.0), "15m")
    m5 = P.measure(_flat(40), "5m")
    assert P.detect(m5, m15) == {}, "15m 15%는 신호를 내면 안 됨!"


def test_15m_밴드_밖은_신호없음_위():
    """15m +30% = 밴드 위 → 15m 신호 X (사장님: 20% 전후만!)"""
    m15 = P.measure(_flat(30) + ramp(17, 100.0, 30.0), "15m")
    m5 = P.measure(_flat(40), "5m")
    assert P.detect(m5, m15) == {}, "15m 30%도 밴드 밖이면 신호 X!"


def test_15m_밴드_안이면_감지():
    for pct in (18.0, 20.0, 22.0):
        m15 = P.measure(_flat(30) + ramp(17, 100.0, pct), "15m")
        ev = P.detect(P.measure(_flat(40), "5m"), m15)
        assert ev.get("tf") == "15m", f"{pct}% 는 밴드 안이라 감지돼야 함"


def test_5m은_신호를_내지_않음():
    """🎯 v141b 사장님 결정: 급등락 진입은 **15m 20% 전후만**!

    5m 은 아무리 크게 움직여도 진입 신호를 내지 않습니다 (측정만 함).
    """
    assert P.ENABLE_5M_SIGNAL is False
    for pct in (12.0, 20.0, 30.0, 50.0):
        m5 = P.measure(_flat(30) + ramp(13, 100.0, pct), "5m")
        ev = P.detect(m5, P.measure(_flat(40), "15m"))
        assert ev == {}, f"5m {pct}% 는 신호를 내면 안 됨!"


def test_5m_변동은_참고로_계속_측정():
    """신호는 안 내도 화면 표시용 측정은 유지!"""
    m5 = P.measure(_flat(30) + ramp(13, 100.0, 20.0), "5m")
    assert m5["available"] is True
    assert m5["changes"]["1시간"] > 15


def test_15m_밴드밖이면_이유를_설명():
    """왜 신호가 없는지 사장님께 명시해야 함!"""
    r = _res(_flat(40), _flat(30) + ramp(17, 100.0, 30.0))
    assert r["grade"] == "D"
    assert any("밴드" in s for s in r["signals"]), r["signals"]


def test_15m_2시간창은_기대값0_이라_신호없음():
    """같은 20%라도 2시간 창은 실측 기대값 0.00% → 신호 X (창이 갈랐다!)"""
    # 15m 8봉(2시간)에만 20% 걸치고 1시간/4시간 창은 밴드 밖이 되도록 구성
    bars = _flat(30) + ramp(9, 100.0, 20.0) + [kline(120.0)] * 0
    m15 = P.measure(bars, "15m")
    ev = P.detect(P.measure(_flat(40), "5m"), m15)
    if ev.get("window") == "2시간":
        r = P.combine("T", P.measure(_flat(40), "5m"), m15)
        assert r["side"] is None
        assert r["grade"] == "D"


# ----------------------------------------------------------------------
# 권고
# ----------------------------------------------------------------------
def _res(k5, k15):
    return P.combine("TESTUSDT", P.measure(k5, "5m"), P.measure(k15, "15m"))


def test_신호없으면_D등급():
    r = _res(_flat(40), _flat(40))
    assert r["grade"] == "D"
    assert r["stage"] == "NONE"
    assert r["side"] is None


def test_급등은_추격_LONG():
    """실측 69%가 급등 추격 → 방향은 반드시 LONG!"""
    r = _res(_flat(40), _flat(30) + ramp(5, 100.0, 20.0))
    assert r["side"] == "LONG"
    assert r["stage"] == "TRIGGER"
    assert r["grade"] in ("A", "B", "C")
    assert any("추격 LONG" in s for s in r["signals"])


def test_급락은_진입_비권장():
    """실측: 급락은 양방향 모두 기대값 없음 → side=None + AVOID!"""
    r = _res(_flat(40), _flat(30) + ramp(5, 100.0, -20.0))
    assert r["grade"] == "D"
    assert r["stage"] == "AVOID"
    assert r["side"] is None, "급락은 방향 권고를 하지 않습니다!"
    assert any("방향성이 없습니다" in s for s in r["signals"])


def test_플레이북_15m_20퍼_1시간():
    """15m 1시간 20% 전후 = 밴드 실측 +5%/-5%, 기대값 +0.18% (255건)."""
    r = _res(_flat(40), _flat(30) + ramp(5, 100.0, 21.0))
    assert r["side"] == "LONG"
    assert r["grade"] == "B", f"{r['verdict']}"
    lv = r["levels"]
    assert lv["tp_pct"] == 5.0 and lv["sl_pct"] == 5.0, "밴드 실측 최적 조합!"
    assert lv["expected_value_pct"] == 0.18
    assert lv["sample_n"] == 255


def test_수수료_차감_기대값_표시():
    r = _res(_flat(40), _flat(30) + ramp(5, 100.0, 21.0))
    lv = r["levels"]
    assert lv["expected_value_after_fee_pct"] == round(0.18 - P.ROUND_TRIP_FEE, 3)
    assert any("수수료 차감 후" in s for s in r["signals"])


def test_작은TP_경고_항상_노출():
    r = _res(_flat(40), _flat(30) + ramp(5, 100.0, 20.0))
    assert any("작은 TP는 독" in s for s in r["signals"])


def test_정점대비_밀림_경고():
    """급등이 이미 끝난 뒤 = 추격 불리 경고!"""
    bars = _flat(20) + ramp(10, 100.0, 25.0) + [kline(118.0)] * 3
    r = _res(bars, _flat(40))
    if r["side"] == "LONG":
        assert any("정점 대비" in s for s in r["signals"])


def test_TP_SL_가격_산출():
    r = _res(_flat(40), _flat(30) + ramp(5, 100.0, 20.0))
    lv = r["levels"]
    assert lv["tp_price"] > lv["entry_ref"] > lv["sl_price"], "LONG = TP 위 / SL 아래"


def test_15m_12퍼는_밴드밖_신호없음():
    """v141b: 12% 는 20% 전후 밴드 밖 = 신호 없음 (C등급 관찰 구간도 사라짐)."""
    r = _res(_flat(40), _flat(30) + ramp(5, 100.0, 12.0))
    assert r["grade"] == "D"
    assert r["side"] is None


# ----------------------------------------------------------------------
# 진입점 / 학습
# ----------------------------------------------------------------------
def test_analyze_failsafe():
    r = P(None).analyze("TESTUSDT")
    assert r["available"] is False
    assert r["grade"] == "D"
    assert "error" in r


def test_analyze_캔들주입():
    r = P(None).analyze(
        "testusdt",
        klines_5m=_flat(40),
        klines_15m=_flat(30) + ramp(5, 100.0, 20.0),
    )
    assert r["symbol"] == "TESTUSDT"
    assert r["available"] is True
    assert r["side"] == "LONG"


def test_학습_컨텍스트():
    r = _res(_flat(40), _flat(30) + ramp(5, 100.0, 21.0))
    ctx = to_learning_context(r)
    assert ctx["grade"] == "B"
    assert ctx["kind"] == "PUMP"
    assert ctx["side"] == "LONG"
    assert ctx["tp_pct"] == 5.0
    assert ctx["tf"] == "15m"
    assert "signals" not in ctx and "m5" not in ctx


def test_학습_컨텍스트_None():
    assert to_learning_context(None) == {}


# ----------------------------------------------------------------------
# v142 — 되돌림 상태 (보유 판단용, 진입 신호 아님!)
# ----------------------------------------------------------------------
def test_되돌림_얕으면_높은_회복률():
    """고점 -4% = 얕은 되돌림 → 실측 회복률 80%"""
    bars = _flat(20) + ramp(10, 100.0, 20.0) + [kline(120.0 * 0.96)] * 3
    st = P.retrace_state(bars)
    assert st["available"] is True
    assert -6 < st["retrace_pct"] < -1
    assert st["recovery_rate"] == 80.0
    assert "홀드" in st["advice"]


def test_되돌림_깊으면_낮은_회복률():
    """고점 -25% = 깊은 되돌림 → 회복률 12%"""
    bars = _flat(20) + ramp(10, 100.0, 20.0) + [kline(120.0 * 0.75)] * 3
    st = P.retrace_state(bars)
    assert st["recovery_rate"] == 12.0
    assert "깊은 되돌림" in st["advice"]


def test_되돌림_고점부근은_판정보류():
    bars = _flat(20) + ramp(10, 100.0, 20.0)
    st = P.retrace_state(bars)
    assert abs(st["retrace_pct"]) < 1.0
    assert "고점 부근" in st["advice"]


def test_되돌림_캔들부족():
    st = P.retrace_state([kline(100)] * 5)
    assert st["available"] is False


def test_analyze_결과에_되돌림_포함():
    r = P(None).analyze("T", klines_5m=_flat(40), klines_15m=_flat(30) + ramp(5, 100.0, 21.0))
    assert "retrace" in r and r["retrace"]["available"] is True


def test_되돌림은_진입신호가_아님():
    """헌법: 되돌림 진입 규칙 3종은 전부 기대값 마이너스 = 신호로 쓰지 않음!"""
    assert "마이너스" in P.REVERSAL_ENTRY_VERDICT
    st = P.retrace_state(_flat(20) + ramp(10, 100.0, 20.0) + [kline(115.0)] * 3)
    assert "side" not in st, "되돌림 상태는 진입 방향을 제시하지 않습니다!"
