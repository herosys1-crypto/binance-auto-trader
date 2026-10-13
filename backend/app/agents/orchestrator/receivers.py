"""📥 오케스트라 메시지 받는 쪽 (Fix 450 — 2026-10-14 사장님 「전부 A로 진행해줘」, docs/spec/ORCHESTRA_EVENT_WIRING_2026-10-14.md).

10/13 운영 48h: 팀 사이 메시지 7종이 전부 받는 팀 0. 여기서 두 가지를 받는다 — **기록만**(주문·설정 변경 없음, 원칙 1).
  ① 감시 진단(`orchestra.health_check`)  → Redis `orchestra:health:last` (마지막 진단)
  ② 학습 완료(`learning.daily_done` · `pattern_learning.done`) → Redis 해시 `orchestra:learning:last` (팀별 마지막 시각)
버스를 처음 만들 때(get_event_bus) 자동 설치 — 보내는 워커와 같은 프로세스에서 받는다. Redis 실패 = 기록 생략(fail-open).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.agents.orchestrator.event_types import EventType

logger = logging.getLogger(__name__)

HEALTH_KEY = "orchestra:health:last"
LEARNING_KEY = "orchestra:learning:last"
TTL_S = 7 * 86400                         # 7일 (Claude가 정함) — 멈춘 팀도 일주일은 「마지막 시각」이 보이게
LEARNING_STALE_H = 26.0                   # 하루 한 번 도는 팀 + 2시간 여유 (Claude가 정함)
_VALUE = (str, int, float, bool, type(None))


def _redis():
    from app.core.redis_client import get_redis_client
    return get_redis_client()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _plain(data: dict) -> dict:
    return {k: v for k, v in (data or {}).items() if isinstance(v, _VALUE)}


def team_of(event: Any, data: dict) -> str:
    """보낸 팀 이름 — data 의 team/_from, 없으면 패턴 학습 이벤트는 pattern_learning."""
    t = (data or {}).get("team") or (data or {}).get("_from")
    if t:
        return str(t)
    if getattr(event, "value", event) == EventType.PATTERN_LEARNING_DONE.value:
        return "pattern_learning"
    return "unknown"


def on_health(event: Any, data: dict) -> None:
    try:
        _redis().setex(HEALTH_KEY, TTL_S, json.dumps({"at": _now(), **_plain(data)}))
    except Exception as e:  # noqa: BLE001
        logger.debug("[receivers] 진단 기록 실패: %s", e)


def on_learning(event: Any, data: dict) -> None:
    if (data or {}).get("briefing"):                         # 아침 브리핑 = 학습 아님 (반박 리뷰)
        return
    try:
        r = _redis()
        r.hset(LEARNING_KEY, team_of(event, data),
               json.dumps({"at": _now(), "event": getattr(event, "value", str(event)), **_plain(data)}))
        prune_learning(r)
    except Exception as e:  # noqa: BLE001
        logger.debug("[receivers] 학습 기록 실패: %s", e)


def prune_learning(r, now: datetime | None = None) -> list[str]:
    """반박 리뷰: 해시 전체 expire 는 쓸 때마다 늘어나 옛 칸이 영원히 남는다 → 칸별로 7일 지난 것을 지운다."""
    now = now or datetime.now(timezone.utc)
    gone = []
    for k, v in (r.hgetall(LEARNING_KEY) or {}).items():
        try:
            age = (now - datetime.fromisoformat(json.loads(v)["at"])).total_seconds()
        except Exception:  # noqa: BLE001
            age = TTL_S + 1                                  # 깨진 칸도 지운다
        if age > TTL_S:
            r.hdel(LEARNING_KEY, k)
            gone.append(k.decode() if isinstance(k, bytes) else str(k))
    return gone


def alert_once(team: str, ttl_s: int) -> bool:
    """학습 멈춤 알림 중복 방지 — Redis 에 둔다(재시작해도 유지). Redis 실패 = True(알림은 보낸다, 호출자가 메모리로 한 번 더 거른다)."""
    try:
        return bool(_redis().set(f"orchestra:learning:alerted:{team}", "1", nx=True, ex=int(ttl_s)))
    except Exception:  # noqa: BLE001
        return True


def install(bus) -> None:
    """key 구독 = 여러 번 불러도 하나만 (Fix 449)."""
    bus.subscribe(EventType.ORCHESTRA_HEALTH_CHECK, on_health, key="receiver:health")
    for ev in (EventType.DAILY_LEARNING_DONE, EventType.PATTERN_LEARNING_DONE):
        bus.subscribe(ev, on_learning, key="receiver:learning")


def health_last() -> dict | None:
    try:
        raw = _redis().get(HEALTH_KEY)
        return json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        return None


def learning_last() -> dict[str, dict]:
    try:
        raw = _redis().hgetall(LEARNING_KEY) or {}
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for k, v in raw.items():
        try:
            out[k.decode() if isinstance(k, bytes) else str(k)] = json.loads(v)
        except Exception:  # noqa: BLE001
            continue
    return out


def stale_learning(rec: dict[str, dict], now: datetime | None = None, hours: float = LEARNING_STALE_H) -> list[tuple[str, float]]:
    """(팀, 지난 시간 h) — hours 넘게 학습 완료 기록이 없는 팀. 시각을 못 읽으면 건너뛴다."""
    now = now or datetime.now(timezone.utc)
    out = []
    for team, v in rec.items():
        try:
            age = (now - datetime.fromisoformat(v["at"])).total_seconds() / 3600
        except Exception:  # noqa: BLE001
            continue
        if age > hours:
            out.append((team, round(age, 1)))
    return sorted(out)
