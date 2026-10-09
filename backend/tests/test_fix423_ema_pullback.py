"""Fix 423 — EMA 추세 눌림 (사장님 첨부 YAML Trading_Rules). 합성 시세로 조건 하나하나가 실제로 신호를 좌우하는지 본다."""
from __future__ import annotations

import pathlib

import pytest

from app.services import ema_pullback as EP
from app.services import external_strategies as ES

N = 260


def uptrend_with_pullback(*, vol_mult=2.0, touch=True, confirm=True):
    """완만한 상승(정배열) → 마지막 4봉 EMA20 까지 눌림 → 마지막 봉 반등 + 거래량."""
    c = [100.0 * (1.003 ** i) for i in range(N - 5)]
    top = c[-1]
    for k in range(1, 5):                       # 눌림 4봉: 조금씩 내려온다
        c.append(top * (1 - 0.002 * k))
    c.append(c[-1] * (1.006 if confirm else 0.999))   # 확정봉
    e20 = EP.emas(c)[EP.EMA_MID]
    h = [x * 1.001 for x in c]
    lo = [x * 0.999 for x in c]
    if touch:
        for i in range(N - 5, N - 1):           # 눌림 구간 저가가 EMA20 에 닿는다
            lo[i] = min(lo[i], e20[i] * 0.9995)
    v = [100.0] * N
    v[-1] = 100.0 * vol_mult
    return c, h, lo, v


def mirror(c, h, lo, v, k=1000.0):
    """가격 축 뒤집기 — EMA 도 선형이라 그대로 뒤집힌다 → 하락 추세 되돌림."""
    return [k - x for x in c], [k - x for x in lo], [k - x for x in h], v


def test_long_signal_all_conditions():
    c, h, lo, v = uptrend_with_pullback()
    ok, d = EP.signal(c, h, lo, v, N - 1, "LONG")
    assert ok, d
    assert d["trend"] and d["align"] and d["pullback"] and d["volume"]
    assert d["stop"] == min(lo[-10:]) and d["stop"] < c[-1]          # 손절 = 최근 10봉 박스 저점
    assert d["macro"] is True and d["vol_ratio"] == pytest.approx(2.0)


@pytest.mark.parametrize("kw, flag", [({"vol_mult": 1.0}, "volume"), ({"touch": False}, "pullback"),
                                      ({"confirm": False}, "pullback")])
def test_each_condition_matters(kw, flag):
    c, h, lo, v = uptrend_with_pullback(**kw)
    ok, d = EP.signal(c, h, lo, v, N - 1, "LONG")
    assert not ok and not d[flag]


def test_long_rule_never_fires_on_downtrend():
    c, h, lo, v = mirror(*uptrend_with_pullback())
    assert EP.signal(c, h, lo, v, N - 1, "LONG")[0] is False          # 「LONG ONLY」 는 상승 추세에서만


def test_short_is_mirror_of_long():
    c, h, lo, v = mirror(*uptrend_with_pullback())
    ok, d = EP.signal(c, h, lo, v, N - 1, "SHORT")
    assert ok, d
    assert d["stop"] == max(h[-10:]) and d["stop"] > c[-1]
    assert EP.signal(*uptrend_with_pullback(), N - 1, "SHORT")[0] is False


def test_short_data_and_bad_side_are_safe():
    c, h, lo, v = uptrend_with_pullback()
    assert EP.signal(c[:100], h[:100], lo[:100], v[:100], 99, "LONG")[0] is False   # EMA200 데이터 부족
    assert EP.signal(c, h, lo, v, N - 1, "BOTH")[0] is False
    zero_v = [0.0] * N
    assert EP.signal(c, h, lo, zero_v, N - 1, "LONG")[0] is False                   # 평균 거래량 0 → 거래량 확인 불가


def test_no_lookahead():
    """j 봉 판정은 j 이후 봉을 보지 않는다 — 뒤에 아무 봉이나 붙여도 같은 결과."""
    c, h, lo, v = uptrend_with_pullback()
    base = EP.signal(c, h, lo, v, N - 1, "LONG")
    c2, h2, lo2, v2 = c + [1.0] * 5, h + [1.0] * 5, lo + [1.0] * 5, v + [9e9] * 5
    assert EP.signal(c2, h2, lo2, v2, N - 1, "LONG") == base


