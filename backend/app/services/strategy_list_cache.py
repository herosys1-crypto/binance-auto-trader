"""⚡ Fix 386 (2026-09-19 사장님) — 전략 목록(/strategies) 짧은 캐시 + 동시 요청 합치기.

사장님: "새전략 기존방식이 설정되지 않아" · "새전략에서 심볼 조회가 늦어" · "이전 심볼세팅값으로 나와야 하는데 이상해"

원인 (운영 측정 2026-09-19):
  · 대시보드가 보이는 탭마다 5초에 한 번 /strategies 를 부른다 → 2시간 5,113번(분당 43번 ≈ 탭 3~4개).
  · 한 번에 보관 안 된 전략 1,760건을 매번 새로 계산 = 1.0~1.5초 CPU → 이것만으로 1코어가 찬다
    (api 컨테이너 CPU 79% · 서버 부하 3.3~3.7 / 2코어).
  · 그래서 새 전략 모달의 목록 조회(이전 설정 자동 채움)·심볼 목록 조회가 줄을 서서 늦거나 끝나지 않았다.

해결: 같은 (사용자, 필터) 목록은 TTL 초 동안 한 번만 계산하고 나눠 쓴다. 동시에 들어온 요청은 하나만 계산한다.
  전략을 바꾸는 요청(GET 이 아닌 /api/v1/strategies*)이 오면 바로 비운다 (app/main.py 미들웨어) —
  정지·생성 직후 목록이 옛 상태로 남지 않게. 워커가 바꾼 상태는 최대 TTL 초 늦게 보인다 (화면 갱신 주기 5초보다 짧다).
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Hashable

TTL_SECONDS = 4.0                 # Claude가 정함 — 화면 새로고침(5초)보다 짧게
_CACHE: dict[Hashable, tuple[float, Any]] = {}
_LOCK = threading.Lock()          # 동시 계산 합치기 (목록 키는 몇 개뿐이라 전역 잠금으로 충분)
_GEN = 0                          # 비우기 세대 — 계산 도중 비워졌으면 그 결과는 저장하지 않는다
STATS = {"hit": 0, "miss": 0, "invalidate": 0}


def _fresh(key: Hashable, now: float) -> Any | None:
    hit = _CACHE.get(key)
    if hit is not None and now - hit[0] < TTL_SECONDS:
        return hit[1]
    return None


def get_or_build(key: Hashable, build: Callable[[], Any]) -> Any:
    got = _fresh(key, time.monotonic())
    if got is not None:
        STATS["hit"] += 1
        return got
    with _LOCK:
        got = _fresh(key, time.monotonic())          # 기다리는 동안 다른 요청이 채웠으면 그걸 쓴다
        if got is not None:
            STATS["hit"] += 1
            return got
        gen = _GEN
        value = build()
        if gen == _GEN:                               # 계산 중 전략이 바뀌었으면 저장하지 않는다
            _CACHE[key] = (time.monotonic(), value)
        STATS["miss"] += 1
        return value


def encode(items: Any) -> tuple[bytes, bytes]:
    """목록 → (JSON 바이트, gzip 바이트). FastAPI response_model 직렬화와 같은 규칙(mode=json · by_alias)."""
    import gzip
    from pydantic import TypeAdapter
    from app.schemas.strategy import StrategyDetailResponse
    global _TA
    if _TA is None:
        _TA = TypeAdapter(list[StrategyDetailResponse])
    raw = _TA.dump_json(items, by_alias=True)
    return raw, gzip.compress(raw, compresslevel=6)


_TA = None


def invalidate() -> None:
    global _GEN
    _GEN += 1
    _CACHE.clear()
    STATS["invalidate"] += 1


def should_invalidate(method: str, path: str) -> bool:
    return method.upper() not in ("GET", "HEAD", "OPTIONS") and path.startswith("/api/v1/strategies")
