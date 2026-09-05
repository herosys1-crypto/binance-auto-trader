"""📚 Fix 353 — 차트 학습 일지 (매일 상승 50위·하락 50위 차트 저장 → 36h 뒤 라벨 → 보고서).

사장님 2026-09-05: "상승 50위 하락 50위 심볼을 차트를 … 매일 매일 나눠서 학습을 해줘"
"""
from pathlib import Path

from app.services import chart_learning as CL

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
T0 = 1_757_000_000_000 // CL.MS_4H * CL.MS_4H      # 4h 경계에 맞춘 스냅샷 시각


def _bars(start_ms: int, step: int, prices: list[float], vol: float = 100.0) -> list[list[float]]:
    out = []
    for i, p in enumerate(prices):
        out.append([start_ms + i * step, p, p * 1.004, p * 0.996, p, vol])
    return out


def _pre(n15: int = CL.PRE_15M, n4: int = CL.PRE_4H, base: float = 100.0):
    pre15 = _bars(T0 - n15 * CL.MS_15M, CL.MS_15M, [base + (i % 7) * 0.05 for i in range(n15)])
    pre4 = _bars(T0 - n4 * CL.MS_4H, CL.MS_4H, [base + (i % 5) * 0.2 for i in range(n4)])
    return pre15, pre4


# ── 캔들 처리 ─────────────────────────────────────────────────────────

def test_compact_은_안_닫힌_봉을_뺀다():
    raw = [[T0, "1", "2", "0.5", "1.5", "10", T0 + CL.MS_15M - 1, "x"], [T0 + CL.MS_15M, "1", "2", "0.5", "1.5", "10"]]
    assert len(CL.compact(raw)) == 2
    assert len(CL.compact(raw, now_ms=T0 + CL.MS_15M + 1)) == 1        # 두 번째 봉은 진행중
    assert CL.compact(raw, now_ms=T0 + CL.MS_15M + 1)[0] == [T0, 1.0, 2.0, 0.5, 1.5, 10.0]


def test_aggregate_는_완전한_그룹만():
    k15 = _bars(T0 + CL.MS_15M, CL.MS_15M, [1.0] * 31)                 # 00:15 부터 31봉 → 첫 4h 그룹은 15봉(불완전)
    k4 = CL.aggregate(k15, CL.MS_4H)
    assert len(k4) == 1 and k4[0][0] == T0 + CL.MS_4H
    k1 = CL.aggregate(k15, CL.MS_1H)
    assert len(k1) == 7 and k1[0][0] == T0 + CL.MS_1H                   # 첫 1h 그룹(00:15~00:45 3봉)은 제외


# ── 결과 시뮬 ─────────────────────────────────────────────────────────

def test_sim_TP_SL_시간만료():
    up = _bars(T0, CL.MS_15M, [100 + i for i in range(20)])
    assert CL.sim("LONG", 100.0, up)["hit"] == "TP" and CL.sim("LONG", 100.0, up)["roi"] == 15.0
    assert CL.sim("SHORT", 100.0, up)["hit"] == "SL" and CL.sim("SHORT", 100.0, up)["roi"] == -5.0
    flat = _bars(T0, CL.MS_15M, [100.0] * 60)
    r = CL.sim("LONG", 100.0, flat)
    assert r["hit"] == "TIME" and r["bars"] == CL.HORIZON and abs(r["roi"]) < 1e-9


# ── 라벨 ─────────────────────────────────────────────────────────────

def test_label_row_정점_저점_규칙키():
    pre15, pre4 = _pre()
    fwd = _bars(T0, CL.MS_15M, [100 + i * 0.5 for i in range(24)] + [111 - i * 0.4 for i in range(120)])
    o = CL.label_row(pre15, pre4, fwd)
    assert o["entry_price"] == pre15[-1][4] and o["n_fwd"] == CL.FWD_BARS and o["window_bars"] == CL.WINDOW
    assert o["peak"]["bar"] == 23 and o["peak"]["pct"] > 10 and o["peak"]["drop_after_pct"] < 0
    assert o["trough"]["bar"] == 95 and o["trough"]["rise_after_pct"] >= 0
    assert set(o["rules"]) == {r.key for r in CL.RULES}
    assert len(o["baseline"]["LONG"]) == CL.WINDOW // CL.BASELINE_STEP
    assert o["at_snapshot"]["LONG"]["hit"] == "TP"


def test_RSI_반등_규칙이_발동하고_결과가_붙는다():
    pre15, pre4 = _pre()
    down = [100 - i * 0.8 for i in range(30)]                             # 30봉 하락 → RSI ≈ 0
    fwd = _bars(T0, CL.MS_15M, down + [down[-1] * 1.01 + i * 0.3 for i in range(114)])
    o = CL.label_row(pre15, pre4, fwd)
    f = o["rules"]["multiday_rebound_352"]
    assert f is not None and f["bar"] == 30 and f["hours"] == 7.75 and "roi" in f and f["move_pct"] < 0
    assert o["rules"]["l1_hist_turn_up"] is not None
    assert o["rules"]["s1_breakdown"] is not None and o["rules"]["s1_breakdown"]["bar"] < 30


def test_규칙_함수가_예외를_던져도_라벨은_나온다(monkeypatch):
    def boom(ctx):
        raise RuntimeError("x")
    rules = (CL.Rule("boom", "LONG", "x", "candidate", boom),)
    pre15, pre4 = _pre()
    o = CL.label_row(pre15, pre4, _bars(T0, CL.MS_15M, [100.0] * CL.FWD_BARS), rules=rules)
    assert o["rules"] == {"boom": None}


