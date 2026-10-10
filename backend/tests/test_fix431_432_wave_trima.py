"""Fix 431 볼린저 중심선 파동 · Fix 432 3중 이평 — 사장님 첨부 전략 2종 (외부 전략 5·6번째 가족, 기본 shadow·실주문 차단)."""
from __future__ import annotations

import math
import pathlib
from types import SimpleNamespace as NS

import pytest

from app.services import bb_wave as BW
from app.services import external_strategies as ES
from app.services import triple_ma as TM

APP = pathlib.Path(BW.__file__).resolve().parents[1]


def _bars(c, v=None, o=None, spread=0.002):
    v = v or [100.0] * len(c)
    o = o or [c[max(0, i - 1)] for i in range(len(c))]
    return [[i * 300_000, o[i], max(o[i], c[i]) * (1 + spread), min(o[i], c[i]) * (1 - spread), c[i], v[i]] for i in range(len(c))]


# ───────── 볼린저 중심선 파동 ─────────
def _wave_series(n=120, confirm=True, vol=300.0):
    """완만한 하락(중심선 하향) → 바닥 → 반등으로 중심선 상향 꺾임 + 돌파 봉 + 확인 봉."""
    c = [100 - 0.15 * i for i in range(n - 10)]
    base = c[-1]
    c += [base - 0.05 * (i % 2) for i in range(7)]          # 바닥 다지기 (중심선 아직 아래로)
    c += [base + 2.5]                                         # 돌파 봉 k
    c += [base + 3.0 if confirm else base - 2.0]              # 확인 봉 j
    v = [100.0] * len(c)
    v[-2] = vol
    return c, v


def test_wave_source_numbers():
    assert (BW.BB_N, BW.BB_K, BW.MAX_TRIES, BW.SL_MIN_PCT, BW.SL_MAX_PCT) == (20, 2.0, 3, 3.0, 5.0)
    assert ES.SETTINGS["bbwave_mode"][0] == "shadow" and ES.SETTINGS["bbwave_sides"][0] == "LONG"
    assert ES.SETTINGS["bbwave_interval"][0] == "5m"


def test_wave_bands_match_pandas():
    c = [float(i % 5 + i * 0.3) for i in range(30)]
    mid, sd = BW.bands(c)
    w = c[-20:]
    m = sum(w) / 20
    assert mid[-1] == pytest.approx(m) and sd[-1] == pytest.approx(math.sqrt(sum((x - m) ** 2 for x in w) / 19))


def test_wave_long_signal_and_conditions():
    c, v = _wave_series()
    ok, d = BW.evaluate(_bars(c, v), len(c) - 1, "LONG")
    assert d["cross"] and d["confirm"] and d["vol_ok"] and d["tries_ok"]
    assert ok and d["slope_turn"], d
    assert 3.0 <= d["sl_pct"] <= 5.0 and d["stop"] < c[-1]
    c2, v2 = _wave_series(confirm=False)
    assert BW.evaluate(_bars(c2, v2), len(c2) - 1, "LONG")[1]["confirm"] is False     # 가짜 돌파 = 확인 실패
    c3, v3 = _wave_series(vol=50.0)
    assert BW.evaluate(_bars(c3, v3), len(c3) - 1, "LONG")[1]["vol_ok"] is False     # 거래량 부족
    p0 = BW.params_from(lambda k: "0" if k == "bbwave_vol_mult" else BW.SETTINGS[k][0])
    assert BW.evaluate(_bars(c3, v3), len(c3) - 1, "LONG", p0)[1]["vol_ok"] is True  # 0 = 안 봄


