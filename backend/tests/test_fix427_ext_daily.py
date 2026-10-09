"""Fix 427 — 후지모토·마하세븐 일봉 기준 (사장님 10/10 「일봉기준으로 우리 자동매매에서도」)."""
from __future__ import annotations

import pathlib
from types import SimpleNamespace as NS

import pytest

from app.services import external_strategies as ES
from app.services.ema_pullback import MS_15M, MS_DAY

APP = pathlib.Path(ES.__file__).resolve().parents[1]


def test_defaults_daily():
    assert ES.SETTINGS["ext_interval"][0] == "1d"
    assert ES.SETTINGS["fujimoto_cooldown_hours"][0] == "20" and ES.SETTINGS["mach7_cooldown_hours"][0] == "20"
    assert ES.SETTINGS["fujimoto_mode"][0] == "shadow" and ES.SETTINGS["mach7_mode"][0] == "shadow"


def test_worker_uses_per_interval_last_key():
    from app.workers import external_strategies_worker as W
    assert W._k_last_iv("A", "15m") == W._k_last("A")                 # 15m 은 옛 키 그대로 (되돌려도 이어짐)
    assert W._k_last_iv("A", "1d") == "ext:last:1d:A"                 # 15m 기록이 일봉 첫 판정을 막지 않게
    src = pathlib.Path(W.__file__).read_text(encoding="utf-8")
    assert "last_key=_k_last_iv(sym, interval)" in src and "r.setex(_k_last_iv(sym, interval), last_ttl, str(ts))" in src
    assert "last_ttl = max(LAST_TTL, 2 * INTERVAL_MS.get(interval, 0) // 1000)" in src   # 일봉 = 2일 보관


def _series(n=320, up=True):
    c = [100 * (1.004 ** i if up else 0.996 ** i) for i in range(n)]
    return c, [x * 1.01 for x in c], [x * 0.99 for x in c]


def _kl1d(c, h, lo):
    day0 = 1_760_000_000_000 // MS_DAY * MS_DAY
    return [[day0 + i * MS_DAY, c[i], h[i], lo[i], c[i], 1.0] for i in range(len(c))]


def test_paper_daily_view_only_on_day_close():
    c, h, lo = _series()
    k1 = _kl1d(c, h, lo)
    last15 = int(k1[-1][0]) + MS_DAY - MS_15M
    old = ES.PAPER_INTERVAL
    try:
        ES.set_paper_interval("1d")
        vw = ES._view(NS(kl15=[[last15]], kl1d=k1, c=[], h=[], l=[], j=0))
        assert vw is not None and vw[1] == len(k1) - 1
        assert ES._view(NS(kl15=[[last15 - MS_15M]], kl1d=k1, c=[], h=[], l=[], j=0)) is None   # 하루 중간 = 판정 안 함
        assert ES._view(NS(kl15=[[last15 + MS_DAY]], kl1d=k1, c=[], h=[], l=[], j=0)) is None   # 일봉 묵음
        assert ES._r_mach7_long(NS(kl15=[[last15 - MS_15M]], kl1d=k1, c=[], h=[], l=[], j=0)) is False
    finally:
        ES.PAPER_INTERVAL = old


def test_paper_daily_matches_worker_function():
    """가상 규칙 = 운영 판정 함수에 일봉을 넣은 것과 같다."""
    c, h, lo = _series()
    k1 = _kl1d(c, h, lo)
    last15 = int(k1[-1][0]) + MS_DAY - MS_15M
    ctx = NS(kl15=[[last15]], kl1d=k1, c=[], h=[], l=[], j=0)
    ind = ES.compute(c, h, lo)
    j = len(c) - 1
    old = ES.PAPER_INTERVAL
    try:
        ES.set_paper_interval("1d")
        assert ES._r_mach7_long(ctx) == ES.mach7_signal(ind, j, "LONG", min_slope_pct=float(ES.SETTINGS["mach7_min_slope_pct"][0]))[0]
        for st, fn in ((1, ES._r_fujimoto_l1), (2, ES._r_fujimoto_l2), (3, ES._r_fujimoto_l3)):
            assert fn(ctx) == ES.fujimoto_stages(ind, j, "LONG", div_lookback=30)[st]
    finally:
        ES.PAPER_INTERVAL = old


