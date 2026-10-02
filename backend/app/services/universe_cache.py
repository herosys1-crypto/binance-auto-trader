"""감시 종목(universe) 봉 스냅샷 — Fix 408 (Duel ext-universe-cache).

외부 전략 워커가 60초마다 전 심볼 24h 티커(무게 40, 공유 캐시 TTL 30초라 매번 미스)로 감시 종목을 다시 고르던 것을
**완성봉 하나에 한 번**만 고르게 한다. 판정은 완성봉당 한 번이므로 같은 봉 동안 감시 종목이 고정돼도 판정 대상 봉은 같다
(한 봉 중간에 상위 N 에 새로 든 종목은 다음 봉부터 판정 — 기존은 그 봉에서도 판정될 수 있었다).
GPT 초안 바탕 + Claude 감사: 봉 계산·설정 해석은 bar_gate 그대로 쓴다(복제하면 경계에서 어긋난다).
"""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone

from app.services import bar_gate as BG

KEY = "ext:universe"


def cached_universe(r, *, interval: str, interval_ms: int | None, settle_ms: int, top_n: int, min_qv: float,
                    enabled: object, now_ms: int, compute: Callable[[], list[str]]) -> tuple[list[str], str]:
    """(symbols, "snapshot"|"computed"). Redis·JSON 문제는 캐시 미스로 보고 compute() 결과를 쓴다(compute 예외는 그대로 전파).

    interval_ms = INTERVAL_MS.get(interval) (모르면 None → 매번 compute). enabled = 설정값(bar_gate.parse_flag 규칙, 기본 켬).
    """
    if not BG.parse_flag(enabled, default=True) or not interval_ms or interval_ms <= 0:
        return compute(), "computed"
    bar = BG.last_closed_open(now_ms, interval_ms, settle_ms)          # _closed_bars 가 판정하는 봉과 같은 함수·같은 시각
    try:
        raw = r.get(KEY)
        snap = json.loads(raw.decode() if isinstance(raw, bytes) else raw) if raw is not None else None
        if (isinstance(snap, dict) and snap.get("bar") == bar and snap.get("interval") == interval
                and snap.get("top_n") == top_n and snap.get("min_qv") == min_qv
                and isinstance(snap.get("symbols"), list) and all(isinstance(s, str) for s in snap["symbols"])):
            return list(snap["symbols"]), "snapshot"
    except Exception:  # noqa: BLE001 — Redis 장애·깨진 JSON = 캐시 미스
        pass
    symbols = compute()
    if symbols:                                                        # 빈 결과(티커 일시 장애)는 저장하지 않는다 → 다음 사이클 재시도
        snap = {"bar": bar, "interval": interval, "top_n": top_n, "min_qv": min_qv, "symbols": list(symbols),
                "at": datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).isoformat()}
        try:
            r.setex(KEY, max(3600, (2 * interval_ms + 999) // 1000), json.dumps(snap, separators=(",", ":")))
        except Exception:  # noqa: BLE001 — 쓰기 실패는 무시(계산 결과는 그대로 사용)
            pass
    return symbols, "computed"
