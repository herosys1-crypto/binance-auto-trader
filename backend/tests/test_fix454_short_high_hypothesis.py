"""🧪 Fix 454 — 가설 I 사전 등록: 장세 필터 안 SHORT 중 시장폭 > 0.6 빼기 (2026-10-14, 전략 손실 진단 감사관 제안)."""
import importlib.util
import pathlib
from datetime import date, timedelta

P = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "entry_condition_study" / "verdict_2026_10_25.py"
_s = importlib.util.spec_from_file_location("verdict_454", P)
V = importlib.util.module_from_spec(_s)
_s.loader.exec_module(V)
D0 = date(2026, 10, 15)


def _rows(mb, roi_of, days=10, per=5):
    return [{"d": D0 + timedelta(days=i), "roi": roi_of(i), "mb": mb} for i in range(days) for _ in range(per)]


def test_cutoff_registered_after_hypothesis():
    assert V.CUTOFFS["short_high"] == "2026-10-14T04:00:00+00:00" and V.HIGH_BREADTH == 0.6


def test_exclusion_candidate():
    r = _rows(0.7, lambda i: -2.0) + _rows(0.5, lambda i: 1.0)
    h = V.short_high_hypothesis(r)
    assert h["verdict"] == "✅ 제외 후보" and h["high"]["n"] == 50 and h["rest"]["mean"] == 1.0


def test_rejected_when_one_half_positive_or_not_worse():
    r = _rows(0.7, lambda i: -3.0 if i < 5 else 1.0) + _rows(0.5, lambda i: 1.0)
    assert V.short_high_hypothesis(r)["verdict"].startswith("❌")
    r2 = _rows(0.7, lambda i: -1.0) + _rows(0.5, lambda i: -2.0)          # 나머지가 더 나쁘다
    assert "나머지 칸보다 낮지 않음" in V.short_high_hypothesis(r2)["why"]


def test_hold_when_small_and_none_breadth_ignored():
    r = _rows(0.7, lambda i: -2.0, days=3) + [{"d": D0, "roi": -50.0, "mb": None}]
    h = V.short_high_hypothesis(r)
    assert h["verdict"] == "⏳ 보류" and h["high"]["n"] == 15


def test_section_printed():
    src = P.read_text(encoding="utf-8")
    assert "## I. 🧪 가설(Fix 454)" in src and 'CUTOFFS["short_high"]' in src