def test_unsupported_interval_turns_paper_off():
    old = ES.PAPER_INTERVAL
    try:
        ES.set_paper_interval("4h")
        assert ES.PAPER_INTERVAL == "off"
        c, h, lo = _series()
        assert ES._view(NS(kl15=[[0]], kl1d=_kl1d(c, h, lo), c=c, h=h, l=lo, j=len(c) - 1)) is None
        ES.set_paper_interval("15m")
        assert ES._view(NS(kl15=[[0]], kl1d=None, c=c, h=h, l=lo, j=len(c) - 1))[1] == len(c) - 1   # 15m 은 예전 그대로
    finally:
        ES.PAPER_INTERVAL = old


def test_paper_worker_interval_failure_keeps_previous(monkeypatch):
    from app.workers import paper_trading_worker as PW
    old = ES.PAPER_INTERVAL
    try:
        ES.PAPER_INTERVAL = "15m"
        monkeypatch.setattr(ES, "setting", lambda db, k: (_ for _ in ()).throw(RuntimeError("db")))
        assert PW._ext_paper_interval(None) == "15m" and ES.PAPER_INTERVAL == "15m"   # 반환값 = 규칙이 실제 쓰는 값
    finally:
        ES.PAPER_INTERVAL = old


def test_paper_worker_fetches_daily_for_ext():
    w = (APP / "workers" / "paper_trading_worker.py").read_text(encoding="utf-8")
    assert '_ext_daily = _ext_paper_interval(db) == "1d"' in w
    assert "_need_ep = _dc is not None and not _daily_done" in w


def test_real_paper_path_passes_daily_to_rules():
    """Gemini 1회차 지적 확인: 워커가 series.k1d 를 채운 뒤 PT.evaluate_rules 가 **새 ctx** 를 만들어 일봉이 규칙에 실제로 닿는다.
    (단위 테스트처럼 ctx 를 직접 만들지 않고 가상매매 엔진 경로 그대로)."""
    from app.services import paper_trading as PT
    from app.services import ema_pullback as EP
    c, h, lo = _series()
    k1 = _kl1d(c, h, lo)
    day_close_15 = int(k1[-1][0]) + MS_DAY - MS_15M                    # 그날 마지막 15분봉
    allk = [[day_close_15 - (59 - i) * MS_15M, 100, 101, 99, 100, 10] for i in range(60)]
    series = PT.Series.build(allk, [])
    j = len(allk) - 1
    seen = []
    from app.services.chart_learning import Rule
    rules = [Rule("probe", "LONG", "probe", "candidate", lambda ctx: seen.append(ctx.kl1d) or True)]
    _cx = series.ctx(j)                                                # 워커처럼: ctx 를 먼저 만들고
    assert EP.needs_daily(_cx.kl15)
    series.k1d = k1                                                    # 그다음 일봉을 채운다
    PT.evaluate_rules(series, j, rules=rules)
    assert seen and seen[0] is k1                                      # 규칙은 채운 일봉을 받는다
    old = ES.PAPER_INTERVAL
    try:
        ES.set_paper_interval("1d")
        ind = ES.compute(c, h, lo)
        want = ES.fujimoto_stages(ind, len(c) - 1, "LONG", div_lookback=30)[3]
        fired = PT.evaluate_rules(series, j)
        assert fired["fujimoto_l3_ichimoku"] == want
    finally:
        ES.PAPER_INTERVAL = old


def test_live_timing_compact_keeps_just_closed_daily():
    """Gemini 3회차 지적 확인: 가상매매는 **닫힌** 15분봉만 판정 → 23:45 봉은 00:00 이후에 판정된다.
    그 시각(now = 00:00 + 수 초) compact 는 방금 닫힌 일봉을 남기고 오늘 진행 중 일봉만 뺀다 → 시각이 맞아 판정된다."""
    from app.services import chart_learning as CL
    c, h, lo = _series()
    raw = [[r[0], str(r[1]), str(r[2]), str(r[3]), str(r[4]), "1"] for r in _kl1d(c, h, lo)]
    today_open = int(raw[-1][0]) + MS_DAY
    raw.append([today_open, "1", "1", "1", "1", "1"])                 # 거래소 응답엔 오늘 진행 중 일봉이 끼어 있다
    now_ms = today_open + 5_000                                        # 23:45 봉이 닫힌 직후의 가상매매 사이클
    k1 = CL.compact(raw, now_ms=now_ms, interval_ms=CL.MS_DAY)
    last15 = today_open - MS_15M                                       # 판정 대상 = 방금 닫힌 23:45 봉
    assert int(last15) + MS_15M <= now_ms                              # 그 봉은 이미 닫혔다
    old = ES.PAPER_INTERVAL
    try:
        ES.set_paper_interval("1d")
        vw = ES._view(NS(kl15=[[last15]], kl1d=k1, c=[], h=[], l=[], j=0))
        assert vw is not None and vw[1] == len(c) - 1                   # 방금 닫힌 일봉까지로 판정
    finally:
        ES.PAPER_INTERVAL = old


