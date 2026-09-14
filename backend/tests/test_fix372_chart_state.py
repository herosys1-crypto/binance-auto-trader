"""📐 Fix 372 — 일봉·4H 볼밴 상태 · 5분/1분 단기 고점·저점 · 진입 타이밍 채점 · 기록 배선 (학습 전용)."""
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql

from app.services import chart_state as CS
from app.services import chart_state_report as CSR

APP = Path(__file__).resolve().parents[1] / "app"
DAY = CS.MS["1d"]
M5 = CS.MS["5m"]
TH = CS.THRESHOLDS


def _bars(closes, *, step=DAY, spread=0.004, start=0):
    out, prev = [], closes[0]
    for k, c in enumerate(closes):
        o = prev
        out.append([start + k * step, o, max(o, c) * (1 + spread), min(o, c) * (1 - spread), c, 1000.0])
        prev = c
    return out


def _base(n=40):
    return [100 + 2 * math.sin(k * 0.7) for k in range(n)]


def _state(bars):
    return CS.bb_state(bars, tol_pct=TH["tol_pct_1d"], lookback=TH["lookback_1d"], slope_pct=TH["trend_slope_1d"])


def _last(bars, o, h, l, c):
    bars[-1][1:5] = [o, h, l, c]
    return bars


def _with_prev(prev_close, o, h, l, c):
    closes = _base()
    closes[-1] = prev_close
    b = _bars(closes)
    b.append([b[-1][0] + DAY, o, h, l, c, 1000.0])
    return b


# ── 일봉 볼밴 상태 (사장님 이벤트 전부) ────────────────────────────────────
def test_upper_breakout_ride_and_reject():
    s = _state(_bars(_base() + [110]))
    assert s["state"] == "UPPER_BREAKOUT" and s["pos"] == "ABOVE_UPPER"
    assert _state(_bars(_base() + [110, 112]))["state"] == "UPPER_RIDE"
    s = _state(_with_prev(100.5, 100.5, 103.5, 100.2, 101.0))
    assert "UPPER_REJECT" in s["events"]


def test_pullback_start_and_deep_pullback_after_upper_breakout():
    b = _bars(_base() + [110])
    b.append([b[-1][0] + DAY, 110, 110.5, 103.5, 104.0, 1000.0])
    s = _state(b)
    assert "PULLBACK_START" in s["events"] and "DEEP_PULLBACK" not in s["events"]
    b2 = _bars(_base() + [110, 106])
    b2.append([b2[-1][0] + DAY, 106, 106.5, 100.0, 100.8, 1000.0])
    assert "DEEP_PULLBACK" in _state(b2)["events"]


def test_mid_support_breakdown_reclaim_resist():
    assert "MID_SUPPORT" in _state(_with_prev(100.6, 100.6, 101.0, 99.9, 100.7))["events"]
    assert "MID_BREAKDOWN" in _state(_with_prev(101.0, 101.0, 101.2, 98.8, 99.0))["events"]
    assert "MID_RECLAIM" in _state(_with_prev(99.0, 99.0, 101.3, 98.9, 101.0))["events"]
    assert "MID_RESIST" in _state(_with_prev(99.0, 99.0, 100.3, 98.9, 99.2))["events"]


def test_lower_breakdown_ride_support_rebound_and_rerise():
    assert _state(_bars(_base() + [90]))["state"] == "LOWER_BREAKDOWN"
    assert _state(_bars(_base() + [90, 88]))["state"] == "LOWER_RIDE"
    assert "LOWER_SUPPORT" in _state(_with_prev(99.0, 99.0, 99.5, 97.0, 98.2))["events"]
    reb = _state(_bars(_base() + [90, 97]))
    assert "REBOUND_AFTER_LOWER" in reb["events"]
    b = _bars(_base() + [90, 97])
    b.append([b[-1][0] + DAY, 97, 102.9, 96.8, 102.5, 1000.0])       # 중단선 위 + 직전 3봉 고가(≈102.06) 돌파
    assert "RERISE_START" in _state(b)["events"]


def test_trend_and_bias_and_short_history():
    up = [100 * (1.02 ** k) for k in range(40)]
    s = _state(_bars(up))
    assert s["trend"] == "UP"
    assert _state(_bars(_base() + [90]))["bias"] < 0 < _state(_bars(_base() + [110]))["bias"]
    assert _state(_bars(_base()[:20]))["error"] == "bars"


# ── 5분·1분 단기 ─────────────────────────────────────────────────────────
def _wave5m():
    up = [100 + k * 0.5 for k in range(21)]            # 0..20 → 110 (고점)
    down = [110 - k for k in range(1, 11)]              # 21..30 → 100 (저점)
    up2 = [100 + k * 0.99 for k in range(1, 10)]        # 31..39 → 108.9
    return up + down + up2


