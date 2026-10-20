"""가설 M 「세력 그림 S4」 (2026-10-21 사전 등록 · 11/15 jk 자동 판정)."""
from __future__ import annotations

import importlib.util
import pathlib
from datetime import date, datetime, timedelta, timezone

from app.workers import verdict_report_worker as V

SCRIPTS = pathlib.Path(V.__file__).resolve().parents[2] / "scripts" / "entry_condition_study"
_s = importlib.util.spec_from_file_location("s4m", SCRIPTS / "s4_pattern_m_2026_11_15.py")
M = importlib.util.module_from_spec(_s)
_s.loader.exec_module(M)
D0 = date(2026, 10, 21)


def _lab(plain_v, other_v, days=10, per=4, pump_v=None):
    out = []
    for i in range(days):
        d = D0 + timedelta(days=i)
        out += [(d, M.PLAIN, plain_v)] * per + [(d, "랠리 중간 속도", other_v)] * per
        if pump_v is not None:
            out += [(d, M.PUMP2, pump_v)] * per
    return out


def test_m1_drop_plain_candidate_and_reject():
    assert M.verdict_m1(_lab(-1.0, 2.0))[0] == "✅ 평범 문맥 빼기 후보"
    assert M.verdict_m1(_lab(0.5, 2.0))[0] == "❌ 기각(지금 그대로)"
    assert M.verdict_m1(_lab(-1.0, 2.0, days=5))[0] == "⏳ 표본 부족"          # 날 < 8
    assert M.verdict_m1(_lab(-1.0, 2.0, per=2))[0] == "⏳ 표본 부족"           # n 20 < 30


def test_m2_pump_size_up():
    assert M.verdict_m2(_lab(0.0, 1.0, days=14, pump_v=3.0))[0] == "✅ ② 문맥 크기 키우기 후보"
    assert M.verdict_m2(_lab(0.0, 3.0, days=14, pump_v=1.0))[0] == "❌ 기각"
    assert M.verdict_m2(_lab(0.0, 1.0, days=10, pump_v=3.0))[0] == "⏳ 표본 부족"   # 날 < 12


def test_label_uses_previous_closed_day_only():
    """진입 날 봉과 그 뒤 봉은 판정에 들어가지 않는다(미래 참조 없음)."""
    day_ms = 86_400_000
    start = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp() * 1000)
    kl = [[start + i * day_ms, "1", "1", "1", "1", "0", 0, "1"] for i in range(140)]
    seen = []

    def ctx(k, t):
        seen.append((len(k), t))
        return "x"
    at = datetime.fromtimestamp((start + 120 * day_ms + 3_600_000) / 1000, timezone.utc)   # 120번째 봉 01:00
    M.label_rows([("AUSDT", at, 1.0)], lambda s: kl, ctx)
    assert seen == [(140, 119)]


def test_jk_bundle_and_summary_include_m():
    jk = (SCRIPTS / "jk_2026_11_15.py").read_text(encoding="utf-8")
    assert '("M", "s4_pattern_m_2026_11_15.py", "60", "2026-10-21")' in jk
    out = V.summarize("jk", "M1 판정: ⏳ 표본 부족 — 평범 n 3\nM2 판정: ✅ ② 문맥 크기 키우기 후보 — 두 칸 모두 있는 날 14")
    assert "M1 (평범 문맥 S4 빼기): ⏳ 표본 부족" in out and "M2 (② 펌프·회귀 문맥 크기 키우기): ✅" in out
    src = (SCRIPTS / "s4_pattern_m_2026_11_15.py").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert 'if __name__ == "__main__":\n    main()' in src
    low = src.lower()
    assert "commit" not in low and "update " not in low and "insert " not in low and "delete " not in low