def test_daily_cache_cannot_serve_other_symbol():
    """Gemini 4회차 지적 확인: 캐시가 원본 일봉 리스트를 **강한 참조**로 쥐고 있어 해제·주소 재사용이 불가능 → 다른 심볼 지표가 나올 수 없다."""
    import gc
    old = ES.PAPER_INTERVAL
    ES._D_CACHE.clear()
    try:
        ES.set_paper_interval("1d")
        outs = []
        for k in range(20):                                            # 심볼 20개를 차례로 (같은 길이)
            c, h, lo = _series(up=(k % 2 == 0))
            k1 = _kl1d(c, h, lo)
            last15 = int(k1[-1][0]) + MS_DAY - MS_15M
            ind, _j = ES._view(NS(kl15=[[last15]], kl1d=k1, c=[], h=[], l=[], j=0))
            outs.append((ind.c[-1], c[-1]))
            del k1
            gc.collect()
        assert all(a == b for a, b in outs)                            # 언제나 자기 일봉으로 계산한 지표
        assert all(ref is not None for ref, _ in ES._D_CACHE.values()) # 캐시가 참조를 쥐고 있다
    finally:
        ES.PAPER_INTERVAL = old
        ES._D_CACHE.clear()



# ── Fix 427 (Gemini 5회차 지적 확인): 23:45 봉 사이클을 놓쳐도 1시간 창 안이면 판정 · 하루 한 번만 ─────────
def test_daily_window_and_once_per_day():
    from app.services import ema_pullback as EP
    c, h, lo = _series()
    k1 = _kl1d(c, h, lo)
    dc = int(k1[-1][0]) + MS_DAY                                        # 그날 일봉 마감 = 다음 날 00:00
    old = ES.PAPER_INTERVAL
    try:
        ES.set_paper_interval("1d")
        for bar_open, want in ((dc - MS_15M, True), (dc, True), (dc + 2 * MS_15M, True),   # 23:45 · 00:00 · 00:30 봉
                               (dc + 3 * MS_15M, False), (dc - 2 * MS_15M, False)):        # 01:00 마감 봉 = 창 밖 · 마감 전
            got = ES._view(NS(kl15=[[bar_open]], kl1d=k1, c=[], h=[], l=[], j=0)) is not None
            assert got is want, (bar_open - dc) // MS_15M
        EP.set_paper_daily_done(True)                                   # 오늘 이미 판정
        assert ES._view(NS(kl15=[[dc]], kl1d=k1, c=[], h=[], l=[], j=0)) is None
    finally:
        EP.set_paper_daily_done(False)
        ES.PAPER_INTERVAL = old


def test_worker_marks_daily_done_only_after_fresh_daily():
    from app.workers import paper_trading_worker as PW
    w = (APP / "workers" / "paper_trading_worker.py").read_text(encoding="utf-8")
    assert "_need_ep, _dc, _cx = False, None, None" in w                # 앞 심볼 값이 새지 않게
    assert "_daily_done = _dc is not None and _paper_daily_done(sym, _dc)" in w
    i_eval = w.index("fired = PT.evaluate_rules(series, j)")
    i_mark = w.index("_mark_paper_daily_done(sym, _dc)")
    assert i_mark > i_eval and "_EPF.daily_is_fresh(series.k1d, _cx.kl15)" in w[i_eval:i_mark + 200]
    assert PW._k_daily_done("BTCUSDT", 123) == "paper:daily_done:BTCUSDT:123"