def test_wave_tries_block():
    """창 안에서 중심선 돌파가 이미 3번 → 지지력 약화 → 배제."""
    c = [100.0 + (1.5 if (i // 4) % 2 else -1.5) for i in range(80)]
    ok, d = BW.evaluate(_bars(c), len(c) - 1, "LONG")
    assert d.get("tries", 0) >= 3 and d["tries_ok"] is False and not ok


def test_wave_short_mirror_and_no_lookahead():
    c, v = _wave_series()
    k = 1000.0
    mc = [k - x for x in c]
    ok_l, d_l = BW.evaluate(_bars(c, v), len(c) - 1, "LONG")
    ok_s, d_s = BW.evaluate(_bars(mc, v), len(mc) - 1, "SHORT")
    assert (d_l["cross"], d_l["confirm"]) == (d_s["cross"], d_s["confirm"])
    j = len(c) - 1
    more = _bars(c + [1.0] * 5, v + [1.0] * 5)
    assert BW.evaluate(more, j, "LONG")[0] == ok_l


def test_wave_bad_input_safe():
    c, v = _wave_series()
    b = _bars(c, v)
    b[-1][4] = float("nan")
    assert BW.evaluate(b, len(b) - 1, "LONG") == (False, {"why": "값 이상"})
    assert BW.evaluate(b[:10], 9, "LONG")[0] is False
    assert BW.evaluate([["x"]], 0, "LONG")[0] is False


# ───────── 3중 이평 ─────────
def _trima_series(n=300, pull=True):
    """긴 상승(SMA200 우상향·EMA9>SMA20) → 직전 봉 SMA20 아래로 눌림 → 마지막 봉 EMA9 위로 반등."""
    c = [100 * (1.004 ** i) for i in range(n - 2)]
    top = c[-1]
    c.append(top * (0.955 if pull else 1.003))    # 눌림 봉
    c.append(top * 1.012)                          # 반등 봉
    return c


def test_trima_long_signal():
    c = _trima_series()
    ok, d = TM.evaluate(_bars(c), len(c) - 1, "LONG")
    assert d["macro"] and d["pullback"] and d["trigger"], d
    assert ok and d["aligned"] and d["sl_ok"], d
    assert d["stop"] < c[-1]


def test_trima_needs_pullback_and_macro():
    c = _trima_series(pull=False)
    assert TM.evaluate(_bars(c), len(c) - 1, "LONG")[1]["pullback"] is False
    assert TM.evaluate(_bars(_trima_series()), len(c) - 1, "SHORT")[0] is False   # 상승장에 SHORT 없음


def test_trima_indicators_pandas_def():
    c = [1.0, 2.0, 3.0, 4.0]
    e = TM.ema(c, 9)
    assert e[0] == 1.0 and e[1] == pytest.approx(0.2 * 2 + 0.8 * 1)
    s = TM.sma(c, 2)
    assert s[0] is None and s[1] == 1.5 and s[3] == 3.5


def test_trima_no_lookahead_and_bad_input():
    c = _trima_series()
    j = len(c) - 1
    base = TM.evaluate(_bars(c), j, "LONG")[0]
    assert TM.evaluate(_bars(c + [1.0] * 5), j, "LONG")[0] == base
    b = _bars(c)
    b[-3][3] = float("inf")
    assert TM.evaluate(b, j, "LONG")[0] is False
    assert TM.evaluate(_bars(c[:100]), 99, "LONG")[0] is False


@pytest.mark.parametrize("mod,key,bad", [(BW, "bbwave_tries_lookback", "5"), (BW, "bbwave_vol_mult", "nan"),
                                         (TM, "trima_swing_bars", "x"), (TM, "trima_max_sl_pct", "99")])
def test_bad_settings_fall_back(mod, key, bad):
    assert mod.params_from(lambda k: bad if k == key else mod.SETTINGS[k][0]) == mod.params_from()


# ───────── 등록 · 공용 루프 ─────────
def test_registered_everywhere():
    from app.services import chart_learning as CL
    from app.services.auto_control import LINE_ORDER
    from app.services.auto_family_registry import family_for
    from app.services.single_entry_guard import SINGLE_ENTRY_STRATEGY_TYPES, SINGLE_ENTRY_TEMPLATE_PREFIXES
    keys = {r.key for r in CL.RULES}
    for mod, fam in ((BW, "bbwave"), (TM, "trima")):
        assert {k for k, *_ in mod.PAPER_RULES} <= keys
        assert any(fam in fams for _t, fams in LINE_ORDER)
        assert family_for(strategy_type=mod.STYPE, template_name=None, entry_origin=None).key == fam
        assert mod.STYPE in SINGLE_ENTRY_STRATEGY_TYPES and mod.PREFIX in SINGLE_ENTRY_TEMPLATE_PREFIXES
        for k in mod.SETTINGS:
            assert k in ES.SETTINGS


def test_paper_rules_use_15m():
    c = _trima_series()
    assert TM._r_l(NS(kl15=_bars(c)[-260:])) in (True, False)
    assert BW._r_l(NS(kl15=[])) is False


def test_on_forced_to_shadow():
    from app.workers import external_strategies_worker as W
    from app.workers import ext_family_loop as FL
    assert {f.key for f in W.FAMILIES} == {"bbwave", "trima"} and all(f.force_shadow for f in W.FAMILIES)
    fake_es = NS(mode_of=lambda db, k: "on")
    assert FL.mode(fake_es, None, W.FAMILIES[0]) == "shadow"


class _R:
    def __init__(self):
        self.kv = {}

    def setex(self, k, ttl, v):
        self.kv[k] = v


def test_family_loop_shadow_records_after_processing():
    """공용 루프: 신호 → 그림자 기록 + 쿨다운 · 판정 기록 키는 처리 뒤 · 활성 종목 건너뜀 · 실주문 경로 미호출."""
    from app.workers import ext_family_loop as FL
    c, v = _wave_series()
    bars = _bars(c, v)
    calls = {"shadow": [], "enter": 0}
    settings = dict((k, d[0]) for k, d in BW.SETTINGS.items())
    settings["bbwave_vol_mult"] = "0"
    ES_ = NS(setting=lambda db, k: settings[k], setting_float=lambda db, k: float(settings[k]),
             sides_of=lambda db, k: {"LONG"}, clamp_stop_pct=lambda sp, lo, hi: sp, stop_pct=ES.stop_pct)
    BG_ = NS(already_judged=lambda seen, ts: False)
    ext = NS(ES=ES_, BG=BG_, LAST_TTL=3600, INTERVAL_MS={"5m": 300_000, "15m": 900_000},
             _active_by_prefix=lambda db, p: {"BUSYUSDT": object()},
             _closed_bars=lambda *a, **k: (bars, None), _rget=lambda r, k: None, _k_cool=lambda f, s: f"cool:{f}:{s}",
             _size=lambda db, eq, **k: (10.0, False),
             _shadow=lambda r, stat, fam, sym, ts, payload: calls["shadow"].append((fam, sym, payload["side"])),
             _enter=lambda *a, **k: calls.__setitem__("enter", calls["enter"] + 1))
    fam = FL.Family("bbwave", BW, "볼린저파동", ("5m", "15m"), force_shadow="x")
    r = _R()
    stat = {"sig": {}, "miss": {}, "err": 0}
    ok, _ = BW.evaluate(bars, len(bars) - 1, "LONG", BW.params_from(lambda k: settings[k]))
    FL.run(ext, fam, "shadow", db=NS(rollback=lambda: None), r=r, bc=None, stat=stat, universe=["AUSDT", "BUSYUSDT"],
           cycle_now=0, settle_ms=0, incremental=True, equity=None, lev=2, sp_lo=0.3, sp_hi=15, now=NS(isoformat=lambda: "t"))
    assert calls["enter"] == 0 and stat["err"] == 0
    assert FL.k_last("bbwave", "5m", "AUSDT") in r.kv and FL.k_last("bbwave", "5m", "BUSYUSDT") not in r.kv
    assert ok and len(calls["shadow"]) == 1 and stat["sig"]["bbwave_L"] == 1


def test_worker_pins():
    src = (APP / "workers" / "ext_family_loop.py").read_text(encoding="utf-8")
    assert src.index("r.setex(lk, ttl, str(ts))") > src.index("fam.mod.evaluate(")
    assert "prefix=fam.mod.PREFIX, stype=fam.mod.STYPE" in src
    paper = (APP / "workers" / "paper_trading_worker.py").read_text(encoding="utf-8")
    assert "BW.set_paper_params(" in paper and "TM.set_paper_params(" in paper


def test_audit_fixes():
    """교차 감사: 3중 이평 손절가가 진입가 반대편이면 거부 · 파동 반복 세기 창 안의 NaN 도 거부."""
    c = _trima_series()
    b = _bars(c)
    j = len(b) - 1
    for i in range(j - 9, j + 1):
        b[i][3] = c[j] * 1.01                     # 저가 > 종가 (이상 봉)
    ok, d = TM.evaluate(b, j, "LONG")
    assert not ok and d.get("sl_ok") is False
    cw, vw = _wave_series()
    bw = _bars(cw, vw)
    bw[len(bw) - 30][4] = float("nan")
    assert BW.evaluate(bw, len(bw) - 1, "LONG") == (False, {"why": "값 이상"})
