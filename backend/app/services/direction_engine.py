"""🧭 Fix 488 방향 엔진 v1 (그림자) — 사장님 11/11 「… 모든 전략을 개선하는 방향으로 만들어줘 전면 개편도 가능해」 · 11/12 「다음으로 진행해줘 … 개발을 완료해줘」.

사양: docs/spec/direction_engine_v1_spec_2026-11-12.md · 결정 D-113·116·119·120.
그날 진입 방향 = 직전 window_h 시간에 **이미 마감된**(closed_at < day_start) 무작위 기준 거래(baseline_LONG/SHORT)의
방향별 평균 roi 가 **낮았던 쪽** (역방향). 어느 쪽이든 min_n 건 미만이거나 평균이 같으면 None(그날 쉼).
24개월 백테스트: 역방향 +0.39 %p/건 · 추격(이긴 쪽) −1.23 · 지정가 진입이면 기회당 +0.47 (90% 하한 −0.05, 얇다).

이 모듈은 **판정과 기록만** 한다 — 주문 없음. 실주문 경로는 그림자 판정 통과 + 사장님 승인 뒤 별도 Fix.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

logger = logging.getLogger(__name__)

S_WINDOW_H = "dir_engine_window_h"      # 「Claude가 정함」 24 — 24개월 12·48h 도 비슷(+0.43~+0.46)
S_MIN_N = "dir_engine_min_n"            # 「Claude가 정함」 20
DEFAULT_WINDOW_H = 24
DEFAULT_MIN_N = 20
KEY = "dir:engine:{day}"                # Redis — 날마다 판정 기록 (120일)
LATEST = "dir:engine:latest"
TTL_SEC = 120 * 86400
SIDES = ("LONG", "SHORT")


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def decide(closed: Iterable[tuple[str, datetime, Any]], day_start: datetime, *,
           window_h: int = DEFAULT_WINDOW_H, min_n: int = DEFAULT_MIN_N) -> dict[str, Any]:
    """closed = (side, closed_at(aware), roi). [day_start − window_h, day_start) 안에 마감된 행만 쓴다(미래 참조 없음).
    반환 {"side": "LONG"|"SHORT"|None, "n_long", "n_short", "m_long", "m_short", "why"}."""
    lo = day_start - timedelta(hours=window_h)
    acc = {s: [0, 0.0] for s in SIDES}
    for side, ca, roi in closed:
        if side not in acc or ca is None or not (lo <= ca < day_start):
            continue
        r = _f(roi)
        if r is None:
            continue
        acc[side][0] += 1
        acc[side][1] += r
    out: dict[str, Any] = {"n_long": acc["LONG"][0], "n_short": acc["SHORT"][0], "m_long": None, "m_short": None}
    for s in SIDES:
        if acc[s][0]:
            out[f"m_{s.lower()}"] = round(acc[s][1] / acc[s][0], 4)
    if acc["LONG"][0] < min_n or acc["SHORT"][0] < min_n:
        out.update(side=None, why=f"표본 부족 (LONG {acc['LONG'][0]} · SHORT {acc['SHORT'][0]} < {min_n})")
        return out
    ml, ms = acc["LONG"][1] / acc["LONG"][0], acc["SHORT"][1] / acc["SHORT"][0]   # 반올림 전 값으로 비교(감사 지적)
    if ml == ms:
        out.update(side=None, why="두 방향 같음")
        return out
    out.update(side="SHORT" if ml > ms else "LONG", why="직전 진 쪽(역방향)")
    return out


def _int_setting(get, key: str, default: int, lo: int, hi: int) -> int:
    try:
        v = get(key)
        return max(lo, min(hi, int(float(v)))) if v is not None else default
    except (TypeError, ValueError):
        return default


def run_once(now: datetime | None = None) -> dict[str, Any]:
    """하루 1회(00:05 UTC). 오늘(UTC) 방향을 판정해 Redis 에 남긴다. 읽기·기록 전용."""
    from sqlalchemy import text

    from app.core.database import SessionLocal
    from app.core.redis_client import get_redis_client
    from app.models.system_setting import SystemSetting

    now = now or datetime.now(timezone.utc)
    day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    db = SessionLocal()
    try:
        def get(k: str):
            row = db.get(SystemSetting, k)
            return row.value if row else None
        window_h = _int_setting(get, S_WINDOW_H, DEFAULT_WINDOW_H, 1, 168)
        min_n = _int_setting(get, S_MIN_N, DEFAULT_MIN_N, 1, 1000)
        rows = db.execute(text("""
            SELECT side, closed_at, engines->'live'->>'roi' AS roi FROM paper_trades
            WHERE source = 'live' AND status = 'CLOSED' AND rule IN ('baseline_LONG', 'baseline_SHORT')
              AND closed_at >= :lo AND closed_at < :hi
        """), {"lo": day_start - timedelta(hours=window_h), "hi": day_start}).fetchall()
    finally:
        db.rollback()
        db.close()
    res = decide(((r.side, r.closed_at, r.roi) for r in rows), day_start, window_h=window_h, min_n=min_n)
    res.update(day=day_start.date().isoformat(), window_h=window_h, min_n=min_n, at=now.isoformat())
    try:
        r = get_redis_client()
        blob = json.dumps(res, ensure_ascii=False)
        r.setex(KEY.format(day=res["day"]), TTL_SEC, blob)
        r.setex(LATEST, TTL_SEC, blob)
    except Exception as e:  # noqa: BLE001 — 기록 실패가 다른 잡을 막지 않게
        logger.warning("[Fix488] 방향 엔진 기록 실패: %s", e)
    logger.info("[Fix488] 방향 엔진 %s → %s (%s)", res["day"], res["side"], res["why"])
    return res
