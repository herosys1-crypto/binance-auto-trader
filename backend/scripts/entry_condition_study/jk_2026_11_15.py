"""가설 J·K 판정 묶음 (2026-10-16 사전 등록 · 판정 ≈ 2026-11-15) — 읽기 전용.

판정 보고서 자동 실행(verdict_report_worker, 종류 "jk")이 이 파일의 main() 을 부른다.
  J = council_realistic_2026_10_16.py  (운영팀 SHORT 첫 1건 vs S4 규칙, SCORE_FROM 2026-10-17)
  K = long_trend_k_2026_10_16.py       (LONG 5규칙 + 진입 전 24h 시장폭 평균 < 0.45, SCORE_FROM 2026-10-17)
기준은 각 파일 머리말(사전 등록) 그대로 — 여기서 바꾸지 않는다.
수동:  docker compose exec -T api python - < scripts/entry_condition_study/jk_2026_11_15.py
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path("/app/scripts/entry_condition_study")
SCORE_FROM = "2026-10-17"
FILES = (("J", "council_realistic_2026_10_16.py", "60"), ("K", "long_trend_k_2026_10_16.py", "60"))


def _load(name: str, fname: str):
    spec = importlib.util.spec_from_file_location(f"jk_{name}", HERE / fname)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    old = {k: os.environ.get(k) for k in ("SCORE_FROM", "DAYS")}
    try:
        for name, fname, days in FILES:
            os.environ["SCORE_FROM"], os.environ["DAYS"] = SCORE_FROM, days     # 모듈 상수가 import 때 읽는다
            print(f"\n# ── 가설 {name} ({fname}) ──")
            _load(name, fname).main()
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


if __name__ == "__main__":
    main()
