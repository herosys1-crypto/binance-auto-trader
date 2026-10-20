"""🏔 Fix 475 (2026-10-21 사장님 「a b로 해줘」) — 코인 시총·유통 비율 캐시 (공개 CoinGecko, 키 없음 · 거래소 IP 무게 0).

쓰는 곳: 정상 추세 눌림 LONG(대형, trend_pullback) 의 시총 10억$ 거르기 · 세력 그림 표시(pump_profile, Fix 476) 의 🐋 소형·큰손.
- refresh(redis): markets 8쪽(250×8) → 기호(대문자) → {"mcap","fdv","float"} · 같은 기호는 시총 큰 쪽 · 성공 기호 ≥ 300 일 때만
  Redis coin:mcap:v1 (3일) + coin:mcap:at 저장(모자라면 이전 값 유지). 매일 KST 08:50 + 시작 90초 뒤 (scheduler_runner).
- get(sym) / info(sym): 바이낸스 심볼(1000PEPEUSDT 등) → 기호로 바꿔 조회 · 프로세스 안 10분 캐시(Redis 객체별) · 실패·없음 = None.
받은 날 값이다(과거 시점 시총 아님). 주문·DB 쓰기 없음.
"""
from __future__ import annotations

import json
import logging
import math
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)

FIX = "Fix475"
KEY = "coin:mcap:v1"
AT_KEY = "coin:mcap:at"
TTL = 3 * 86400
PAGES = 8
MIN_OK = 300
LOCAL_TTL_S = 600
URL = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page={page}"


def _http(url: str) -> list:
    req = urllib.request.Request(url, headers={"User-Agent": "binance-auto-trader/coin-mcap", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as f:
        return json.loads(f.read())


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def fetch_all(fetch: Callable[[str], list] | None = None, *, page_gap: float = 8.0, retry_wait: float = 20.0,
              retries: int = 3, sleep: Callable[[float], None] = time.sleep) -> tuple[dict[str, dict], dict]:
    """→ ({기호: {mcap, fdv, float}}, stat). 실패 페이지는 건너뛴다(빈 페이지가 나와도 끝까지 본다)."""
    fetch = fetch or _http
    out: dict[str, dict] = {}
    stat: dict[str, Any] = {"pages_ok": 0, "pages_fail": 0, "rows": 0}
    for page in range(1, PAGES + 1):
        rows = None
        for attempt in range(retries + 1):
            try:
                rows = fetch(URL.format(page=page))
                break
            except Exception as e:  # noqa: BLE001 — 429·네트워크 = 잠시 뒤 다시
                if attempt < retries:
                    sleep(retry_wait)
                else:
                    logger.info("[%s] CoinGecko %d쪽 실패: %s", FIX, page, type(e).__name__)
        if not isinstance(rows, list):
            stat["pages_fail"] += 1
        else:
            stat["pages_ok"] += 1
            for r in rows:
                if not isinstance(r, dict):
                    continue
                s = str(r.get("symbol") or "").strip().upper()
                mc = _num(r.get("market_cap"))
                if not s or mc is None:
                    continue
                stat["rows"] += 1
                if s in out and (out[s]["mcap"] or 0) >= mc:
                    continue                                    # 같은 기호 = 시총 큰 쪽
                fdv = _num(r.get("fully_diluted_valuation"))
                out[s] = {"mcap": mc, "fdv": fdv, "float": (mc / fdv) if fdv else None}
        if page < PAGES:
            sleep(page_gap)
    return out, stat


def refresh(redis, fetch: Callable[[str], list] | None = None, now: datetime | None = None, **kw) -> dict:
    data, stat = fetch_all(fetch, **kw)
    stat["symbols"] = len(data)
    if len(data) < MIN_OK:
        stat["saved"] = False
        stat["why"] = f"기호 {len(data)} < {MIN_OK} → 이전 값 유지"
        logger.warning("[%s] 시총 갱신 안 함: %s", FIX, stat["why"])
        return stat
    redis.setex(KEY, TTL, json.dumps(data))
    redis.setex(AT_KEY, TTL, (now or datetime.now(timezone.utc)).isoformat())
    stat["saved"] = True
    _LOCAL.clear()
    logger.info("[%s] 시총 갱신: %s", FIX, stat)
    return stat


def base_of(symbol: str) -> str:
    b = str(symbol or "").strip().upper()
    if b.endswith("USDT"):
        b = b[:-4]
    for pre in ("1000000", "1000", "1M"):
        if b.startswith(pre) and len(b) > len(pre):
            return b[len(pre):]
    return b


_LOCAL: dict[int, tuple[float, dict]] = {}       # id(redis) → (받은 시각, 표)


def _table(redis) -> dict | None:
    if redis is None:
        try:
            from app.core.redis_client import get_redis_client
            redis = get_redis_client()
        except Exception:  # noqa: BLE001
            return None
    k = id(redis)
    hit = _LOCAL.get(k)
    if hit and time.time() - hit[0] < LOCAL_TTL_S:
        return hit[1]
    try:
        raw = redis.get(KEY)
        data = json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001 — 만료 뒤 읽기 실패 = 모름(옛 값으로 통과시키지 않는다 · 교차 감사)
        _LOCAL.pop(k, None)
        return None
    _LOCAL[k] = (time.time(), data if isinstance(data, dict) else {})
    return _LOCAL[k][1]


def info(symbol: str, redis=None) -> dict | None:
    t = _table(redis)
    if not t:
        return None
    v = t.get(base_of(symbol))
    return v if isinstance(v, dict) else None


def get(symbol: str, redis=None) -> float | None:
    v = info(symbol, redis)
    return _num(v.get("mcap")) if v else None
