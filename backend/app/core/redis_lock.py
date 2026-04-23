from __future__ import annotations

import time
from contextlib import contextmanager
from uuid import uuid4

from redis import Redis


class RedisLockError(Exception):
    pass


@contextmanager
def redis_lock(
    redis_client: Redis,
    key: str,
    ttl_seconds: int = 30,
    wait_timeout_seconds: int = 0,
):
    token = uuid4().hex
    deadline = time.time() + wait_timeout_seconds

    acquired = False
    while time.time() <= deadline or (wait_timeout_seconds == 0 and not acquired):
        acquired = bool(redis_client.set(key, token, nx=True, ex=ttl_seconds))
        if acquired:
            break
        if wait_timeout_seconds == 0:
            break
        time.sleep(0.1)

    if not acquired:
        raise RedisLockError(f"Failed to acquire lock: {key}")

    try:
        yield token
    finally:
        current = redis_client.get(key)
        if current == token:
            redis_client.delete(key)
