"""📈 Fix 447 — 추세 보유 청산 가상 기록 (1시간봉 EMA9 이탈 절반 · SMA20 이탈 나머지).

live_trend  = TP1(+15 ROI, 25%) 뒤 트레일링 대신 추세선
live_trend0 = 진입 직후부터 추세선 (TP1 부분익절 없음)
레버 2 → 가격 1% = ROI 2%. TP1 가격 = 107.5 (LONG, 진입 100).
"""
from pathlib import Path

import pytest

from app.services import paper_trading as PT
from app.services.chart_learning import MS_15M, MS_1H

ROOT = Path(__file__).resolve().parents[1] / "app"


def _bar(ts, o, h, l, c, v=1000.0):
    return [ts, o, h, l, c, v]


def _run(side, bars, lines, mode="after_tp1", **kw):
    return PT.run_live_like(side, 100.0, bars, tp1_pct=15.0, variants=(), trend=mode, trend_lines=lines, **kw)


def test_definitions():
    assert PT.EXIT_VARIANTS["live_trend"] == {"trend": "after_tp1"}
    assert PT.EXIT_VARIANTS["live_trend0"] == {"trend": "from_entry"}
    assert (PT.TREND_EMA, PT.TREND_SMA) == (9, 20)
    assert PT.VERSION == 2


def test_after_tp1_half_then_rest():
    bars = [_bar(0, 100, 108, 100, 108),        # TP1 (107.5) → 25% 에 +15
            _bar(1, 108, 112, 107, 111),        # 마감 · 선 위
            _bar(2, 111, 111, 106, 106),        # 마감 · EMA9(107) 아래 → 남은 75% 의 절반
            _bar(3, 106, 106, 103, 103),        # 마감 · SMA20(104) 아래 → 나머지
            _bar(4, 103, 103, 103, 103)]
    lines = [(99, 98), (109, 100), (107, 100), (105, 104), None]
    r = _run("LONG", bars, lines)
    exp = 0.25 * 15 + 0.375 * 12 + 0.375 * 6       # 106 = ROI +12 · 103 = ROI +6
    assert r["hit"] == "TREND" and r["exit_bar"] == 3 and r["trend_half"] is True
    assert r["roi"] == pytest.approx(exp, abs=1e-6)


def test_after_tp1_ignores_trailing_and_tp1_bar_itself():
    # TP1 봉(0) 종가가 선 아래여도 그 봉은 판정 안 함 · 트레일링(최고 −5%p)이었다면 bar2 에서 청산됐을 하락도 선 위면 보유
    bars = [_bar(0, 100, 110, 100, 101), _bar(1, 101, 112, 108, 111), _bar(2, 111, 111, 106, 107)]
    lines = [(105, 104), (108, 100), (105, 100)]
    r = _run("LONG", bars, lines)
    assert r["hit"] == "OPEN" and r["tp1_hit"] is True and r["trend_half"] is False
    live = PT.run_live_like("LONG", 100.0, bars, tp1_pct=15.0, variants=())
    assert live["hit"] == "TRAIL"


def test_before_tp1_no_trend_exit_but_sl_applies():
    bars = [_bar(0, 100, 101, 95, 96), _bar(1, 96, 96, 87, 88)]
    lines = [(99, 98), (99, 98)]
    r = _run("LONG", bars, lines)
    assert r["hit"] == "SL" and r["exit_bar"] == 1          # 손절가 87.5 (−25 ROI)


def test_from_entry_no_tp1_and_short_mirror():
    bars = [_bar(0, 100, 109, 100, 108), _bar(1, 108, 108, 101, 102)]
    lines = [(105, 103), (104, 103)]
    r = _run("LONG", bars, lines, mode="from_entry")
    assert r["tp1_hit"] is False and r["hit"] == "TREND" and r["roi"] == pytest.approx(4.0)
    sb = [_bar(0, 100, 100, 92, 93), _bar(1, 93, 96, 93, 95), _bar(2, 95, 99, 95, 98)]
    sl = [(94, 96), (94.5, 97), (97, 97.5)]
    s = _run("SHORT", sb, sl, mode="from_entry")
    # bar1 종가 95 > EMA9 94.5 → 절반(ROI +10) · bar2 종가 98 > SMA20 97.5 → 나머지(ROI +4)
    assert s["hit"] == "TREND" and s["exit_bar"] == 2
    assert s["roi"] == pytest.approx(0.5 * 10 + 0.5 * 4)


def test_no_lines_means_only_sl_and_time():
    bars = [_bar(i, 100, 101, 99, 100) for i in range(PT.LIVE_HORIZON)]
    r = _run("LONG", bars, None)
    assert r["hit"] == "TIME"


