"""Fix 475 정상 추세 눌림 LONG(대형) · coin_mcap · 공용 루프 거르기 칸 / Fix 476 세력 그림 표시."""
from __future__ import annotations

import json
import math

from app.services import coin_mcap as CM
from app.services import pump_profile as PP
from app.services import trend_pullback as TP

DAY = 86_400_000


def _bars(closes, lows=None, highs=None):
    out = []
    for i, c in enumerate(closes):
        lo = lows[i] if lows else c * 0.99
        hi = highs[i] if highs else c * 1.01
        out.append([i * DAY, str(c), str(hi), str(lo), str(c), "1000", (i + 1) * DAY - 1, str(c * 1000)])
    return out


def _uptrend(n=160, start=100.0, rate=0.006):
    """완만한 상승(하루 0.6%) → 마지막 날 저가가 중단까지 눌림."""
    c = [start * (1 + rate) ** i for i in range(n)]
    lows = [x * 0.99 for x in c]
    bars = _bars(c, lows)
    mid = sum(c[-20:]) / 20
    bars[-1][3] = str(mid * 0.995)                     # 저가 ≤ 중단
    return bars


class _R:
    def __init__(self):
        self.d = {}

    def get(self, k):
        return self.d.get(k)

    def setex(self, k, ttl, v):
        self.d[k] = v


def test_signal_ok_and_stop_range():
    b = _uptrend()
    ok, d = TP.evaluate(b, len(b) - 1, "LONG")
    assert ok, d
    e = float(b[-1][4])
    assert 0.03 <= 1 - d["stop"] / e <= 0.15 + 1e-9 and d["target"] > e


def test_each_condition_breaks():
    b = _uptrend()
    j = len(b) - 1
    assert not TP.evaluate(b, j, "SHORT")[0]
    hi = [dict(enumerate(x)) for x in b]
    # ⑤ 안 눌림
    b5 = [list(x) for x in b]
    b5[-1][3] = str(float(b5[-1][4]) * 1.05)
    assert TP.evaluate(b5, j, "LONG")[1]["why"] == "중단까지 안 눌림"
    # ④ 가파름 (하루 3%)
    bf = _uptrend(rate=0.03)
    assert "가파름" in TP.evaluate(bf, j, "LONG")[1]["why"]
    # ③ 랠리 부족 (하루 0.05%)
    bs = _uptrend(rate=0.0005)
    assert not TP.evaluate(bs, j, "LONG")[0]
    # ⑥ 중단 위 마감 요구
    p = TP.params_from(lambda k: "1" if k == "trpb_require_hold_mid" else TP.SETTINGS[k][0])
    bh = [list(x) for x in b]
    bh[-1][4] = str(float(bh[-1][3]))                  # 종가 = 저가(중단 아래)
    assert TP.evaluate(bh, j, "LONG", p)[1].get("why") in ("중단 아래 마감", "중단 하락·평평") or not TP.evaluate(bh, j, "LONG", p)[0]
    assert hi  # noqa: B018


def test_no_future_reads():
    b = _uptrend()
    j = len(b) - 6
    r1 = TP.evaluate(b, j, "LONG")
    b2 = [list(x) for x in b]
    for k in range(j + 1, len(b2)):
        b2[k] = [b2[k][0], "1", "1e9", "1e-9", "1", "1", b2[k][6], "1"]
    assert TP.evaluate(b2, j, "LONG") == r1


def test_bad_input_no_exception():
    assert not TP.evaluate([], 0, "LONG")[0]
    b = _uptrend()
    b[-3][4] = "nan"
    assert TP.evaluate(b, len(b) - 1, "LONG")[1]["why"] == "값 이상"
    assert not TP.evaluate([["x"]] * 200, 199, "LONG")[0]


def test_params_bounds():
    p = TP.params_from(lambda k: "garbage")
    assert p["min_mcap"] == 1e9 and math.isclose(p["min_gain"], 0.30) and math.isclose(p["max_speed"], 0.01) and p["hold_mid"] is False
    assert TP.params_from(lambda k: "99999" if k == "trpb_max_speed_pct" else TP.SETTINGS[k][0])["max_speed"] == 0.01
    assert TP.SETTINGS["trpb_mode"][0] == "shadow"


