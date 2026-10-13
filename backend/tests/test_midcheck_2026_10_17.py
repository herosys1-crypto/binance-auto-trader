"""10/17 중간 점검 스크립트 — 예상 계산 (읽기 전용 스크립트, 운영 DB 부분은 미리 실행으로 확인)."""
import importlib.util
from pathlib import Path

_p = Path(__file__).resolve().parents[1] / "scripts" / "entry_condition_study" / "midcheck_2026_10_17.py"
_s = importlib.util.spec_from_file_location("midcheck_2026_10_17", _p)
M = importlib.util.module_from_spec(_s)
_s.loader.exec_module(M)


def test_project_and_days():
    assert M.project(10, 2.0, 12.0) == 10 / 2 * 10          # 마지막 이틀 진입분 제외
    assert M.project(10, 0, 12.0) == 0.0
    assert M.project_days(2, 2.0, 12.0, 14) == 10             # 매일 진입 → 남은 기간 전부
    assert M.project_days(1, 4.0, 12.0, 14) == 2              # 넷 중 하루만 → 1/4
    assert M.project_days(0, 4.0, 12.0, 14) == 0
    assert M.project_days(5, 2.0, 30.0, 14) == 14             # 달력 일수가 상한


def test_status():
    assert M.status(0, 0, 0, 0, 30, 7).startswith("—")
    assert M.status(31, 40, 100, 8, 30, 7) == "✅ 충분"
    assert M.status(5, 40, 100, 8, 30, 7) == "✅ 충분 예상"
    assert M.status(5, 40, 100, 4, 30, 7) == "⚠️ 부족 예상"
    assert M.status(5, 6, 20, 10, 30, 7) == "⚠️ 부족 예상"
