"""가설 J·K 자동 판정 등록 (2026-10-16 사장님 「1번 진행」) — 11/15 KST 10:20 판정 보고서 자동 실행."""
from __future__ import annotations

import pathlib

from app.workers import verdict_report_worker as V

SCRIPTS = pathlib.Path(V.__file__).resolve().parents[2] / "scripts" / "entry_condition_study"


def test_jk_registered():
    assert V.SCRIPTS["jk"] == "jk_2026_11_15.py" and (SCRIPTS / "jk_2026_11_15.py").exists()
    assert V.parse_schedule(None)["2026-11-15"] == "jk"
    assert V.TITLES["jk"].startswith("🧪")


def test_jk_summary_lines():
    rep = "\n".join([
        "## § J 가설 J 판정 (SCORE_FROM 2026-10-17) — A1 SHORT n 31 · L SHORT n 30 · 맞대결 이긴 12 / 진 9",
        "A1 순수익 +3.10 · L +1.20 · 차 +1.90%p · 무작위 +0.20 → ✅ 통과",
        "하루 1건(그날 첫 진입) 순수익 -2.00 (n 25)",
        "판정: ⏳ 보류",
        "L 판정: 짝 120 · 날 13 · 날 평균의 평균 +0.40 (날 묶음 90% +0.10~+0.70) · 앞 +0.30 / 뒤 +0.50 · 플러스 날 9/13 → ✅ 통과",
        "S4 판정: 짝 240 · 날 28 · 날 평균의 평균 +3.10 (날 묶음 90% +0.80~+5.20) → ✅ 통과",
    ])
    out = V.summarize("jk", rep)
    assert "J (운영팀 SHORT 첫 1건 vs S4): A1 순수익 +3.10" in out and "✅ 통과" in out
    assert "K (LONG + 24h 시장폭<0.45): ⏳ 보류" in out and "하루 1건" in out
    assert "L (S4 트레일링 3%p vs 지금): 짝 120 · 날 13" in out and "S4 (날 단위 순수익): 짝 240 · 날 28" in out
    assert V.summarize("jk", "") == "(요약 줄 없음 — 원문 확인)"


def test_jk_scripts_do_not_run_on_import():
    for f in ("council_realistic_2026_10_16.py", "long_trend_k_2026_10_16.py", "strategy_audit_2026_10_16.py", "jk_2026_11_15.py",
              "s4_exit_compare_2026_10_17.py"):
        src = (SCRIPTS / f).read_text(encoding="utf-8")
        assert 'if __name__ == "__main__":\n    main()' in src.replace("\r\n", "\n"), f
    jk = (SCRIPTS / "jk_2026_11_15.py").read_text(encoding="utf-8")
    assert 'SCORE_FROM = "2026-10-17"' in jk and '"s4_exit_compare_2026_10_17.py"' in jk
