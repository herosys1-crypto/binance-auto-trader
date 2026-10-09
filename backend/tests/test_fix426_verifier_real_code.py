"""Fix 426 — 배포 검사기의 코드 층은 **실제 저장소 코드**로도 통과해야 한다.

Fix 424·425 가 외부 전략 워커 15분 루프 머리를 바꿔 verify_ip_weight 의 표식(Fix 406)이 운영 배포 검사에서 FAIL 했다
(코드는 정상, 검사기 표식만 낡음). 합성 텍스트 테스트만으로는 못 잡았다 → 실제 파일로 코드 층을 돌린다.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _run(check):
    fails, oks = [], []
    check(oks.append, fails.append)
    return oks, fails


def test_verify_ip_weight_code_layer_passes_on_repo():
    import verify_ip_weight as V
    oks, fails = _run(lambda ok, fail: V._check_code(ROOT, ok, fail))
    assert not fails, fails


def test_verify_fix414_418_code_layer_passes_on_repo():
    import verify_fix414_418 as V
    oks, fails = _run(lambda ok, fail: V._check_code(ROOT, ok, fail))
    assert not fails, fails
