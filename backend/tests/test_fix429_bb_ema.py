"""Fix 429 — 존 볼린저 「볼린저 밴드 + EMA」 (사장님 첨부 bollinger_ema_trading_strategy.md) — 외부 전략 4번째 가족, 일봉, 기본 shadow."""
from __future__ import annotations

import math
import pathlib
from types import SimpleNamespace as NS

import pytest

from app.services import bb_ema as BE
from app.services import external_strategies as ES
from app.services.ema_pullback import MS_15M, MS_DAY

APP = pathlib.Path(BE.__file__).resolve().parents[1]


def test_source_numbers_and_defaults():
    assert (BE.EMA_LONG, BE.EMA_MID, BE.BB_N, BE.BB_K) == (200, 90, 30, 2.0)    # 출처 verbatim
    assert ES.SETTINGS["bbema_mode"][0] == "shadow" and ES.SETTINGS["bbema_interval"][0] == "1d"
    for k in BE.SETTINGS:
        assert k in ES.SETTINGS


def test_bands_match_pandas_definition():
    """출처 슈도코드 rolling(30).std() = 표본 표준편차(ddof=1), ewm(adjust=False) = 첫 값 시드."""
    c = [float(i % 7 + i * 0.1) for i in range(40)]
    mid, sd = BE.bands(c)
    w = c[-30:]
    m = sum(w) / 30
    assert mid[-1] == pytest.approx(m)
    assert sd[-1] == pytest.approx(math.sqrt(sum((x - m) ** 2 for x in w) / 29))
    assert mid[28] is None and mid[29] is not None
    e = BE.ema([1.0, 2.0, 3.0], 3)
    assert e[0] == 1.0 and e[1] == pytest.approx(1.5)


def _trend_series(n=400, breakout=1.06, squeeze=True):
    """완만한 상승(EMA 정배열) → 마지막 몇십 봉 좁은 횡보(수축) → 마지막 봉 상단 돌파(확장)."""
    c = [100 * (1.003 ** i) for i in range(n - 25)]
    base = c[-1]
    amp = 0.002 if squeeze else 0.03
    for i in range(24):
        c.append(base * (1 + amp * (1 if i % 2 else -1)))
    c.append(base * breakout)
    h = [x * 1.002 for x in c]
    lo = [x * 0.998 for x in c]
    return c, h, lo


def test_trend_long_signal():
    c, h, lo = _trend_series()
    ok, d = BE.trend_signal(c, h, lo, len(c) - 1, "LONG")
    assert ok, d
    assert d["trend"] and d["expanding"] and d["squeeze"] and d["breakout"]
    assert d["stop"] < c[-1]                                          # 손절 = 중단선(아래)


def test_trend_needs_each_condition():
    c, h, lo = _trend_series(breakout=1.0005)
    assert not BE.trend_signal(c, h, lo, len(c) - 1, "LONG")[1]["breakout"]
    # 변동성이 계속 커지는 상승(최근 밴드 폭이 가장 넓다) = 수축이 없었다 → 상단 돌파여도 신호 아님
    n = 400
    c2 = [100 * (1.003 ** i) * (1 + (0.0002 * i) * (1 if i % 2 else -1)) for i in range(n - 1)]
    c2.append(c2[-1] * 1.2)
    h2, lo2 = [x * 1.002 for x in c2], [x * 0.998 for x in c2]
    ok2, d2 = BE.trend_signal(c2, h2, lo2, len(c2) - 1, "LONG")
    assert not ok2 and not d2["squeeze"]                               # 수축 없이 확장 = 신호 아님
    assert BE.trend_signal(c, h, lo, len(c) - 1, "SHORT")[0] is False  # 상승 추세에 SHORT 없음


def test_trend_short_mirror():
    c, h, lo = _trend_series()
    k = 10_000.0
    mc, mh, ml = [k - x for x in c], [k - x for x in lo], [k - x for x in h]
    ok, d = BE.trend_signal(mc, mh, ml, len(mc) - 1, "SHORT")
    assert ok, d


def _range_series(n=400, pierce=2.5, rev_close=True):
    """횡보(밴드 안) → 어제 저가가 하단 2σ 를 pierce σ 만큼 찌름 → 오늘 밴드 안 반등."""
    import random
    rnd = random.Random(7)
    c = [100 + rnd.uniform(-1, 1) for _ in range(n - 2)]
    mid, sd = BE.bands(c)
    m, s = mid[-1], sd[-1]
    c.append(m - 1.5 * s)                                              # 어제 종가는 밴드 안
    c.append(m - 1.0 * s if rev_close else m - 1.8 * s)               # 오늘 반등
    h = [x + 0.3 for x in c]
    lo = [x - 0.3 for x in c]
    lo[-2] = m - pierce * s                                            # 어제 저가가 2σ 를 찌름
    return c, h, lo


def test_reversal_long_inside_band():
    c, h, lo = _range_series(pierce=2.5)
    ok, d = BE.reversal_signal(c, h, lo, len(c) - 1, "LONG")
    assert ok, d
    assert d["stop"] < min(lo[-2:]) and d["target"] > c[-1]            # 손절 = 리버절 밴드 아래 · 목표 = 반대편 밴드


