"""🎯 Fix 368 — 외부 전략 2종 (후지모토 3역 호전 · 마하세븐 속임수 돌파) 판정·크기 계산·배선."""
from pathlib import Path

import pytest

from app.services import external_strategies as ES

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


# ───────── 지표 ─────────
def test_sma_and_macd_and_rsi_basic():
    assert ES.sma([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]
    flat = [100.0] * 60
    m, s, h = ES.macd_lines(flat)
    assert len(m) == 60 and abs(m[-1]) < 1e-9 and abs(h[-1]) < 1e-9
    r = ES.rsi([float(i) for i in range(1, 40)])                       # 단조 상승 → RSI 100 근처
    assert r[13] is None and r[14] is not None and r[-1] > 99


def test_ichimoku_and_cloud_shift():
    n = 120
    h = [101.0] * n
    lo = [99.0] * n
    ic = ES.ichimoku(h, lo)
    assert ic["tenkan"][7] is None and ic["tenkan"][8] == 100.0 and ic["kijun"][25] == 100.0 and ic["span_b"][51] == 100.0
    assert ES.cloud_at(ic, 25) is None                                    # 26봉 전 선행스팬이 없다
    assert ES.cloud_at(ic, 90) == (100.0, 100.0)                          # 구름은 26봉 전 값을 되돌려 읽는다


# ───────── 다이버전스 ─────────
def test_divergence_detection():
    c = [100.0] * 40
    r: list = [50.0] * 40
    c[10], c[30] = 90.0, 88.0                                             # 가격 저점은 더 낮아짐
    r[10], r[30] = 25.0, 32.0                                             # RSI 저점은 높아짐
    assert ES.bullish_divergence(c, r, 35, 30) is True
    r[30] = 20.0
    assert ES.bullish_divergence(c, r, 35, 30) is False
    c2 = [100.0] * 40
    r2: list = [50.0] * 40
    c2[10], c2[30] = 110.0, 112.0
    r2[10], r2[30] = 75.0, 68.0
    assert ES.bearish_divergence(c2, r2, 35, 30) is True
    assert ES.bullish_divergence(c, r, 3, 30) is False                    # 창보다 짧으면 False


# ───────── 후지모토 3단 (배열을 직접 만들어 각 조건을 검증) ─────────
def _ind(n=120, **over):
    base = dict(c=[100.0] * n, h=[101.0] * n, l=[99.0] * n, rsi=[50.0] * n, macd=[0.0] * n, sig=[0.0] * n,
                tenkan=[100.0] * n, kijun=[100.0] * n, sma_s=[100.0] * n, sma_l=[100.0] * n)
    base.update(over)
    ic = {"tenkan": base["tenkan"], "kijun": base["kijun"], "span_a": over.get("span_a", [100.0] * n), "span_b": over.get("span_b", [100.0] * n)}
    return ES.Ind(c=base["c"], h=base["h"], l=base["l"], rsi=base["rsi"], macd=base["macd"], sig=base["sig"],
                  tenkan=base["tenkan"], kijun=base["kijun"], ichi=ic, sma_s=base["sma_s"], sma_l=base["sma_l"])


def test_fujimoto_stage1_rsi_reclaim_and_short_mirror():
    j = 100
    r = [50.0] * 120
    r[j - 1], r[j] = 28.0, 31.0
    st = ES.fujimoto_stages(_ind(rsi=r), j, "LONG")
    assert st == {1: True, 2: False, 3: False}
    r[j - 1], r[j] = 31.0, 33.0                                            # 30 아래에 있지 않았으면 아님
    assert ES.fujimoto_stages(_ind(rsi=r), j, "LONG")[1] is False
    r[j - 1], r[j] = 72.0, 69.0                                            # SHORT: 70 아래로 꺾임
    assert ES.fujimoto_stages(_ind(rsi=r), j, "SHORT")[1] is True
    assert ES.fujimoto_stages(_ind(rsi=r), 50, "LONG") == {1: False, 2: False, 3: False}   # 일목 52+26 봉 미만 = 판정 안 함


def test_fujimoto_stage2_divergence_plus_golden_cross_below_zero():
    j = 100
    c = [100.0] * 120
    r: list = [50.0] * 120
    c[75], c[95] = 90.0, 88.0
    r[75], r[95] = 25.0, 32.0
    macd = [-1.0] * 120
    sig = [-0.5] * 120
    macd[j] = -0.2                                                          # j 에서 시그널을 위로 뚫음, 아직 0 아래
    st = ES.fujimoto_stages(_ind(c=c, rsi=r, macd=macd, sig=sig), j, "LONG")
    assert st[2] is True
    macd[j] = 0.3                                                           # 영선 위 골든크로스 = 2차 아님 (출처: 영선 아래에서)
    assert ES.fujimoto_stages(_ind(c=c, rsi=r, macd=macd, sig=sig), j, "LONG")[2] is False
    # SHORT 2차 = 하락 다이버전스 + 데드크로스 + RSI<50
    c2 = [100.0] * 120
    r2: list = [50.0] * 120
    c2[75], c2[95] = 110.0, 112.0
    r2[75], r2[95] = 75.0, 68.0
    r2[j] = 45.0
    m2, s2 = [1.0] * 120, [0.5] * 120
    m2[j] = 0.2
    assert ES.fujimoto_stages(_ind(c=c2, rsi=r2, macd=m2, sig=s2), j, "SHORT")[2] is True
    r2[j] = 55.0
    assert ES.fujimoto_stages(_ind(c=c2, rsi=r2, macd=m2, sig=s2), j, "SHORT")[2] is False


def test_fujimoto_stage3_ichimoku_three_signals():
    j = 100
    c = [100.0] * 120
    c[j] = 106.0                                                            # 구름(100) 위 + 26봉 전 종가(100) 위
    t = [99.0] * 120
    k = [100.0] * 120
    t[j] = 101.0                                                            # 전환선이 기준선을 상향 돌파
    st = ES.fujimoto_stages(_ind(c=c, tenkan=t, kijun=k), j, "LONG")
    assert st[3] is True
    c[j] = 99.0                                                             # 구름 아래면 아님
    assert ES.fujimoto_stages(_ind(c=c, tenkan=t, kijun=k), j, "LONG")[3] is False
    # SHORT 3차 = 구름 하단 이탈 + 전환선 하향 돌파
    c3 = [100.0] * 120
    c3[j] = 94.0
    t3, k3 = [101.0] * 120, [100.0] * 120
    t3[j] = 99.0
    assert ES.fujimoto_stages(_ind(c=c3, tenkan=t3, kijun=k3), j, "SHORT")[3] is True


# ───────── 마하세븐 ─────────
def test_mach7_trap_long_and_short():
    n = 260
    j = 250
    c = [100.0] * n
    s = [100.0] * n
    L = [90.0 + i * 0.01 for i in range(n)]                                 # 200선 우상향
    s[j - 5] = 99.0                                                         # 5봉 기울기 = +1.01% ≥ 0.5
    c[j - 2], c[j - 1], c[j] = 99.5, 100.4, 100.6                           # 30선(100) 아래 → 2봉 연속 위 마감
    lo = [99.0] * n
    lo[j - 2] = 98.7
    ok, d = ES.mach7_signal(_ind(n=n, c=c, l=lo, sma_s=s, sma_l=L), j, "LONG", min_slope_pct=0.5)
    assert ok is True and d["trend"] is True and d["trap"] is True and d["stop"] == 98.7
    ok2, d2 = ES.mach7_signal(_ind(n=n, c=c, l=lo, sma_s=s, sma_l=L), j, "LONG", min_slope_pct=2.0)   # 기울기 부족
    assert ok2 is False and d2["trap"] is True
    c[j - 1] = 99.8                                                         # 2봉 연속이 아니면 아님
    assert ES.mach7_signal(_ind(n=n, c=c, l=lo, sma_s=s, sma_l=L), j, "LONG", min_slope_pct=0.5)[0] is False
    # SHORT: 200선 우하향 + 30선 위로 튀었다가 2봉 연속 아래 마감, 각도 필터 없음
    cs = [100.0] * n
    cs[j - 2], cs[j - 1], cs[j] = 100.5, 99.6, 99.4
    Ld = [110.0 - i * 0.01 for i in range(n)]
    hi = [101.0] * n
    hi[j - 1] = 101.9
    ok3, d3 = ES.mach7_signal(_ind(n=n, c=cs, h=hi, sma_s=[100.0] * n, sma_l=Ld), j, "SHORT")
    assert ok3 is True and d3["stop"] == 101.9
    assert ES.mach7_signal(_ind(n=n, c=cs, h=hi, sma_s=[100.0] * n, sma_l=L), j, "SHORT")[0] is False   # 상승 추세면 SHORT 아님
    assert ES.mach7_signal(_ind(n=n, c=cs, h=hi, sma_s=[100.0] * n, sma_l=Ld), 100, "SHORT")[0] is False   # 200봉 미만


# ───────── 2% 룰 · 손절 환산 ─────────
def test_two_percent_rule_and_stop_math():
    # 총자산 1,000 · 2% = 20 최대 손실 · 손절폭 4% → 최대 명목 500 → 2x 증거금 250
    assert ES.risk_capped_margin(equity=1000, risk_pct=2, stop_price_pct=4, leverage=2, wanted_margin=100) == (100, False)
    assert ES.risk_capped_margin(equity=1000, risk_pct=2, stop_price_pct=4, leverage=2, wanted_margin=300) == (250, True)
    assert ES.risk_capped_margin(equity=0, risk_pct=2, stop_price_pct=4, leverage=2, wanted_margin=300) == (300, False)   # 자산 모름 = 상한 생략
    assert ES.stop_pct(100, 96, "LONG") == pytest.approx(4.0) and ES.stop_pct(100, 104, "SHORT") == pytest.approx(4.0)
    assert ES.stop_pct(100, 104, "LONG") == 0.0                             # 방향이 어긋나면 0
    assert ES.roi_for_stop(100, 96, "LONG", 2) == pytest.approx(8.0) and ES.roi_for_stop(100, 104, "LONG", 2) is None
    assert ES.clamp_stop_pct(0.1, 0.3, 15) == 0.3 and ES.clamp_stop_pct(40, 0.3, 15) == 15
    ind = _ind(l=[99.0] * 120, h=[101.0] * 120)
    ind.l[95] = 97.5
    assert ES.swing_stop(ind, 100, "LONG", 20) == 97.5 and ES.swing_stop(ind, 100, "SHORT", 20) == 101.0


def test_settings_defaults_and_guards():
    class _DB:
        def __init__(self, kv=None): self.kv = kv or {}
        def get(self, _m, k): return type("R", (), {"value": self.kv[k]})() if k in self.kv else None
    assert ES.mode_of(_DB(), "fujimoto_mode") == "shadow" and ES.mode_of(_DB(), "mach7_mode") == "shadow"   # 기본 = 주문 없음
    assert ES.mode_of(_DB({"fujimoto_mode": "ON"}), "fujimoto_mode") == "on"
    assert ES.mode_of(_DB({"fujimoto_mode": "banana"}), "fujimoto_mode") == "shadow"
    assert ES.sides_of(_DB({"mach7_sides": "long"}), "mach7_sides") == {"LONG"}
    assert ES.stage_ratios(_DB()) == (10.0, 20.0, 70.0) and ES.stage_ratios(_DB({"fujimoto_stage_ratios": "x"})) == (10.0, 20.0, 70.0)
    assert ES.setting_float(_DB({"mach7_min_slope_pct": "NaN"}), "mach7_min_slope_pct") == 0.5
    assert ES.FUJIMOTO_RATIOS == (10.0, 20.0, 70.0) and ES.FUJIMOTO_RISK_PCT == 2.0 and (ES.MACH7_MA_SHORT, ES.MACH7_MA_LONG) == (30, 200)


# ───────── 배선 핀 ─────────
def test_paper_rules_registered_and_indicator_cache():
    from app.services import chart_learning as CL
    from app.services import paper_trading as PT
    keys = {r.key: r for r in CL.RULES}
    for k, side, _lbl, _fn in ES.PAPER_RULES:
        assert k in keys and keys[k].side == side and keys[k].origin == "candidate", k
    assert len(ES.PAPER_RULES) == 8 and CL.LABEL_VERSION == 4
    assert {r.key for r in PT.RULES} >= {k for k, *_ in ES.PAPER_RULES}     # 가상매매도 같은 레지스트리
    # 같은 시리즈(같은 배열 객체)면 지표를 한 번만 계산한다
    n = 300
    c = [100.0 + (i % 7) * 0.1 for i in range(n)]
    h = [x + 0.5 for x in c]
    lo = [x - 0.5 for x in c]

    class _Ctx:
        def __init__(self, j): self.j, self.c, self.h, self.l, self.rsi14 = j, c, h, lo, ES.rsi(c)
    ES._IND_CACHE.clear()
    a = ES._ind_of(_Ctx(250))
    b = ES._ind_of(_Ctx(251))
    assert a is b and len(ES._IND_CACHE) == 1
    for _k, _s, _l, fn in ES.PAPER_RULES:
        assert isinstance(fn(_Ctx(260)), bool)                              # 평탄 시리즈에서 예외 없이 bool


def test_worker_and_wiring_pins():
    wk = (APP / "workers" / "external_strategies_worker.py").read_text(encoding="utf-8")
    for pin in ("create_surge_position(", 'mode="preserve"', "bars = kl[:-1]", "_k_last(sym)", "prefix=ES.FUJIMOTO_PREFIX, stype=ES.FUJIMOTO_TYPE",
                "prefix=ES.MACH7_PREFIX, stype=ES.MACH7_TYPE", "template_prefix=prefix", 'if fm == "shadow":', 'if mm == "shadow":', "roi_for_stop("):
        assert pin in wk, pin
    sr = (APP / "workers" / "scheduler_runner.py").read_text(encoding="utf-8")
    assert 'id="external_strategies"' in sr and "run_external_strategies_once" in sr and "IntervalTrigger(seconds=60)" in sr
    from app.services.single_entry_guard import SINGLE_ENTRY_STRATEGY_TYPES, SINGLE_ENTRY_TEMPLATE_PREFIXES
    assert {ES.FUJIMOTO_TYPE, ES.MACH7_TYPE} <= set(SINGLE_ENTRY_STRATEGY_TYPES)
    assert {ES.FUJIMOTO_PREFIX, ES.MACH7_PREFIX} <= set(SINGLE_ENTRY_TEMPLATE_PREFIXES)
    chk = (ROOT / "scripts" / "verify_fix364_deploy.py").read_text(encoding="utf-8")
    assert "def check_external_strategies()" in chk and "\n    check_external_strategies()\n" in chk
    from app.workers import external_strategies_worker as W
    assert callable(W.run_external_strategies_once) and W.MIN_BARS >= 205
