"""☁️ 파라볼릭 SAR + 일목 구름대 분석 단위 테스트 (v138).

spec: docs/SAR_ICHIMOKU_MTF_STRATEGY_SPEC.md

합성 캔들만 사용 = 네트워크 X!
"""
from __future__ import annotations

from app.services import strategy_confluence
from app.services.sar_ichimoku_analyzer import SARIchimokuAnalyzer, to_learning_context


def kline(close: float, high: float | None = None, low: float | None = None,
          vol: float = 100.0) -> list:
    high = close * 1.004 if high is None else high
    low = close * 0.996 if low is None else low
    return [0, close, high, low, close, vol, 0]


def _uptrend(n: int = 100) -> list:
    return [kline(100 + i * 0.9) for i in range(n)]


def _downtrend(n: int = 100) -> list:
    return [kline(200 - i * 0.9) for i in range(n)]


def _inside_cloud() -> list:
    """급등 후 되돌림 = 캔들이 구름 내부 = 관망 구간!"""
    return [kline(100 + i * 0.9) for i in range(70)] + [kline(163 - i * 0.3) for i in range(32)]


def _long_trigger() -> list:
    """상승 → 짧은 눌림(SAR 하락 전환) → 재상승(SAR 상승 재전환 = 첫 점!)"""
    bars = [kline(100 + i * 0.9) for i in range(92)]
    for c, h, l in [(178, 180, 170), (172, 176, 168), (170, 174, 167)]:
        bars.append(kline(c, h, l))
    for c, h, l in [(180, 182, 171), (186, 188, 179), (190, 192, 185), (191, 193, 189)]:
        bars.append(kline(c, h, l))
    return bars


# ----------------------------------------------------------------------
# 파라볼릭 SAR
# ----------------------------------------------------------------------
def test_psar_상승추세는_점이_아래():
    d = SARIchimokuAnalyzer.split_klines(_uptrend())
    sar, trend = SARIchimokuAnalyzer.psar(d["highs"], d["lows"], d["closes"])

    assert len(sar) == len(d["closes"])
    assert trend[-1] is True, "상승 추세 = SAR 점이 캔들 아래!"
    assert sar[-1] < d["closes"][-1], "상승 구간 SAR = 가격보다 낮아야 함"


def test_psar_하락추세는_점이_위():
    d = SARIchimokuAnalyzer.split_klines(_downtrend())
    sar, trend = SARIchimokuAnalyzer.psar(d["highs"], d["lows"], d["closes"])

    assert trend[-1] is False
    assert sar[-1] > d["closes"][-1], "하락 구간 SAR = 가격보다 높아야 함"


def test_psar_가속계수_상한():
    """AF는 0.2를 넘지 않아야 함 = SAR가 가격을 추월해 폭주하지 않음."""
    d = SARIchimokuAnalyzer.split_klines(_uptrend(200))
    sar, trend = SARIchimokuAnalyzer.psar(d["highs"], d["lows"], d["closes"])
    # 장기 단조 상승에서도 SAR는 항상 저가 아래에 머물러야 함!
    for i in range(60, len(sar)):
        if trend[i]:
            assert sar[i] <= d["lows"][i], f"index {i}: SAR가 저가를 넘음 = 계산 오류!"


def test_psar_데이터_부족():
    sar, trend = SARIchimokuAnalyzer.psar([1.0], [1.0], [1.0])
    assert sar == [None] and trend == [None]


def test_sar_state_전환_감지():
    """상승 → 급락 = SAR 하락 전환 + 신선한 첫 점!"""
    bars = _uptrend(96) + [
        kline(120, 121, 112), kline(115, 118, 110),
        kline(114, 116, 109), kline(114, 115, 113),
    ]
    s = SARIchimokuAnalyzer.sar_state(bars)

    assert s["available"] is True
    assert s["uptrend"] is False, "급락 후 = 하락 전환!"
    assert s["flip_bars_ago"] is not None
    assert s["fresh_flip"] is True, "최근 3봉 이내 전환 = 첫 점!"