def _series(n_hours=30, start=1_760_000_000_000 // MS_1H * MS_1H):
    allk = []
    for i in range(n_hours * 4):
        p = 100 + i * 0.1
        allk.append([start + i * MS_15M, p, p + 0.5, p - 0.5, p + 0.05, 10.0])
    return PT.Series.build(allk, [])


def test_trend_lines_alignment_and_values():
    s = _series()
    j = 80                                              # 진입 봉
    out = PT.trend_lines_for(s, j)
    assert len(out) == len(s.allk) - j - 1
    closes = [b[4] for b in s.k1h]
    for i, v in enumerate(out):
        b = s.allk[j + 1 + i]
        is_hour_close = (int(b[0]) + MS_15M) % MS_1H == 0
        if not is_hour_close:
            assert v is None
            continue
        n = (int(b[0]) + MS_15M - int(s.allk[0][0])) // MS_1H - 1
        assert v is not None
        assert v[1] == pytest.approx(sum(closes[n - 19:n + 1]) / 20)
        assert v[0] == pytest.approx(PT._ema_series(closes, 9)[n])
    early = PT.trend_lines_for(s, 0)                    # 앞쪽 = SMA20 없음 → None
    assert all(v is None for v in early[:70])


def test_manage_trade_records_trend_engines():
    s = _series(60)
    j = 100
    t = {"side": "LONG", "entry_price": s.allk[j][4], "entry_bar_ts": int(s.allk[j][0])}
    m = PT.manage_trade(t, s)
    assert {"live_trend", "live_trend0"} <= set(m["engines"])
    assert "trend_half" in m["engines"]["live_trend0"]


def test_report_and_export_pick_up_new_engines():
    src = (ROOT / "services" / "paper_report_v3.py").read_text(encoding="utf-8")
    assert "tuple(PT.EXIT_VARIANT_ENGINES)" in src


def _verdict_mod():
    import importlib.util
    p = Path(__file__).resolve().parents[1] / "scripts" / "entry_condition_study" / "verdict_2026_10_25.py"
    spec = importlib.util.spec_from_file_location("verdict_2026_10_25_t447", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_verdict_exit_compare_preregistered():
    from datetime import date, timedelta
    V = _verdict_mod()
    assert V.EXIT_ENGINES == ("live_stale24", "live_trend", "live_trend0")
    d0 = date(2026, 10, 13)
    rows = [{"d": d0 + timedelta(days=i % 10), "eng": {"live": 1.0, "live_trend": 1.5}} for i in range(40)]
    ev = V.exit_compare(rows, "live_trend")
    assert ev["n"] == 40 and ev["diff"] == 0.5 and ev["verdict"] == "✅ 청산 후보"
    worse = [dict(r, eng={"live": 1.0, "live_trend": 1.5 if r["d"] < d0 + timedelta(days=5) else 0.0}) for r in rows]
    assert V.exit_compare(worse, "live_trend")["verdict"] == "❌ 지금 청산 유지"
    assert V.exit_compare(rows[:10], "live_trend")["verdict"] == "⏳ 보류"
    assert V.exit_compare([{"d": d0, "eng": {"live": 1.0}}], "live_trend")["n"] == 0      # 키 없는 행 = 짝 아님
    assert V.exit_compare([{"d": d0, "eng": {"live": True, "live_trend": 1.0}}], "live_trend")["n"] == 0
    stale = [{"d": d0 + timedelta(days=i % 10), "eng": {"live": -5.0 if i % 10 == 0 else 1.0, "live_stale24": -2.0 if i % 10 == 0 else 1.0}}
             for i in range(40)]
    ev2 = V.exit_compare(stale, "live_stale24")
    assert ev2["worst_live"] == -20.0 and ev2["worst_eng"] == -8.0
    src = p_src = (Path(__file__).resolve().parents[1] / "scripts" / "entry_condition_study" / "verdict_2026_10_25.py").read_text(encoding="utf-8")
    assert "## G." in p_src and "engines->'live_trend' is not null" in src


def test_stage1_table_fix448():
    V = _verdict_mod()
    rows = V.stage1_rows("rf_consensus_long", "rf", {"rf_consensus_long_mode": "shadow", "rf_consensus_long_capital_usdt": "10",
                                                     "daily_max_rf_consensus_long": "1", "rf_consensus_long_max_concurrent": "1",
                                                     "rf_consensus_long_entry": "split", "rf_regime_filter": "on"})
    keys = [r[0] for r in rows]
    assert keys == ["rf_consensus_long_mode", "rf_consensus_long_capital_usdt", "daily_max_rf_consensus_long",
                    "rf_consensus_long_max_concurrent", "rf_consensus_long_loss_breaker_usdt", "rf_consensus_long_entry", "rf_regime_filter"]
    t = V.stage1_table("rf_consensus_long", "합의 LONG", "rf", dict((r[0], r[1]) for r in rows))
    assert "| `rf_consensus_long_mode` | shadow | on | ✏️ |" in t
    assert "| `daily_max_rf_consensus_long` | 1 | 1~3 | — |" in t
    assert "| `rf_consensus_long_loss_breaker_usdt` | — | 0 | — |" in t
    assert "분할 유지면" in t
    ext = V.stage1_rows("trima", "ext", {})
    assert ext[0][3].startswith("⚠️ on 이어도 shadow") and ext[-1][0] == "ext_regime_filter"
    fj = V.stage1_rows("fujimoto", "ext", {"fujimoto_total_alloc_usdt": "100"})[1]
    assert fj[0] == "fujimoto_total_alloc_usdt" and fj[2] == "유지" and "단위가 달라" in fj[3]
    assert "| `fujimoto_total_alloc_usdt` | 100 | 유지 | — |" in V.stage1_table("fujimoto", "후지모토", "ext", {"fujimoto_total_alloc_usdt": "100"})
    src = (Path(__file__).resolve().parents[1] / "scripts" / "entry_condition_study" / "verdict_2026_10_25.py").read_text(encoding="utf-8")
    assert "## H." in src and src.count("passed.setdefault(") == 5   # A·B·C·D + 미리 보기
