"""Fix 441 — 10/23~25 통합 판정 보고서: 사전 등록 기준(2026-10-11 고정)."""
from __future__ import annotations

import importlib.util
import pathlib
from datetime import date, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("verdict_2026_10_25", ROOT / "scripts" / "entry_condition_study" / "verdict_2026_10_25.py")
V = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(V)

D0 = date(2026, 10, 11)


def _rows(n_days=10, per_day=5, roi=lambda i, k: 2.0, side="LONG"):
    out = []
    for i in range(n_days):
        for k in range(per_day):
            out.append({"d": D0 + timedelta(days=i), "side": side, "symbol": f"S{k}", "ts": k, "roi": roi(i, k)})
    return out


def _base(n_days=10, side="LONG", v=0.0):
    return {(side, D0 + timedelta(days=i)): v for i in range(n_days)}


def test_criteria_are_frozen():
    assert V.CRIT == {"min_n": 30, "min_days": 7, "win_days": 0.5, "live_min_n": 5, "gate_min_n": 30}
    assert V.CUTOFFS["regime"] == "2026-10-11T03:05:00+00:00" and V.CUTOFFS["consensus"] == "2026-10-10T22:45:00+00:00"


def test_pass():
    ev = V.evaluate(_rows(), _base())
    assert ev["verdict"] == "✅ 통과" and ev["n"] == 50 and ev["days"] == 10
    assert ev["cap1_usdt"] == 2.0 * 10 / 100 * 10 and ev["win_days"] == 1.0


def test_hold_when_small():
    assert V.evaluate(_rows(n_days=6), _base())["verdict"] == "⏳ 보류"          # 7일 미만
    assert V.evaluate(_rows(n_days=10, per_day=2), _base())["verdict"] == "⏳ 보류"   # n 20 < 30
    assert V.evaluate([], {})["verdict"] == "⏳ 보류"


def test_reject_reasons():
    ev = V.evaluate(_rows(roi=lambda i, k: 2.0 if i < 5 else -1.0), _base())      # 뒤 절반 −
    assert ev["verdict"] == "❌ 기각" and "뒤 절반" in ev["why"]
    ev2 = V.evaluate(_rows(roi=lambda i, k: 1.0), _base(v=3.0))                  # 무작위가 더 좋다
    assert ev2["verdict"] == "❌ 기각" and "무작위" in ev2["why"]
    ev3 = V.evaluate(_rows(roi=lambda i, k: -5.0 if k == 0 else 4.0), _base())   # 하루 첫 건이 늘 진다
    assert "하루 1건" in ev3["why"]


def test_regime_ok_matches_two_line_rule():
    assert V.regime_ok("LONG", 0.39, None) is True and V.regime_ok("LONG", 0.4, None) is False
    assert V.regime_ok("LONG", None, None) is None and V.regime_ok("LONG", True, None) is None
    assert V.regime_ok("SHORT", None, 10.0) is True and V.regime_ok("SHORT", None, 9.9) is False
    assert V.regime_ok("SHORT", None, "x") is None


def test_live_verdict():
    assert V.live_verdict(3.0, 4) == "⏳ 보류" and V.live_verdict(3.0, 5) == "✅ 통과" and V.live_verdict(-0.1, 9) == "❌ 기각"


def test_read_only():
    src = (ROOT / "scripts" / "entry_condition_study" / "verdict_2026_10_25.py").read_text(encoding="utf-8")
    low = src.lower()
    assert "commit" not in low and "update " not in low and "insert " not in low and "delete " not in low and "setex" not in low


def test_first_bar_tie_mean_and_warning():
    """10/20 판정 전 점검 — 첫 봉 동점: 판정은 정렬 순서의 첫 1건(SQL ORDER BY 로 고정) · 동점 평균은 참고 + 부호가 갈리면 ⚠️."""
    rows = []
    for i in range(10):
        d = D0 + timedelta(days=i)
        rows += [{"d": d, "side": "LONG", "symbol": "A", "ts": 0, "roi": 4.0},     # 첫 봉 동점 2개: +4 / −10 → 평균 −3
                 {"d": d, "side": "LONG", "symbol": "B", "ts": 0, "roi": -10.0},
                 {"d": d, "side": "LONG", "symbol": "C", "ts": 1, "roi": 9.0},
                 {"d": d, "side": "LONG", "symbol": "D", "ts": 2, "roi": 9.0}]
    ev = V.evaluate(rows, _base())
    assert ev["cap1_usdt"] == 4.0 * 10 / 100 * 10              # 입력 순서의 첫 1건(A) — 기준 그대로
    assert ev["cap1_tie_usdt"] == -3.0 * 10 / 100 * 10
    assert "동점 순서에 달림" in ev["why"]
    assert "동점 순서" not in V.evaluate(_rows(), _base())["why"]   # 동점 없으면 경고 없음


def test_sql_orders_ties():
    src = (ROOT / "scripts" / "entry_condition_study" / "verdict_2026_10_25.py").read_text(encoding="utf-8")
    assert "order by entry_bar_ts, opened_at, md5(symbol), rule" in src
