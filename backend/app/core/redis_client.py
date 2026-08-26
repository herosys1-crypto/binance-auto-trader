from __future__ import annotations

import threading

import redis

from app.core.config import settings

# ═══════════════════════════════════════════════════════════════════════════
# 🚨 Fix 126 (2026-08-26): Redis 클라이언트 싱글턴 (연결 풀 재사용)
#
# 옛 코드:
#     def get_redis_client():
#         return redis.Redis.from_url(settings.redis_url, decode_responses=True)
#
# from_url 은 호출할 때마다 「새 Redis 객체 + 새 ConnectionPool」을 만든다.
# 이 함수는 코드베이스 전역에서 불리는데, 특히 Fix 118(호출 계측) /
# Fix 122(klines 캐시) / Fix 124(weight 거버너) 를 「Binance 요청당 실행 경로」에
# 넣으면서 요청 1건마다 Redis 연결이 3~4개씩 새로 생기게 됐다.
# 실측 부하가 분당 1,400 요청이므로 분당 수천 개의 TCP 연결 = 소켓/FD 고갈 위험.
#
# 신: 프로세스당 하나의 Redis 객체를 공유 (redis-py 의 ConnectionPool 은
#     thread-safe 하며 내부적으로 연결을 재사용한다).
#     - 타임아웃을 명시해 Redis 지연이 「거래 경로」를 붙잡지 않게 한다.
#       (계측/캐시가 거래를 멈추면 안 된다 = 이 값들이 그 보험)
#     - health_check_interval 로 죽은 연결 자동 감지
# ═══════════════════════════════════════════════════════════════════════════

_client: redis.Redis | None = None
_lock = threading.Lock()

# 거래 경로를 붙잡지 않기 위한 짧은 타임아웃 (초).
# 캐시/계측이 목적이므로 느린 Redis 는 「없는 것」으로 취급하는 편이 안전하다.
REDIS_SOCKET_TIMEOUT = 1.5
REDIS_CONNECT_TIMEOUT = 1.5


def get_redis_client() -> redis.Redis:
    """프로세스 공유 Redis 클라이언트 (연결 풀 재사용).

    ⚠️ 반환 객체를 close() 하지 말 것 — 전역 공유 풀이다.
    """
    global _client
    c = _client
    if c is not None:
        return c
    with _lock:
        if _client is None:
            _client = redis.Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_timeout=REDIS_SOCKET_TIMEOUT,
                socket_connect_timeout=REDIS_CONNECT_TIMEOUT,
                health_check_interval=30,
                retry_on_timeout=False,
            )
        return _client


def reset_redis_client() -> None:
    """테스트/재설정용 — 싱글턴 폐기 (다음 호출에서 새로 생성)."""
    global _client
    with _lock:
        old, _client = _client, None
    if old is not None:
        try:
            old.close()
        except Exception:
            pass