def test_short_term_resistance_reject_and_support():
    closes = _wave5m()
    b = _bars(closes, step=M5, spread=0.0005)
    b.append([b[-1][0] + M5, 109.7, 109.9, 109.0, 109.2, 1000.0])       # 직전 고점 110 에 닿고 음봉
    st = CS.short_term(b, range_bars=TH["range_bars_5m"])
    assert st["resistance"] == pytest.approx(110 * 1.0005, rel=1e-3)
    assert "RESIST_REJECT" in st["events"]
    assert st["support"] == pytest.approx(100 * (1 - 0.0005), rel=1e-3)
    b2 = _bars(closes[:31], step=M5, spread=0.0005) + [[0, 0, 0, 0, 0, 0]] * 0
    b2 = _bars(closes[:31] + [101, 102, 103, 102, 101], step=M5, spread=0.0005)
    b2.append([b2[-1][0] + M5, 100.4, 101.2, 99.99, 101.0, 1000.0])     # 직전 저점 100 지지 양봉
    assert "SUPPORT_HOLD" in CS.short_term(b2, range_bars=TH["range_bars_5m"])["events"]


def test_short_term_new_high_near_top_and_breaks():
    rally = [100 + k * 0.4 for k in range(40)]
    st = CS.short_term(_bars(rally, step=M5, spread=0.0005), range_bars=24)
    assert "NEW_HIGH" in st["events"] and st["near_top"] is True and st["range_pos"] > 0.9
    closes = _wave5m()
    b = _bars(closes, step=M5, spread=0.0005)
    b.append([b[-1][0] + M5, 109.0, 111.0, 108.9, 110.8, 1000.0])
    assert "BREAK_RESIST" in CS.short_term(b, range_bars=24)["events"]


# ── 진입 타이밍 채점 ──────────────────────────────────────────────────────
def _timing_bars(pre, after, entry_ms):
    bars = []
    for k, (h, l, c) in enumerate(pre):
        bars.append([entry_ms - (len(pre) - k) * M5, c, h, l, c, 1.0])
    for k, (h, l, c) in enumerate(after):
        bars.append([entry_ms + k * M5, c, h, l, c, 1.0])
    return bars


FLAT = [(100.2, 99.8, 100.0)] * 12
E_MS = 1_700_000_000_000


def test_timing_labels_long():
    good = [(100 + 0.05 * k + 0.1, 100 + 0.05 * k - 0.1, 100 + 0.05 * k) for k in range(48)]
    r = CS.timing_label("LONG", 100.0, E_MS, _timing_bars(FLAT, good, E_MS))
    assert r["label"] == "GOOD" and r["max_fav_pct"] >= 1.5
    early = [(99.9, 98.2, 98.4)] * 10 + [(102.0, 100.0, 101.8)] * 38
    assert CS.timing_label("LONG", 100.0, E_MS, _timing_bars(FLAT, early, E_MS))["label"] == "EARLY"
    wrong = [(99.9, 96.5, 97.0)] * 48
    r = CS.timing_label("LONG", 100.0, E_MS, _timing_bars(FLAT, wrong, E_MS))
    assert r["label"] == "WRONG_DIRECTION" and r["best_offset_bars"] >= 0
    late_pre = [(100.2, 97.5, 98.0)] * 6 + [(100.2, 99.8, 100.0)] * 6        # 1시간 안에 97.5 까지 쌌다 = 이미 올랐다
    flat_after = [(100.4, 99.6, 100.0)] * 48
    r = CS.timing_label("LONG", 100.0, E_MS, _timing_bars(late_pre, flat_after, E_MS))
    assert r["label"] == "LATE" and r["late_flag"] and r["best_offset_bars"] < 0
    assert CS.timing_label("LONG", 100.0, E_MS, _timing_bars(FLAT, flat_after, E_MS))["label"] == "NO_MOVE"


def test_timing_short_mirror_and_insufficient_bars():
    good = [(100 - 0.05 * k + 0.1, 100 - 0.05 * k - 0.1, 100 - 0.05 * k) for k in range(48)]
    assert CS.timing_label("SHORT", 100.0, E_MS, _timing_bars(FLAT, good, E_MS))["label"] == "GOOD"
    assert CS.timing_label("SHORT", 100.0, E_MS, _timing_bars(FLAT, good[:10], E_MS))["label"] is None


# ── 캡처 · 설정 ──────────────────────────────────────────────────────────
class _BC:
    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def get_klines(self, *, symbol, interval, limit, start_time=None):
        self.calls.append(interval)
        if interval in self.fail:
            raise RuntimeError("boom")
        step = CS.MS[interval]
        now = 1_800_000_000_000
        return [[now - (limit + 1 - k) * step, 100, 101, 99, 100 + math.sin(k), 10, 0] for k in range(limit)]