def test_paper_rules_big_needs_mcap(monkeypatch):
    b = _uptrend()

    class Ctx:
        kl1d = b
        kl15 = None
    monkeypatch.setattr(TP, "DAILY_FRESH", lambda ctx: True)
    rules = {k: fn for k, _s, _l, fn in TP.PAPER_RULES}
    TP.set_paper_symbol("BTCUSDT")
    monkeypatch.setattr(CM, "get", lambda s, redis=None: None)
    assert rules["trpb_long"](Ctx) and not rules["trpb_long_big"](Ctx)
    monkeypatch.setattr(CM, "get", lambda s, redis=None: 5e8)
    assert not rules["trpb_long_big"](Ctx)
    monkeypatch.setattr(CM, "get", lambda s, redis=None: 5e9)
    assert rules["trpb_long_big"](Ctx)
    monkeypatch.setattr(TP, "DAILY_FRESH", lambda ctx: False)
    assert not rules["trpb_long"](Ctx) and not rules["trpb_long_big"](Ctx)
    TP.set_paper_symbol(None)


def test_symbol_ok(monkeypatch):
    p = TP.params_from()
    monkeypatch.setattr(CM, "get", lambda s, redis=None: None)
    assert TP.symbol_ok("XUSDT", p) == (False, "시총 모름")
    monkeypatch.setattr(CM, "get", lambda s, redis=None: 2e9)
    assert TP.symbol_ok("XUSDT", p)[0]


def _page(n, start=0, dup=None):
    rows = [{"symbol": f"c{start + i}", "market_cap": 1e9 - (start + i), "fully_diluted_valuation": 2e9} for i in range(n)]
    if dup:
        rows.append(dup)
    return rows


def test_coin_mcap_refresh_retry_dup_and_min():
    calls = {"n": 0}

    def fetch(url):
        page = int(url.rsplit("=", 1)[1])
        calls["n"] += 1
        if page == 2 and calls.setdefault("p2", 0) < 2:
            calls["p2"] += 1
            raise OSError("429")
        if page == 3:
            return []                                           # 빈 쪽이 나와도 끝까지 본다
        dup = {"symbol": "c1", "market_cap": 5e12, "fully_diluted_valuation": 1e13} if page == 8 else None
        return _page(60, start=page * 100, dup=dup)
    r = _R()
    st = CM.refresh(r, fetch, sleep=lambda s: None)
    assert st["saved"] and st["pages_fail"] == 0 and st["symbols"] >= 300
    data = json.loads(r.d[CM.KEY])
    assert data["C1"]["mcap"] == 5e12 and math.isclose(data["C1"]["float"], 0.5)
    # 300 미만 = 저장 안 함, 이전 값 유지
    r2 = _R()
    r2.d[CM.KEY] = "old"
    st2 = CM.refresh(r2, lambda url: _page(10), sleep=lambda s: None)
    assert not st2["saved"] and r2.d[CM.KEY] == "old"


def test_coin_mcap_page_fail_skipped():
    def fetch(url):
        if url.endswith("=5"):
            raise OSError("down")
        return _page(60, start=int(url.rsplit("=", 1)[1]) * 100)
    st = CM.refresh(_R(), fetch, sleep=lambda s: None)
    assert st["pages_fail"] == 1 and st["saved"]


def test_base_of_and_get():
    assert CM.base_of("1000PEPEUSDT") == "PEPE" and CM.base_of("1000000MOGUSDT") == "MOG" and CM.base_of("BTCUSDT") == "BTC"
    r = _R()
    r.d[CM.KEY] = json.dumps({"PEPE": {"mcap": 3e9, "fdv": 3e9, "float": 1.0}})
    CM._LOCAL.clear()
    assert CM.get("1000PEPEUSDT", r) == 3e9 and CM.get("NOPEUSDT", r) is None

    class Bad:
        def get(self, k):
            raise RuntimeError("down")
    assert CM.get("BTCUSDT", Bad()) is None


