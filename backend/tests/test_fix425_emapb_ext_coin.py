"""Fix 425 — 사장님 10/09: ① EMA20 에서 멀리 달아난 날은 진입 신호 아님(기본 10%) ② 코인 무기한만 (주식·금·원유 TradFi 제외).

배포 첫 알림(10/09 10:17 UTC)에서 OGN 종가가 EMA20 의 약 2배·RLC 1.8배인데 「진입 신호」, GOOGL·NVDA·QQQ·XAU·BZ·KORU 가 감시에 들어왔다.
"""
from __future__ import annotations

import pathlib
from types import SimpleNamespace as NS

import pytest

from app.services import ema_pullback as EP
from app.services import external_strategies as ES

APP = pathlib.Path(EP.__file__).resolve().parents[1]
N = 120


def daily(*, last_jump=1.02):
    c = [100.0 * (1.01 ** i) for i in range(N - 5)]
    top = c[-1]
    for k in range(1, 5):
        c.append(top * (1 - 0.006 * k))
    c.append(c[-1] * last_jump)
    e20 = EP.emas(c)[EP.EMA_MID]
    h = [x * 1.003 for x in c]
    lo = [x * 0.997 for x in c]
    for i in range(N - 5, N - 1):
        lo[i] = min(lo[i], e20[i] * 0.999)
    v = [100.0] * N
    v[-1] = 200.0
    return c, h, lo, v


def test_default_is_owner_value():
    assert ES.SETTINGS["emapb_max_ext_pct"][0] == "10" and ES.SETTINGS["emapb_coin_only"][0] == "1"
    assert EP.params_from()["max_ext_pct"] == 10.0


def test_far_from_ema20_is_not_a_signal():
    c, h, lo, v = daily(last_jump=1.02)
    ok, d = EP.signal(c, h, lo, v, N - 1, "LONG")
    assert ok and d["near"] and d["ext_pct"] < 10
    c2, h2, lo2, v2 = daily(last_jump=1.6)                      # OGN 같은 폭등 확정봉
    ok2, d2 = EP.signal(c2, h2, lo2, v2, N - 1, "LONG")
    assert not ok2 and not d2["near"] and d2["ext_pct"] > 10 and d2["pullback"]   # 다른 조건은 맞아도 막힌다


def test_ext_threshold_is_setting():
    c, h, lo, v = daily(last_jump=1.6)
    p = EP.params_from(lambda k: "100" if k == "emapb_max_ext_pct" else EP.SETTINGS[k][0])
    assert EP.signal(c, h, lo, v, N - 1, "LONG", p)[0] is True
    bad = EP.params_from(lambda k: "-5" if k == "emapb_max_ext_pct" else EP.SETTINGS[k][0])
    assert bad["max_ext_pct"] == 10.0                            # 범위 밖 = 기본값


def test_short_ext_mirror():
    c, h, lo, v = daily(last_jump=1.6)
    k = 10_000.0
    mc, mh, ml = [k - x for x in c], [k - x for x in lo], [k - x for x in h]
    ok, d = EP.signal(mc, mh, ml, v, N - 1, "SHORT")
    assert d["ext_pct"] is not None


@pytest.mark.parametrize("raw, ct, want", [
    ({"underlyingType": "COIN"}, "PERPETUAL", True),
    ({"underlyingType": "EQUITY"}, "TRADIFI_PERPETUAL", False),        # GOOGL·NVDA·QQQ·KORU
    ({"underlyingType": "COMMODITY"}, "TRADIFI_PERPETUAL", False),     # XAU·BZ
    ({"underlyingType": "INDEX"}, "PERPETUAL", False),
    (None, "PERPETUAL", True), (None, "TRADIFI_PERPETUAL", False), ("garbage", None, False),
])
def test_is_coin_row(raw, ct, want):
    assert EP.is_coin_row(raw, ct) is want


def test_coin_symbols_keeps_order_and_fails_open():
    class DB:
        def execute(self, *a, **k):
            return NS(all=lambda: [("BTCUSDT", {"underlyingType": "COIN"}, "PERPETUAL"),
                                   ("XAUUSDT", {"underlyingType": "COMMODITY"}, "TRADIFI_PERPETUAL"),
                                   ("OGNUSDT", {"underlyingType": "COIN"}, "PERPETUAL")])
    assert EP.coin_symbols(DB(), ["XAUUSDT", "OGNUSDT", "BTCUSDT", "NEWUSDT"]) == ["OGNUSDT", "BTCUSDT"]

    class Bad:
        def execute(self, *a, **k):
            raise RuntimeError("db")

        def rollback(self):
            pass
    assert EP.coin_symbols(Bad(), ["XAUUSDT"]) == ["XAUUSDT"]      # 조회 실패 = 거르지 않음(알림 정지 방지)

    class Empty:
        def execute(self, *a, **k):
            return NS(all=lambda: [])
    assert EP.coin_symbols(Empty(), ["XAUUSDT", "BTCUSDT"]) == ["XAUUSDT", "BTCUSDT"]   # 0행 = 거르지 않음 (교차 감사)
    assert EP.coin_only_on(lambda k: "0") is False and EP.coin_only_on(lambda k: "1") is True


def test_paper_symbol_flag_blocks_non_coin():
    c, h, lo, v = daily()
    day0 = 1_760_000_000_000 // EP.MS_DAY * EP.MS_DAY
    kl1d = [[day0 + i * EP.MS_DAY, c[i], h[i], lo[i], c[i], v[i]] for i in range(N)]
    ctx = NS(kl15=[[kl1d[-1][0] + EP.MS_DAY - EP.MS_15M, 0, 0, 0, 0, 0]], kl1d=kl1d, c=[], h=[], l=[], v=[], j=0)
    try:
        EP.set_paper_symbol_ok(True)
        assert EP._r_long(ctx) is True
        EP.set_paper_symbol_ok(False)
        assert EP._r_long(ctx) is False
    finally:
        EP.set_paper_symbol_ok(True)


def test_wired_in_all_three_paths():
    ext = (APP / "workers" / "external_strategies_worker.py").read_text(encoding="utf-8")
    assert "ep_universe = EP.coin_symbols(None, universe)" in ext and "for sym in ep_universe:" in ext
    watch = (APP / "workers" / "emapb_watch_worker.py").read_text(encoding="utf-8")
    assert "universe = EP.coin_symbols(None, universe)" in watch
    paper = (APP / "workers" / "paper_trading_worker.py").read_text(encoding="utf-8")
    assert "_ep_coins = _emapb_coins(db, process_symbols)" in paper and "_EPF.set_paper_symbol_ok(_ep_ok)" in paper
    i_set, i_eval, i_reset = (paper.index("_EPF.set_paper_symbol_ok(_ep_ok)"), paper.index("fired = PT.evaluate_rules(series, j)"),
                              paper.index("_EPF.set_paper_symbol_ok(True)"))
    assert i_set < i_eval < i_reset                                # 심볼마다 설정 → 평가 → 기본값 복구 (교차 감사)
    assert "coin_symbols(None," in ext and "coin_symbols(None," in watch and "coin_symbols(None," in paper   # 조회 전용 세션
    src = (APP / "services" / "ema_pullback.py").read_text(encoding="utf-8")
    blk = src[src.index("def coin_symbols("):src.index("def coin_only_on(")]
    assert ".rollback(" not in blk                                  # 워커 세션을 되돌리지 않는다