def test_sar_state_단일추세는_전환없음():
    s = SARIchimokuAnalyzer.sar_state(_uptrend())
    assert s["uptrend"] is True
    assert s["flip_bars_ago"] is None, "전환 없으면 None!"
    assert s["fresh_flip"] is False


def test_sar_state_캔들_부족():
    s = SARIchimokuAnalyzer.sar_state([kline(100)] * 3)
    assert s["available"] is False


# ----------------------------------------------------------------------
# 일목 구름대
# ----------------------------------------------------------------------
def test_구름_상승추세는_ABOVE():
    c = SARIchimokuAnalyzer.cloud_state(_uptrend())
    assert c["available"] is True
    assert c["position"] == "ABOVE"
    assert c["close"] > c["top"]
    assert c["thickness_pct"] > 0


def test_구름_하락추세는_BELOW():
    c = SARIchimokuAnalyzer.cloud_state(_downtrend())
    assert c["position"] == "BELOW"
    assert c["close"] < c["bottom"]


def test_구름_내부는_INSIDE_관망():
    c = SARIchimokuAnalyzer.cloud_state(_inside_cloud())
    assert c["position"] == "INSIDE"
    assert c["bottom"] <= c["close"] <= c["top"]


def test_구름_캔들_부족():
    c = SARIchimokuAnalyzer.cloud_state([kline(100)] * 40)
    assert c["available"] is False
    assert "부족" in c["note"]


def test_구름은_완료봉_기준_리페인팅_방지():
    """진행 중 봉을 바꿔도 구름 판정(close)은 안 바뀌어야 함!"""
    bars = _uptrend()
    base = SARIchimokuAnalyzer.cloud_state(bars)

    moved = [list(b) for b in bars]
    moved[-1][4] = 1.0          # 진행 중 봉 종가를 폭락시켜도...
    moved[-1][3] = 0.5
    after = SARIchimokuAnalyzer.cloud_state(moved)

    assert after["close"] == base["close"], "완료봉 종가 기준이어야 함!"
    assert after["position"] == base["position"]
    assert after["current_price"] != base["current_price"], "현재가는 따로 보고!"


# ----------------------------------------------------------------------
# 타임프레임 판정
# ----------------------------------------------------------------------
def test_4h_구름위는_LONG만_허가():
    up = _uptrend()
    assert SARIchimokuAnalyzer.analyze_4h(up, "LONG")["ok"] is True
    assert SARIchimokuAnalyzer.analyze_4h(up, "SHORT")["ok"] is False


def test_4h_구름아래는_SHORT만_허가():
    dn = _downtrend()
    assert SARIchimokuAnalyzer.analyze_4h(dn, "SHORT")["ok"] is True
    assert SARIchimokuAnalyzer.analyze_4h(dn, "LONG")["ok"] is False


def test_4h_구름내부는_양방향_금지():
    inside = _inside_cloud()
    assert SARIchimokuAnalyzer.analyze_4h(inside, "LONG")["ok"] is False
    assert SARIchimokuAnalyzer.analyze_4h(inside, "SHORT")["ok"] is False


def test_15m_방아쇠_손절기준():
    r = SARIchimokuAnalyzer.analyze_15m(_long_trigger(), "LONG")
    assert r["ok"] is True
    assert r["sar_aligned"] is True
    assert r["trigger"] is True, "신선한 SAR 상승 전환 = 방아쇠!"
    # 손절 = 구름 하단 (LONG)
    assert r["stop_loss"] == r["bottom"]
    assert r["risk_pct"] > 0


def test_15m_SHORT_손절은_구름_상단():
    r = SARIchimokuAnalyzer.analyze_15m(_downtrend(), "SHORT")
    assert r["ok"] is True
    assert r["stop_loss"] == r["top"]