def test_family_loop_symbol_ok_hook():
    from app.workers import ext_family_loop as FL
    from app.workers import external_strategies_worker as W
    fam = next(f for f in W.FAMILIES if f.key == "trpb")
    assert fam.mod is TP and fam.force_shadow and fam.symbol_ok is TP.symbol_ok
    src = open(FL.__file__, encoding="utf-8").read()
    assert "fam.symbol_ok(sym, p)" in src and src.index("fam.symbol_ok(sym, p)") < src.index("ext._closed_bars(")


def test_wiring():
    from app.services import auto_family_registry as AF, chart_learning as CL, external_strategies as ES, single_entry_guard as SG
    assert {"trpb_long", "trpb_long_big"} <= {r.key for r in CL.RULES}
    assert "trpb_mode" in ES.SETTINGS and ES.SETTINGS["trpb_mode"][0] == "shadow"
    assert "trend_pullback" in SG.SINGLE_ENTRY_STRATEGY_TYPES and "TRPB" in SG.SINGLE_ENTRY_TEMPLATE_PREFIXES
    assert AF.family_for(strategy_type="trend_pullback", template_name=None, entry_origin=None).key == "trpb"


# ───────── Fix 476 세력 그림 표시 ─────────
def test_pump_classify_p3_and_next_day():
    c = [10.0] * 120 + [13.5, 12.0]                 # 어제 +35% 급등 · 오늘 음봉
    b = _bars(c)
    pr = PP.classify(b)
    assert "p3" in pr["tags"] and "다음 날 음봉" in pr["reasons"][0]


def test_pump_classify_p1_p2_whale():
    p1 = PP.classify(_uptrend())
    assert "p1" in p1["tags"]
    steep = [12.0 - 0.02 * i for i in range(100)] + [10 * 1.06 ** i for i in range(1, 15)] + [21.0] * 6   # 바닥 바로 뒤 14일 하루 6% (+126%)
    sb = _bars(steep)
    for k in range(100, 114):
        sb[k][7] = str(float(sb[k][7]) * 20)                     # 랠리 중 거래대금 ×20
    p2 = PP.classify(sb)
    assert "p2" in p2["tags"]
    w = PP.classify(_bars([10.0] * 120), mcap=1e8, flt=0.3)
    assert w["tags"] == ["whale"]
    assert PP.badge(w)["color"] == "purple" and PP.badge({"tags": []}) is None
    assert PP.badge({"tags": ["p1", "p3", "whale"], "reasons": []})["main"] == "p3"


def test_pump_build_skips_open_bar_and_short():
    import time as _t
    now = int(_t.time() * 1000)
    b = _bars([10.0] * 121 + [14.0])
    b[-1][6] = now + DAY                              # 아직 안 닫힌 봉(급등) → 빼야 함
    out = PP.build(["AUSDT", "BUSDT"], lambda s: b if s == "AUSDT" else [], lambda s: None, sleep=0)
    assert "AUSDT" not in out


def test_pump_profiles_read_fail_safe():
    class Bad:
        def get(self, k):
            raise RuntimeError
    PP._MEM.update(at=0.0, data={})
    assert PP.profiles(Bad()) == {}
    r = _R()
    r.d[PP.KEY] = json.dumps({"XUSDT": {"tags": ["p3"], "reasons": ["r"]}})
    PP._MEM.update(at=0.0, data={})
    assert PP.badges_for(["xusdt", "YUSDT"], r)["XUSDT"]["label"].startswith("③")


def test_future_garbage_not_parsed():
    """j 뒤 봉이 쓰레기여도 판정이 같다(파싱도 안 함 — Gemini 심판 1차)."""
    b = _uptrend()
    j = len(b) - 6
    r1 = TP.evaluate(b, j, "LONG")
    b2 = [list(x) for x in b]
    for k in range(j + 1, len(b2)):
        b2[k] = ["x", "invalid", None, "bad", "?", None]
    assert TP.evaluate(b2, j, "LONG") == r1
    assert TP.params_from(lambda k: "True" if k == "trpb_require_hold_mid" else TP.SETTINGS[k][0])["hold_mid"] is True
