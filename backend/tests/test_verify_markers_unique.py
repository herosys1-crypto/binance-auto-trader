"""배포 검사기 표식 표 — 같은 파일 이름이 두 번 들어가면 앞 줄이 조용히 사라진다(10/15: Fix 420·433·435 표식이 검사되지 않고 있었다)."""
from __future__ import annotations

import ast
import pathlib
from collections import Counter

BACKEND = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = BACKEND / "scripts" / "verify_fix414_418.py"


def _markers():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "CODE_MARKERS":
            return [(k.value, [e.value for e in v.elts]) for k, v in zip(n.value.keys, n.value.values)]
    raise AssertionError("CODE_MARKERS 없음")


def test_no_duplicate_paths():
    dup = [k for k, c in Counter(k for k, _ in _markers()).items() if c > 1]
    assert not dup, f"같은 파일이 두 번: {dup} — 한 줄로 합칠 것"


def test_every_marker_exists_in_its_file():
    missing = []
    for rel, ms in _markers():
        src = (BACKEND / rel).read_text(encoding="utf-8")
        missing += [f"{rel}: {m}" for m in ms if m not in src]
    assert not missing, missing