# ----------------------------------------------------------------------
# 종합 등급
# ----------------------------------------------------------------------
def _combine(side: str, k4=None, k1=None, k15=None):
    k4 = k4 if k4 else _uptrend()
    k1 = k1 if k1 else _uptrend()
    k15 = k15 if k15 else _long_trigger()
    return SARIchimokuAnalyzer.combine(
        "TESTUSDT", side,
        SARIchimokuAnalyzer.analyze_4h(k4, side),
        SARIchimokuAnalyzer.analyze_1h(k1, side),
        SARIchimokuAnalyzer.analyze_15m(k15, side),
    )


def test_등급A_SAR_전환_첫점():
    r = _combine("LONG")
    assert r["grade"] == "A"
    assert r["stage"] == "TRIGGER"
    assert r["score"] >= 80
    assert r["levels"]["stop_loss"] is not None


def test_등급B_정렬완료_전환대기():
    """3중 구름 정렬은 됐지만 SAR 전환이 오래됨 = B (추격 금지!)"""
    r = _combine("LONG", k15=_uptrend())
    assert r["grade"] == "B"
    assert r["stage"] == "SETUP"


def test_등급C_하위_정렬_대기():
    """4H만 구름 위, 1H는 구름 안 = C"""
    r = _combine("LONG", k1=_inside_cloud(), k15=_inside_cloud())
    assert r["grade"] == "C"
    assert r["stage"] == "WATCH"


def test_등급D_4H_역방향():
    r = _combine("SHORT")   # 4H 구름 위인데 SHORT = 역방향!
    assert r["grade"] == "D"
    assert r["stage"] == "AVOID"
    assert any("금지" in s for s in r["signals"])


def test_등급D_4H_구름내부는_관망():
    r = _combine("LONG", k4=_inside_cloud())
    assert r["grade"] == "D"
    assert any("관망" in s for s in r["signals"])


def test_데이터부족_판정불가_예외없음():
    r = SARIchimokuAnalyzer.combine(
        "TESTUSDT", "LONG",
        SARIchimokuAnalyzer.analyze_4h([], "LONG"),
        SARIchimokuAnalyzer.analyze_1h([], "LONG"),
        SARIchimokuAnalyzer.analyze_15m([], "LONG"),
    )
    assert r["available"] is False
    assert r["grade"] == "D"
    assert r["stage"] == "UNKNOWN"


def test_analyze_클라이언트_없으면_failsafe():
    r = SARIchimokuAnalyzer(None).analyze("TESTUSDT", "LONG")
    assert r["available"] is False
    assert r["grade"] == "D"
    assert "error" in r


def test_analyze_캔들_직접주입():
    r = SARIchimokuAnalyzer(None).analyze(
        "testusdt", "long",
        klines_4h=_uptrend(), klines_1h=_uptrend(), klines_15m=_long_trigger(),
    )
    assert r["symbol"] == "TESTUSDT"
    assert r["available"] is True
    assert r["grade"] == "A"


def test_학습_컨텍스트_압축():
    ctx = to_learning_context(_combine("LONG"))
    assert ctx["grade"] == "A"
    assert ctx["cloud_4h"] == "ABOVE"
    assert ctx["cloud_4h_ok"] is True
    assert ctx["sar_fresh_flip"] is True
    assert "tf_1h" not in ctx and "signals" not in ctx


def test_학습_컨텍스트_None_안전():
    assert to_learning_context(None) == {}


# ----------------------------------------------------------------------
# 🤝 두 전략 합의
# ----------------------------------------------------------------------
def _res(grade: str, score: int = 80, available: bool = True) -> dict:
    return {"available": available, "grade": grade, "score": score}


def test_합의_둘다A는_최상위():
    c = strategy_confluence.evaluate(_res("A", 90), _res("A", 85))
    assert c["level"] == "STRONG_AGREE"
    assert c["agree"] is True
    assert c["conflict"] is False
    assert c["score"] == 88  # (90+85)/2 반올림