def test_capture_reuses_given_bars_and_isolates_failures():
    bc = _BC(fail=("1m",))
    have = {"15m": _bars(_base(60), step=CS.MS["15m"])}
    out = CS.capture(bc, "XUSDT", "LONG", now_ms=1_800_000_000_000, klines=have)
    assert "15m" not in bc.calls and set(bc.calls) == {"1d", "4h", "1h", "5m", "1m"}
    assert "bb" in out["d1"] and "bb" in out["h4"] and "st" in out["m5"]
    assert "error" in out["m1"] and "error" not in out["d1"]
    bc2 = _BC()
    assert "m1" not in CS.capture(bc2, "XUSDT", "LONG", now_ms=1_800_000_000_000, include_1m=False)
    assert "1m" not in bc2.calls


def test_normalize_drops_in_progress_bar():
    rows = [[0, 1, 2, 0.5, 1.5, 10], [DAY, 1, 2, 0.5, 1.5, 10]]
    assert len(CS.normalize(rows, "1d", now_ms=DAY + 1000)) == 1


def test_thresholds_override():
    class _DB:
        def get(self, _m, key):
            return type("R", (), {"value": '{"timing_win_pct": 2.5, "nope": 1}'})() if key == CS.S_THRESH else None
    th = CS.thresholds(_DB())
    assert th["timing_win_pct"] == 2.5 and "nope" not in th


# ── 보고서 · 배선 ─────────────────────────────────────────────────────────
def test_report_aggregate_delta_vs_same_state_baseline():
    t0 = datetime(2026, 9, 15, tzinfo=timezone.utc)
    rows = []
    for k in range(40):
        rows.append({"side": "LONG", "rule": "bottom_331", "symbol": f"S{k}USDT", "opened_at": t0 + timedelta(hours=k),
                     "roi": 3.0, "done": "true", "d1_state": "MID_SUPPORT", "d1_trend": "UP", "m5_pos": 0.1,
                     "timing": "GOOD", "best_offset": 2})
        rows.append({"side": "LONG", "rule": "baseline_LONG", "symbol": f"S{k}USDT", "opened_at": t0 + timedelta(hours=k),
                     "roi": 1.0, "done": "true", "d1_state": "MID_SUPPORT", "d1_trend": "UP", "m5_pos": 0.5,
                     "timing": None, "best_offset": None})
    rep = CSR.aggregate(rows, [{"side": "LONG", "status": "CLOSED", "pnl_pct": -2.0, "timing": "LATE"}], days=14)
    st = next(r for r in rep["by_d1_state"] if r["key"] == ["LONG", "MID_SUPPORT"])
    assert st["n"] == 40 and st["delta"] == 2.0 and st["pieces_pos"] == 4
    md = CSR.render_markdown(rep)
    assert "중단선 지지" in md and "늦은 진입" in md


def test_sql_compiles_and_reads_only_paths():
    from app.workers import chart_timing_worker as W
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    for stmt in (CSR.paper_stmt(cutoff=now), CSR.real_stmt(cutoff=now),
                 W.paper_stmt(now=now, horizon=timedelta(hours=4), limit=10),
                 W.real_stmt(now=now, horizon=timedelta(hours=4), limit=10)):
        sql = str(stmt.compile(dialect=postgresql.dialect()))
        assert "SELECT" in sql and "progression" not in sql
    from app.models.paper_trade import PaperTrade
    upd = str(W._set_json_stmt(PaperTrade, "snapshot", "chart_timing", 1, {"label": "GOOD"}).compile(dialect=postgresql.dialect()))
    assert "jsonb_set" in upd and "{chart_timing}" in upd


def test_wiring():
    pw = (APP / "workers" / "paper_trading_worker.py").read_text(encoding="utf-8")
    i_mb = pw.find('t["snapshot"]["market_breadth"] = breadth')
    i_cs = pw.find('t["snapshot"]["chart_state"] = _cs')
    i_row = pw.find("row = PaperTrade(source=t[\"source\"]")
    assert 0 < i_mb < i_cs < i_row                                   # 가상 진입 행을 만들기 전에 붙인다
    assert "def _chart_state_for(" in pw and "series.allk[-60:]" in pw
    ls = (APP / "workers" / "learning_sync_worker.py").read_text(encoding="utf-8")
    assert '"chart_state": _chart_state_block(client, strategy, klines)' in ls
    sr = (APP / "workers" / "scheduler_runner.py").read_text(encoding="utf-8")
    assert 'guarded_job("chart_timing", 900, _chart_timing)' in sr and "run_chart_timing_once(decrypt_text)" in sr
    api = (APP / "api" / "v1" / "paper_trading.py").read_text(encoding="utf-8")
    assert '@router.get("/chart-state")' in api and '@router.get("/chart-state.md"' in api
    src = (APP / "services" / "chart_state.py").read_text(encoding="utf-8")
    assert "place_order" not in src and "ExecutionService" not in src   # 학습 전용
