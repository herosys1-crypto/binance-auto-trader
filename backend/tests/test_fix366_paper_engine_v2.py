"""🧪 Fix 366 — 가상 엔진 v2 (사장님 2026-09-10 「2·5·7 진행」): 손절 변형 · 실코드와 맞춤(TP1 15 고정, 적응 TP 변형, 게이트 재현) · 시장 국면 태그."""
from pathlib import Path

from app.services import paper_trading as PT

ROOT = Path(__file__).resolve().parents[1] / "app"


def _bar(ts, o, h, l, c, v=1000.0):
    return [ts, o, h, l, c, v]


def _series(n=320, base=100.0):
    """평탄한 15m 봉 n개 + 4h 봉 — 지표 계산이 가능할 만큼 길게."""
    allk = [_bar(1_700_000_000_000 + i * 900_000, base, base + 0.5, base - 0.5, base) for i in range(n)]
    k4h = [_bar(1_700_000_000_000 + i * 14_400_000, base, base + 1, base - 1, base) for i in range(n // 16 + 2)]
    return PT.Series.build(allk, k4h)


def test_breadth_and_tags():
    chg = {"AUSDT": 5.0, "BUSDT": -1.0, "CUSDT": 2.0}
    qv = {"AUSDT": 6e6, "BUSDT": 6e6, "CUSDT": 1e6}
    assert PT.market_breadth(chg, qv, min_quote_volume=5e6) is None                       # 20개 미만 = 보류
    big_chg = {f"S{i}USDT": (1.0 if i % 10 < 7 else -1.0) for i in range(100)}
    big_qv = {s: 6e6 for s in big_chg}
    assert PT.market_breadth(big_chg, big_qv, min_quote_volume=5e6) == 0.7
    assert PT.breadth_tag(0.7) == "MKT_UP" and PT.breadth_tag(0.3) == "MKT_DOWN" and PT.breadth_tag(0.5) == "MKT_FLAT"
    assert PT.breadth_tag(None) is None
    assert PT.breadth_tag(0.55, up=0.55) == "MKT_UP"
    g = PT.group_of(["UP", "MKT_DOWN", "LIVE_OK"])
    assert "UP24" in g and "MKT_DOWN" in g and "LIVE_OK" in g and "MKT_UP" not in g
    assert set(PT.GROUP_KEYS) >= {"MKT_UP", "MKT_DOWN", "LIVE_OK"}
    assert PT.ENGINES == ("house", "live", "live_adaptive", "live_sl10", "live_sl15")


def test_manage_trade_has_five_engines_and_live_uses_flat_tp1():
    s = _series()
    j = 200
    t = {"side": "LONG", "entry_price": float(s.allk[j][4]), "entry_bar_ts": int(s.allk[j][0]), "tp1_pct": 3.0, "chg_24h": 1.0}
    res = PT.manage_trade(t, s)
    eng = res["engines"]
    assert set(eng) == set(PT.ENGINES)
    assert eng["live"]["tp1_pct"] == PT.TP1_FLAT == 15.0                                  # 실코드 = TP1 15 고정
    assert eng["live_adaptive"]["tp1_pct"] == 3.0                                         # 적응 TP 변형은 저장된 3/15
    assert eng["live_sl10"]["sl_roi"] == 10.0 and eng["live_sl15"]["sl_roi"] == 15.0 and eng["live"]["sl_roi"] == 25.0
    assert "adds" in res and set(res["adds"]) == set(PT.VARIANTS)                         # 추가 변형은 live 엔진 위에서만
    assert res["status"] == "OPEN"                                                        # 평탄봉 = 아무 엔진도 안 끝남


def test_sl_variants_close_earlier_than_sl25():
    entry = 100.0
    # LONG, 가격이 매 봉 −3% 씩 → ROI(2배) −6%/봉: sl10 은 2봉째, sl15 는 3봉째, sl25 는 5봉째
    bars = [_bar(i, entry * (0.97 ** i), entry * (0.97 ** i) + 0.1, entry * (0.97 ** (i + 1)), entry * (0.97 ** (i + 1))) for i in range(8)]
    r10 = PT.run_live_like("LONG", entry, bars, tp1_pct=15.0, sl_roi=10.0, variants=())
    r15 = PT.run_live_like("LONG", entry, bars, tp1_pct=15.0, sl_roi=15.0, variants=())
    r25 = PT.run_live_like("LONG", entry, bars, tp1_pct=15.0, sl_roi=25.0, variants=())
    assert r10["hit"] == r15["hit"] == r25["hit"] == "SL"
    assert r10["exit_bar"] < r15["exit_bar"] < r25["exit_bar"]
    assert r10["roi"] == -10.0 and r15["roi"] == -15.0 and r25["roi"] == -25.0


def test_add_cooldown_matches_live_next_bar_and_anchor_is_blended_avg():
    assert PT.ADD_COOLDOWN_BARS == 0                                                       # 실코드 5분 쿨다운 = 다음 봉부터
    entry = 100.0
    hist = [20.0 - 2 * i for i in range(7)]
    # SHORT: 90 에서 첫 lot(ROI 20). 합산 평단 ≈ (10·100 + 300·90)/310 = 90.32 → 다음 봉 89.9 는 평단 대비 이동 0.5% < 3% = 추가 없음
    closes = [99.0, 97.0, 95.0, 90.0, 89.9, 89.8, 89.7]
    bars = [_bar(0, c + 0.5, c + 1.0, c - 1.0, c) for c in closes]
    r = PT.run_live_like("SHORT", entry, bars, tp1_pct=500.0, hist=hist, hist_off=0, horizon=7, variants=("live_both",))
    assert [a["bar"] for a in r["adds"]["live_both"]] == [3], "두 번째 lot 은 합산 평단 기준으로 다시 재야 한다 (C11)"
    # 평단 대비 3% 더 내려가면(≈87.6) 다음 봉에 바로 두 번째 lot (쿨다운 = 다음 봉)
    closes2 = [99.0, 97.0, 95.0, 90.0, 87.0, 86.0, 85.0]
    bars2 = [_bar(0, c + 0.5, c + 1.0, c - 1.0, c) for c in closes2]
    r2 = PT.run_live_like("SHORT", entry, bars2, tp1_pct=500.0, hist=hist, hist_off=0, horizon=7, variants=("live_both",))
    assert [a["bar"] for a in r2["adds"]["live_both"]] == [3, 4]
    # live 변형은 LONG 만 (사장님 pyramid_sides=LONG)
    r3 = PT.run_live_like("SHORT", entry, bars2, tp1_pct=500.0, hist=hist, hist_off=0, horizon=7, variants=("live",))
    assert r3["adds"]["live"] == []


def test_live_gate_replay_shape_and_open_trade_tag():
    s = _series()
    j = 300
    g = PT.live_gate_replay(s, j, "SHORT", "XUSDT")
    assert set(g) >= {"obv", "regime", "h1", "surge_veto", "all"} and isinstance(g["all"], bool)
    gl = PT.live_gate_replay(s, j, "LONG", "XUSDT")
    assert gl["h1"] is None and gl["surge_veto"] is None                                   # LONG 은 OBV + LONG regime 만
    src = (ROOT / "services" / "paper_trading.py").read_text(encoding="utf-8")
    i_g = src.find("def live_gate_replay(")
    assert 'tag = f"_learn_paper_' in src[i_g:i_g + 3000], "C6: `_learn_` 접두사 = Redis 캐시 우회 규약"
    assert "series.k4h[max(0, n4 - 79):n4]" in src[i_g:i_g + 3000], "C14: 게이트 재현 4h 80봉"
    fired = PT.evaluate_rules(s, j)
    t = PT.open_trade(symbol="XUSDT", side="SHORT", rule="baseline_SHORT", series=s, j=j, tags=["UP", "MKT_UP"],
                      chg_24h=3.0, chg_3d=None, chg_5d=None, source="live", fired=fired)
    assert "live_gates" in t["snapshot"] and t["version"] == 2
    assert ("LIVE_OK" in t["tags"]) == bool(t["snapshot"]["live_gates"]["all"])
    assert "MKT_UP" in t["tags"]


def test_report_paired_sample_and_recommend_split():
    """C1/C3/C4: live 계열 통계는 넷이 모두 끝난 건만, live 는 TP1 15 로 계산된 것만, 채택 제안은 house/live 만."""
    def eng(done, roi, tp1=15.0, sl=25.0):
        return {"done": done, "roi": roi, "hit": "TRAIL" if done else "END_OF_DATA", "tp1_pct": tp1, "sl_roi": sl}

    def trade(i, sym, roi, *, sl10_done=True, tp1=15.0):
        return {"status": "CLOSED", "source": "backfill", "symbol": sym, "rule": "confirm_peak_111", "side": "SHORT",
                "tags": ["UP"], "opened_at": f"2026-09-0{1 + i % 9}T00:00:00", "adds": {},
                "engines": {"house": eng(True, roi), "live": eng(True, roi, tp1), "live_adaptive": eng(True, roi, 3.0),
                            "live_sl10": eng(sl10_done, roi, 15.0, 10.0), "live_sl15": eng(True, roi, 15.0, 15.0)}}
    trades = [trade(i, f"S{i}USDT", 1.0) for i in range(6)]
    trades += [trade(6, "CENSUSDT", 9.0, sl10_done=False)]                                # sl10 미완 → 짝 표본에서 전부 제외
    trades += [trade(7, "V1USDT", 9.0, tp1=3.0)]                                           # v1 적응 TP 행 → live 통계에서 제외
    rep = PT.build_report(trades)
    st = rep["rules"]["confirm_peak_111"]["groups"]["ALL"]
    assert st["live"]["n"] == 6 and st["live_sl10"]["n"] == 7 and st["house"]["n"] == 8
    assert rep["censored"]["live_sl10"] == 1 and rep["paired_n"] == 7 and rep["versions"]["v2"] == 8
    assert "variants" in rep["recommend"] and rep["recommend"]["hypotheses"] > 0
    md = PT.render_markdown(rep)
    assert "짝 표본" in md and "잣대 house·live 만" in md


def test_worker_pins():
    wk = (ROOT / "workers" / "paper_trading_worker.py").read_text(encoding="utf-8")
    for pin in ("breadth = PT.market_breadth(chg, qv, min_quote_volume=MIN_QUOTE_VOLUME)", "_publish_breadth(db, breadth, mtag)",
                "_u, _uskip = _upgrade_closed_live_rows(db, PaperTrade, sym, series)", "on_conflict_do_update(",
                'where=((PaperTrade.version < PT.VERSION) & (PaperTrade.status == "CLOSED"))', "ENGINE_VERSION_KEY",
                '_set_setting(db, CURSOR_KEY, "0")', '"breadth": breadth, "regime": mtag', "row.version = PT.VERSION",
                'interval="4h", limit=82', '"version": r.version'):
        assert pin in wk, pin
    svc = (ROOT / "services" / "paper_trading.py").read_text(encoding="utf-8")
    i_bf = svc.find("def backfill_row(")
    assert '_ev["hit"] = "END_OF_DATA"' in svc[i_bf:], "검열 표시는 live 계열 엔진 전부"
    i_r = svc.find("def render_markdown(")
    assert "for eng in ENGINES:" in svc[i_r:] and "live_adaptive = TP1 3/15%" in svc[i_r:]