def test_합의_A와B는_AGREE():
    c = strategy_confluence.evaluate(_res("A", 90), _res("B", 70))
    assert c["level"] == "AGREE"
    assert c["agree"] is True


def test_합의_둘다B도_AGREE():
    c = strategy_confluence.evaluate(_res("B", 60), _res("B", 70))
    assert c["level"] == "AGREE"


def test_합의_한쪽D는_충돌_차단():
    """v139: 충돌은 실측 적중률 16.4% = AVOID(32.8%)보다도 나쁨 → 차단 격상!"""
    c = strategy_confluence.evaluate(_res("A", 90), _res("D", 10))
    assert c["level"] == "CONFLICT"
    assert c["conflict"] is True
    assert c["agree"] is False
    assert c["blocked"] is True, "v139: 충돌 = 진입 비권장 = blocked!"
    assert c["score"] == 15, "v139: 평균(50)의 0.3배 = 신뢰도 대폭 하락!"
    assert any("금지" in s for s in c["signals"])


def test_합의_둘다D는_차단플래그():
    c = strategy_confluence.evaluate(_res("D", 0), _res("D", 5))
    assert c["level"] == "AVOID"
    assert c["blocked"] is True
    assert any("87%" in s for s in c["signals"]), "실측 근거를 사장님께 노출!"


def test_합의_정상구간은_차단아님():
    for a, b in (("A", "A"), ("A", "B"), ("B", "B"), ("C", "B")):
        c = strategy_confluence.evaluate(_res(a, 80), _res(b, 70))
        assert c["blocked"] is False, f"{a}+{b} 는 차단 대상이 아님!"


def test_합의_둘다D는_AVOID():
    c = strategy_confluence.evaluate(_res("D", 0), _res("D", 5))
    assert c["level"] == "AVOID"
    assert c["score"] == 0


def test_합의_C포함은_부분합의():
    c = strategy_confluence.evaluate(_res("C", 40), _res("B", 60))
    assert c["level"] == "PARTIAL"
    assert c["agree"] is False


def test_합의_한쪽_판정불가면_합의없음():
    c = strategy_confluence.evaluate(_res("A", 90), _res("A", 90, available=False))
    assert c["available"] is False
    assert c["level"] == "NONE"
    assert any("합의 없음" in s for s in c["signals"])


def test_합의_둘다_판정불가():
    c = strategy_confluence.evaluate(None, None)
    assert c["available"] is False
    assert c["level"] == "NONE"
    assert c["grades"] == {"ema_vcp": None, "sar_ichimoku": None}


def test_합의_학습_컨텍스트():
    ctx = strategy_confluence.to_learning_context(
        strategy_confluence.evaluate(_res("A", 90), _res("A", 90))
    )
    assert ctx["level"] == "STRONG_AGREE"
    assert ctx["agree"] is True
    assert ctx["grades"] == {"ema_vcp": "A", "sar_ichimoku": "A"}
    assert "signals" not in ctx


def test_합의_실제_분석기_결과로_동작():
    """실제 두 분석기 산출물을 그대로 넣어도 동작해야 함 (계약 검증!)"""
    from app.services.ema_vcp_analyzer import EMAVCPAnalyzer

    ema = EMAVCPAnalyzer(None).analyze(
        "TESTUSDT", "LONG",
        klines_4h=_uptrend(), klines_1h=_uptrend(), klines_15m=_uptrend(),
    )
    sar = SARIchimokuAnalyzer(None).analyze(
        "TESTUSDT", "LONG",
        klines_4h=_uptrend(), klines_1h=_uptrend(), klines_15m=_long_trigger(),
    )
    c = strategy_confluence.evaluate(ema, sar, "LONG")

    assert c["grades"]["sar_ichimoku"] == "A"
    assert c["level"] in ("STRONG_AGREE", "AGREE", "PARTIAL", "CONFLICT", "AVOID", "NONE")
    assert isinstance(c["signals"], list) and c["signals"]
