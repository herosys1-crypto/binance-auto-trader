"""D-139 지정가 판정 스크립트 — summarize 순수 함수."""
import importlib.util
from pathlib import Path

_p = Path(__file__).resolve().parents[1] / "scripts/entry_condition_study/limit_entry_verdict_2026_12_15.py"
_s = importlib.util.spec_from_file_location("lev", _p)
V = importlib.util.module_from_spec(_s)
_s.loader.exec_module(V)


def test_empty():
    assert V.summarize([])["verdict"] == "자료 없음"


def test_cost_only_gain_passes():
    rows = [("LONG", b, 1.0, "true", 1.0) for b in range(40) for _ in range(10)]
    o = V.summarize(rows)
    assert o["fill_pct"] == 100 and abs(o["diff"] - 0.16) < 1e-9 and o["verdict"] == "채택 후보"


def test_nofill_counts_as_zero_and_tail_fails():
    good = [("LONG", b, 1.0, "true", 1.0) for b in range(39) for _ in range(10)]
    bad = [("LONG", 99, 20.0, "false", None)] * 10              # 급등 봉 전부 미체결 → 놓친 +19.6
    o = V.summarize(good + bad)
    assert o["tail_diff"] < -3.0 and not o["checks"]["P4 하위5% 칸≥−3.0"] and o["verdict"] == "기각"


def test_bad_values_skipped():
    o = V.summarize([("LONG", 1, "nan", "true", 1.0), ("LONG", 1, 1.0, "true", None), ("LONG", 1, 1.0, "false", None)])
    assert o["n"] == 1 and o["fill_pct"] == 0