# ── 감시 대상 태그 ────────────────────────────────────────────────────

def test_tag_universe_당일_다일_동시_태그():
    chg = {"A": 30.0, "B": 10.0, "C": -12.0, "D": -3.0, "E": 1.0}
    qv = {s: 1e7 for s in chg}
    qv["E"] = 1e5                                                            # 거래대금 미달
    rets = {"A": (0.5, 0.9), "C": (0.4, 0.6), "D": (-0.3, -0.5), "E": (0.9, 0.9)}
    u = CL.tag_universe(chg, qv, rets, n=2, min_quote_volume=1e6)
    assert u["A"]["tags"] == ["UP", "UP3D", "UP5D"] and u["A"]["ranks"]["UP"] == 1
    assert "DOWN" in u["C"]["tags"] and "UP3D" in u["C"]["tags"]          # 며칠 상승 + 당일 하락 = 조정 자리
    assert "E" not in u and "UP" not in u["C"]["tags"]


# ── 보고서 ───────────────────────────────────────────────────────────

def _row(sym, sd, tags, roi_rule=None, base=(-1.0, 0.5)):
    rules = {r.key: None for r in CL.RULES}
    if roi_rule is not None:
        rules["multiday_rebound_352"] = {"bar": 3, "hours": 1.0, "price": 1.0, "move_pct": 0.0, "roi": roi_rule,
                                         "hit": "TP" if roi_rule > 10 else "SL", "bars": 5, "mfe": 1.0, "mae": 1.0}
    return {"symbol": sym, "snap_date": sd, "tags": tags, "source": "live",
            "outcome": {"version": 1, "entry_price": 1.0, "peak": {"bar": 1, "hours": 0.5, "pct": 3.0, "drop_after_pct": -2.0},
                        "trough": {"bar": 2, "hours": 0.75, "pct": -2.0, "rise_after_pct": 4.0},
                        "at_snapshot": {"LONG": {"roi": 1.0}, "SHORT": {"roi": -1.0}},
                        "baseline": {"LONG": [base[0]] * 8, "SHORT": [base[1]] * 8}, "rules": rules}}


def test_build_report_과_markdown():
    rows = [_row("AAUSDT", "2026-09-01", ["UP", "UP5D"], 15.0), _row("ABUSDT", "2026-09-02", ["DOWN", "UP3D"], 15.0),
            _row("ACUSDT", "2026-09-03", ["DOWN5D", "DOWN"], -5.0), _row("ADUSDT", "2026-09-04", ["UP"]),
            {"symbol": "ZZ", "snap_date": "2026-09-04", "tags": [], "source": "live", "outcome": None}]
    rep = CL.build_report(rows)
    assert rep["rows"] == 4 and rep["rows_total"] == 5 and rep["dates"]["n"] == 4
    g = rep["groups"]
    assert g["ALL"]["n"] == 4 and g["UP35_DOWN24"]["n"] == 1 and g["DOWN35_DOWN24"]["n"] == 1
    st = g["ALL"]["rules"]["multiday_rebound_352"]
    assert st["n"] == 3 and st["side"] == "LONG" and abs(st["mean"] - 8.333) < 1e-3 and st["delta"] > 0   # 3자리 반올림
    assert set(rep["cv"]["multiday_rebound_352"]) == {"sym_even", "sym_odd", "date_early", "date_late", "all_positive"}
    md = CL.render_markdown(rep, min_n=1)
    assert "## 1. 자리별 기준선" in md and "`UP35_DOWN24`" in md and "교차검증" in md


# ── 설정 기본값 ───────────────────────────────────────────────────────

def test_설정_기본값():
    assert CL.enabled(None) is True and CL.top_n(None) == 50 and CL.keep_days(None) == 45
    assert CL.outcome_batch(None) == 400 and CL.snapshot_hours(None) == {0}
    assert (CL.LEV, CL.SL_PRICE, CL.TP_PRICE, CL.HORIZON, CL.WINDOW) == (2.0, 0.025, 0.075, 48, 96)


# ── 배선 ─────────────────────────────────────────────────────────────

def test_배선():
    s = (APP / "workers" / "scheduler_runner.py").read_text(encoding="utf-8")
    assert 'id="chart_learning_snapshot"' in s and 'CronTrigger(hour="0,12", minute=5)' in s
    assert 'id="chart_learning_outcome"' in s and "run_chart_learning_outcome_once" in s
    assert "ChartLearningDay" in (APP / "models" / "__init__.py").read_text(encoding="utf-8")
    r = (APP / "api" / "router.py").read_text(encoding="utf-8")
    assert "include_router(chart_learning_router)" in r
    m = (ROOT / "alembic" / "versions" / "0035_chart_learning_days.py").read_text(encoding="utf-8")
    assert "revision = '0035_chart_learning'" in m and "down_revision = '0034_surge_ladder'" in m
    assert len("0035_chart_learning") <= 32


def test_규칙_레지스트리는_시스템_규칙_넷을_담는다():
    keys = {r.key for r in CL.RULES}
    assert {"toprev_331", "pullback_331", "bottom_331", "surge_start_346", "multiday_rebound_352"} <= keys
    assert all(r.side in ("LONG", "SHORT") and r.origin in ("system", "candidate") for r in CL.RULES)
