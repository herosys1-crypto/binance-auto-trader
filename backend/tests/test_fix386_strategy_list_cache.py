"""⚡ Fix 386 (2026-09-19 사장님) — 전략 목록 캐시.

사장님: "새전략 기존방식이 설정되지 않아" · "새전략에서 심볼 조회가 늦어" · "이전 심볼세팅값으로 나와야 하는데 이상해"
원인: 대시보드 탭마다 5초 폴링 × /strategies 1,760건 계산(1~1.5초) = 분당 43번 → api CPU 79% · 모달 조회가 줄을 섰다.
"""
import threading
import time
from pathlib import Path

from app.services import strategy_list_cache as LC

APP = Path(__file__).resolve().parents[1] / "app"


def test_hit_within_ttl_and_rebuild_after(monkeypatch):
    LC.invalidate()
    calls = []
    build = lambda: calls.append(1) or ["x"]            # noqa: E731
    assert LC.get_or_build("k", build) == ["x"] and LC.get_or_build("k", build) == ["x"]
    assert len(calls) == 1
    real = time.monotonic
    monkeypatch.setattr(LC.time, "monotonic", lambda: real() + LC.TTL_SECONDS + 1)
    LC.get_or_build("k", build)
    assert len(calls) == 2


def test_keys_are_separate():
    LC.invalidate()
    assert LC.get_or_build(("list", 1, None, None, False), lambda: [1]) == [1]
    assert LC.get_or_build(("list", 1, None, "BTCUSDT", False), lambda: [2]) == [2]
    assert LC.get_or_build(("list", 1, None, None, True), lambda: [3]) == [3]


def test_concurrent_requests_build_once():
    LC.invalidate()
    calls = []

    def slow():
        calls.append(1)
        time.sleep(0.2)
        return ["v"]
    out = []
    ts = [threading.Thread(target=lambda: out.append(LC.get_or_build("c", slow))) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(calls) == 1 and out == [["v"]] * 6


def test_invalidate_during_build_is_not_stored():
    LC.invalidate()

    def build_and_change():
        LC.invalidate()                                  # 계산 도중 전략이 바뀜
        return ["old"]
    LC.get_or_build("g", build_and_change)
    assert LC._CACHE == {}


def test_which_requests_invalidate():
    assert LC.should_invalidate("POST", "/api/v1/strategies")
    assert LC.should_invalidate("PATCH", "/api/v1/strategies/12/settings")
    assert LC.should_invalidate("DELETE", "/api/v1/strategies/12")
    assert not LC.should_invalidate("GET", "/api/v1/strategies")
    assert not LC.should_invalidate("POST", "/api/v1/auto-control/settings")


def test_wiring():
    crud = (APP / "api" / "v1" / "strategies" / "crud.py").read_text(encoding="utf-8")
    assert "_LC.get_or_build(" in crud and "def list_strategies_endpoint(" in crud
    assert "\ndef list_strategies(" in crud, "본문은 원래 이름 그대로 (다른 테스트·직접 호출이 이 이름을 본다)"
    main = (APP / "main.py").read_text(encoding="utf-8")
    assert "should_invalidate(request.method, request.url.path)" in main
    assert LC.TTL_SECONDS <= 5.0, "화면 새로고침(5초)보다 길면 목록이 한 박자 늦게 보인다"