def test_reversal_forbidden_when_reversal_band_broken():
    c, h, lo = _range_series(pierce=4.0)                               # 리버절 3σ 를 뚫음 = 추세 연장 → 반전 금지
    ok, d = BE.reversal_signal(c, h, lo, len(c) - 1, "LONG")
    assert not ok and not d["held"]


def test_reversal_can_be_disabled():
    c, h, lo = _range_series()
    p = BE.params_from(lambda k: "0" if k == "bbema_reversal_enabled" else BE.SETTINGS[k][0])
    assert BE.reversal_signal(c, h, lo, len(c) - 1, "LONG", p)[0] is False


@pytest.mark.parametrize("key, bad", [("bbema_rev_k", "1.5"), ("bbema_squeeze_pct", "nan"), ("bbema_squeeze_lookback", "x")])
def test_bad_settings_fall_back(key, bad):
    p = BE.params_from(lambda k: bad if k == key else BE.SETTINGS[k][0])
    assert p == BE.params_from()


def test_no_lookahead():
    c, h, lo = _trend_series()
    j = len(c) - 1
    base = BE.trend_signal(c, h, lo, j, "LONG")
    c2, h2, lo2 = c + [1.0] * 5, h + [1.0] * 5, lo + [1.0] * 5
    assert BE.trend_signal(c2, h2, lo2, j, "LONG")[0] == base[0]


def test_paper_daily_window():
    from app.services import ema_pullback as EP
    c, h, lo = _trend_series()
    day0 = 1_700_000_000_000 // MS_DAY * MS_DAY
    k1 = [[day0 + i * MS_DAY, c[i], h[i], lo[i], c[i], 1.0] for i in range(len(c))]
    dc = int(k1[-1][0]) + MS_DAY
    assert BE._r_tl(NS(kl15=[[dc - MS_15M]], kl1d=k1)) is True
    assert BE._r_tl(NS(kl15=[[dc + 4 * MS_15M]], kl1d=k1)) is False   # 1시간 창 밖
    EP.set_paper_daily_done(True)
    try:
        assert BE._r_tl(NS(kl15=[[dc]], kl1d=k1)) is False             # 오늘 이미 판정
    finally:
        EP.set_paper_daily_done(False)


def test_registered_everywhere():
    from app.services import chart_learning as CL
    from app.services.auto_control import LINE_ORDER
    from app.services.auto_family_registry import family_for
    from app.services.single_entry_guard import SINGLE_ENTRY_STRATEGY_TYPES, SINGLE_ENTRY_TEMPLATE_PREFIXES
    assert {k for k, *_ in BE.PAPER_RULES} <= {r.key for r in CL.RULES}
    assert any("bbema" in fams for _t, fams in LINE_ORDER)
    assert family_for(strategy_type=BE.STYPE, template_name=None, entry_origin=None).key == "bbema"
    assert BE.STYPE in SINGLE_ENTRY_STRATEGY_TYPES and BE.PREFIX in SINGLE_ENTRY_TEMPLATE_PREFIXES


def test_worker_loop_pins():
    src = (APP / "workers" / "external_strategies_worker.py").read_text(encoding="utf-8")
    blk = src[src.index("볼린저 EMA (Fix 429"):]
    blk = blk[:blk.index("r.setex(CYCLE_KEY")]
    assert "if sym in act_bb:" in blk and 'ES.setting(db, "bbema_interval")' in blk and "last_key=lk" in blk
    assert blk.index("r.setex(lk, bb_ttl, str(ts))") > blk.index("BE.signal(")    # 처리 뒤 기록
    assert 'if bm == "shadow":' in blk and "prefix=BE.PREFIX, stype=BE.STYPE" in blk
    assert 'bm = ES.mode_of(db, "bbema_mode")' in src and 'em == "off" and bm == "off"' in src
    paper = (APP / "workers" / "paper_trading_worker.py").read_text(encoding="utf-8")
    assert "BE.set_paper_params(lambda k: ES.setting(db, k))" in paper


def test_expansion_uses_absolute_width():
    """교차 감사: 출처 슈도코드 = 절대 폭(상단−하단) 비교. 중단이 오르며 σ 가 조금 커지면 확장이다."""
    import inspect
    src = inspect.getsource(BE.trend_signal)
    assert 's_now > s_prev' in src and 'd["expanding"] = s_now is not None' in src


def test_on_mode_runs_as_shadow_and_interval_forced_daily():
    src = (APP / "workers" / "external_strategies_worker.py").read_text(encoding="utf-8")
    i = src.index('bm = ES.mode_of(db, "bbema_mode")')
    assert 'if bm == "on":' in src[i:i + 600] and 'bm = "shadow"' in src[i:i + 600]   # 전용 청산 전까지 실주문 금지
    j = src.index('bb_iv = ES.setting(db, "bbema_interval")')
    assert 'if bb_iv != "1d":' in src[j:j + 300] and 'bb_iv = "1d"' in src[j:j + 300]
