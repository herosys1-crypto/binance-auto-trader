from __future__ import annotations
import random

def exponential_backoff(attempt: int, base: float = 1.0, cap: float = 60.0, jitter: bool = True) -> float:
    delay = min(cap, base * (2 ** max(0, attempt - 1)))
    if jitter:
        return random.uniform(delay * 0.5, delay)
    return delay
