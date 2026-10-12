"""🗄 Fix 446 (2026-10-12 사장님 「1번 진행해줘」 — 재시작해도 일봉 캐시 유지): 봉 증분 캐시의 Redis 저장소.

IncrementalKlines(store=...) 가 쓴다. 일봉만(기본) 종목마다 한 키 `kc:<prefix>:<interval>:<symbol>` 에
zlib 압축 JSON(base64)으로 둔다 — 300봉 ≈ 40KB → ≈10KB, 600종목 ≈ 6MB.
읽기·쓰기 실패·끔은 모두 「저장소 없음」 = 예전처럼 메모리 캐시만 (fail-open). 결과의 정확성은 캐시 쪽 증분 병합
검사(겹침·확정 봉 대조)가 지키므로 여기서는 형식만 다룬다.
"""
from __future__ import annotations

import base64
import json
import zlib
from typing import Any, Callable

TTL_S = 3 * 86400            # 3일 (Claude가 정함) — 매일 한 번 다시 쓰이므로 하루 이틀 멈춰도 남는다
MAX_RAW = 2_000_000          # 풀었을 때 2MB 넘으면 버린다(깨진 값 방어)

# system_settings (둘 다 Claude가 정함 · 재시작 불필요, 다음 사이클부터)
S_PERSIST = "kline_daily_persist"            # 1 = 일봉 캐시를 Redis 에 보관 (0 = 예전처럼 메모리만)
S_REFRESH_H = "kline_daily_full_refresh_h"   # 일봉 전체 재조회 주기(시간) — 기본 168(7일), 6~720. 6 = 예전과 같음
DEFAULT_REFRESH_H = 168.0


def db_getter(db: Any) -> Callable[[str], Any]:
    """system_settings 한 행 읽기(없음·실패 = None). 두 워커가 같은 키를 같은 방식으로 읽게."""
    def get(key: str) -> Any:
        if db is None:
            return None
        try:
            from app.models.system_setting import SystemSetting
            row = db.get(SystemSetting, key)
            return None if row is None else row.value
        except Exception:  # noqa: BLE001
            return None
    return get


def apply_settings(kc: Any, store: "RedisKlineStore", get: Callable[[str], Any]) -> dict:
    """워커가 사이클 시작에 부른다. get(key) → 설정 문자열|None. 실패·이상한 값 = 기본값."""
    def _s(k: str) -> str:
        try:
            v = get(k)
        except Exception:  # noqa: BLE001
            return ""
        return "" if v is None else str(v).strip()
    store.enabled = _s(S_PERSIST).lower() not in ("0", "false", "off", "no")
    try:
        h = float(_s(S_REFRESH_H) or DEFAULT_REFRESH_H)
    except ValueError:
        h = DEFAULT_REFRESH_H
    if not 6 <= h <= 720:                        # nan 도 여기서 기본값
        h = DEFAULT_REFRESH_H
    kc.set_full_refresh("1d", h * 3600)
    return {"persist": store.enabled, "refresh_h": h}


def _default_client() -> Any:
    from app.core.redis_client import get_redis_client
    return get_redis_client()


class RedisKlineStore:
    def __init__(self, prefix: str, intervals: frozenset[str] = frozenset({"1d"}), *, ttl_s: int = TTL_S,
                 client: Callable[[], Any] = _default_client) -> None:
        self.prefix = prefix
        self._intervals = frozenset(intervals)
        self.ttl_s = ttl_s
        self._client = client
        self.enabled = True          # 워커가 사이클마다 설정으로 바꾼다

    @property
    def intervals(self) -> frozenset[str]:
        return self._intervals if self.enabled else frozenset()

    def key(self, symbol: str, interval: str) -> str:
        return f"kc:{self.prefix}:{interval}:{symbol}"

    def load(self, symbol: str, interval: str) -> dict | None:
        raw = self._client().get(self.key(symbol, interval))
        if not raw:
            return None
        try:
            data = zlib.decompressobj().decompress(base64.b64decode(raw), MAX_RAW)
            d = json.loads(data)
        except Exception:  # noqa: BLE001 — 깨진 값 = 없는 것
            return None
        return d if isinstance(d, dict) and d.get("v") == 1 else None

    def save(self, symbol: str, interval: str, d: dict) -> None:
        body = json.dumps({"v": 1, **d}, separators=(",", ":"))
        self._client().setex(self.key(symbol, interval), self.ttl_s,
                             base64.b64encode(zlib.compress(body.encode(), 6)).decode())