def test_confluence_is_recorded_not_traded():
    c, h, lo, v = uptrend_with_pullback()
    _ok, d = EP.signal(c, h, lo, v, N - 1, "LONG")
    assert "confluence" in d and "fib" in d                          # 증액(30~50%)은 기록만 — 1차 버전
    src = (pathlib.Path(EP.__file__).resolve().parents[1] / "workers" / "external_strategies_worker.py").read_text(encoding="utf-8")
    blk = src[src.index("EMA 추세 눌림 (Fix 423)"):]
    blk = blk[:blk.index("except Exception as e")]
    assert "add_position_now" not in blk and "_add_stage" not in blk  # 증액 주문 경로 없음


def test_settings_merged_default_shadow_and_params():
    for k in EP.SETTINGS:
        assert k in ES.SETTINGS
    assert ES.SETTINGS["emapb_mode"][0] == "shadow"
    p = EP.params_from(lambda k: {"emapb_vol_mult": "abc"}.get(k, EP.SETTINGS[k][0]))
    assert p["vol_mult"] == 1.2                                      # 잘못된 값 = 기본값


def test_registered_everywhere():
    from app.services import chart_learning as CL
    from app.services.auto_control import LINE_ORDER
    from app.services.auto_family_registry import family_for
    from app.services.single_entry_guard import SINGLE_ENTRY_STRATEGY_TYPES, SINGLE_ENTRY_TEMPLATE_PREFIXES
    keys = {r.key for r in CL.RULES}
    assert {"emapb_long", "emapb_short"} <= keys
    assert any("emapb" in fams for _t, fams in LINE_ORDER)
    assert family_for(strategy_type=EP.STYPE, template_name=None, entry_origin=None).key == "emapb"
    assert EP.STYPE in SINGLE_ENTRY_STRATEGY_TYPES and EP.PREFIX in SINGLE_ENTRY_TEMPLATE_PREFIXES


def test_worker_block_pins():
    src = (pathlib.Path(EP.__file__).resolve().parents[1] / "workers" / "external_strategies_worker.py").read_text(encoding="utf-8")
    blk = src[src.index("EMA 추세 눌림 (Fix 423)"):]
    blk = blk[:blk.index("except Exception as e")]
    assert "sym not in act_ep" in blk                                 # 1회 진입 — 보유 중이면 건너뜀
    assert '_rget(r, _k_cool("emapb", sym))' in blk                   # 심볼 쿨다운
    assert 'if em == "shadow":' in blk and "_shadow(r, stat, \"emapb\"" in blk
    assert "prefix=EP.PREFIX, stype=EP.STYPE" in blk and 'risk_key="emapb_risk_pct"' in blk
    assert 'em == "off"' in src[:src.index("EMA 추세 눌림 (Fix 423)")]   # 세 모드 모두 off 면 일찍 끝남


# ── 교차 감사 반영 ──────────────────────────────────────────────────────
@pytest.mark.parametrize("bad", ["nan", "inf", "-1", "0", "1e9", "x", None])
def test_bad_settings_fall_back(bad):
    p = EP.params_from(lambda k: bad if k == "emapb_vol_mult" else EP.SETTINGS[k][0])
    assert p["vol_mult"] == 1.2                                      # 음수·0 이면 「거래량 0 도 통과」 → 막는다


def test_min_bars_covers_box_window():
    p = EP.params_from(lambda k: "90" if k == "emapb_box_bars" else EP.SETTINGS[k][0])
    assert EP.min_bars(p) >= 90 + 5


def test_ema_cache_identity_not_just_id():
    from types import SimpleNamespace as NS
    c1, h, lo, v = uptrend_with_pullback()
    ctx1 = NS(c=c1, h=h, l=lo, v=v, j=N - 1)
    e1 = EP._emas_of(ctx1)
    c2 = [x * 2 for x in c1]
    ctx2 = NS(c=c2, h=h, l=lo, v=v, j=N - 1)
    EP._EMA_CACHE[(id(c2), len(c2))] = (c1, e1)                      # 같은 키에 다른 리스트의 값이 남아 있는 상황
    assert EP._emas_of(ctx2)[EP.EMA_MID][-1] == pytest.approx(EP.emas(c2)[EP.EMA_MID][-1])


def test_paper_uses_live_settings():
    old = dict(EP.PAPER_PARAMS)
    try:
        EP.set_paper_params(lambda k: "9" if k == "emapb_vol_mult" else EP.SETTINGS[k][0])
        from types import SimpleNamespace as NS
        c, h, lo, v = uptrend_with_pullback(vol_mult=2.0)
        EP._EMA_CACHE.clear()
        assert EP._r_long(NS(c=c, h=h, l=lo, v=v, j=N - 1)) is False  # 운영에서 9배로 올리면 가상도 같이 막힌다
    finally:
        EP.PAPER_PARAMS = old
