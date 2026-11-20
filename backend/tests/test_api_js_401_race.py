"""2026-11-20 모바일 로그인 직후 튕김 — api.js 401 카운터 경합을 node 로 실제 실행해 고정한다.

원인: 로그인 전 토큰 없이 나간 폴링 요청의 401 이 로그인 뒤 도착해 연속 401 카운터(3회)를 채우고
새 토큰까지 logout() 시켰다 (nginx 실측 11/20 13:07:36 로그인 200 → 4초 뒤 전부 401 "Not authenticated").
"""
import os
import shutil
import subprocess

import pytest

_NODE = shutil.which("node")
_TEST = os.path.join(os.path.dirname(__file__), "js", "api_401_race.test.js")


@pytest.mark.skipif(_NODE is None, reason="node 없음")
def test_api_js_401_race():
    proc = subprocess.run([_NODE, _TEST], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "3/3 OK" in proc.stdout
