"""🧑‍⚖️ Fix 430 — 전략 운영팀 성적표 워커 (하루 1회 KST 09:40, 읽기·기록 전용).

가상매매 마감 행(최근 council_days 일) → strategy_council.build_report → Redis council:latest(3일) + council:day:YYYY-MM-DD(120일)
→ 텔레그램 요약 1통. 주문·설정·DB 쓰기 없음. 예외는 로그 후 상태 dict 로 돌려준다(스케줄러를 죽이지 않는다).
"""
from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.database import SessionLocal
from app.services import strategy_council as SC

logger = logging.getLogger(__name__)
FIX = SC.FIX
LATEST_KEY = "council:latest"
DAY_KEY = "council:day:{}"
LATEST_TTL = 3 * 86400
DAY_TTL = 120 * 86400
DEFAULT_DAYS = 30            # Claude가 정함 — 학습창(최대 60)보다 넉넉하게 · 10/10 측정 30일 13만 행 수 초
DAYS_BOUNDS = (14, 60)

SQL = text("""
    SELECT rule, side, (opened_at AT TIME ZONE 'UTC')::date AS d, engines->'live'->>'roi' AS roi,
           snapshot->>'market_breadth' AS mb, snapshot->'rules_fired' AS rf
    FROM paper_trades
    WHERE source = 'live' AND status = 'CLOSED' AND opened_at > :since
      AND engines->'live'->>'roi' IS NOT NULL
""")


def _setting(db, key: str):
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, key)
        return None if row is None else row.value
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] 설정 %s 조회 실패: %s", FIX, key, e)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None


def council_days(raw) -> int:
    x = SC._num(raw)
    return int(x) if x is not None and x == int(x) and DAYS_BOUNDS[0] <= x <= DAYS_BOUNDS[1] else DEFAULT_DAYS


def to_row(r) -> SC.Row | None:
    """DB 행 → Row. roi 가 수가 아니면 버림. mb 는 0~1 수만, rf 는 문자열 리스트만."""
    roi = SC._num(r.roi)
    if roi is None or r.side not in ("LONG", "SHORT") or not r.rule:
        return None
    mb = SC._num(r.mb)
    mb = mb if mb is not None and 0.0 <= mb <= 1.0 else None
    rf = tuple(x for x in r.rf if isinstance(x, str)) if isinstance(r.rf, list) else None
    return SC.Row(rule=str(r.rule), side=r.side, d=r.d, roi=roi, mb=mb, rf=rf)


def _fmt(x) -> str:
    return "—" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x:+.2f}"


def summary_text(rep: dict) -> tuple[str, str]:
    D = rep["D_walk"]
    t = D["total"]
    E = rep["E_today"]
    title = f"🧑‍⚖️ 전략 운영팀 성적표 {E['d'] or ''} — 오늘 쓸 칸 {len(E['cells'])}"
    lines = [
        f"전진 검증 {D['n_days']}일: 선택 {_fmt(t['sel'])} (n={t['sel_n']}) · 전체 {_fmt(t['all'])} · 무작위 {_fmt(t['base'])}",
        f"선택>전체 {D['sel_gt_all_days']}/{D['n_days']}일 · 최악의 날 {D['worst']['d'] if D['worst'] else '—'} {_fmt(D['worst']['sel'] if D['worst'] else None)}",
        f"오늘 시장폭 구간: {E['current_b']}",
        "",
        "▶ 오늘 쓸 칸 (지금 장세 먼저 · 규칙·방향·장세 · 무작위 대비 edge):",
    ]
    for c in E["cells"][:8]:
        lines.append(f"  {c['rule']} {c['side']} {c['b']} · {_fmt(c['edge'])} (n={c['n']})")
    stop = [f for f in rep["F_status"] if f["status"] == "중지 후보"]
    if stop:
        lines += ["", "⏸ 중지 후보 (무작위보다 못함):"]
        lines += [f"  {f['rule']} {f['side']} · {_fmt(f['edge'])} (n={f['n']})" for f in stop[:8]]
    new = [f for f in rep["F_status"] if f["status"] == "표본 부족"]
    if new:
        lines += ["", "🆕 표본 부족(관찰 중): " + ", ".join(f"{f['rule']}({f['n']})" for f in new[:8])]
    lines += ["", "※ 분석 전용 — 주문·설정은 바꾸지 않습니다. 켜기·끄기는 사장님(관제실)."]
    return title, "\n".join(lines)


def run_strategy_council_once(*, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    t0 = time.monotonic()
    db = SessionLocal()
    try:
        if str(_setting(db, "council_enabled") or "1").strip() == "0":
            return {"status": "off"}
        days = council_days(_setting(db, "council_days"))
        params = SC.params_from(lambda k: _setting(db, k))
        rows, bad = [], 0
        # roi·mb 는 문자열로 받아 파이썬에서 거른다 — 이상한 값 한 행이 조회 전체를 깨지 않게(교차 감사)
        res = db.execute(SQL, {"since": now - timedelta(days=days)}, execution_options={"stream_results": True})
        for r in res.yield_per(5000):
            x = to_row(r)
            if x is None:
                bad += 1
            else:
                rows.append(x)
        db.rollback()                         # 읽기 트랜잭션 정리 (쓰기 없음)
        rep = SC.build_report(rows, **params, today=now.date())   # 실행일(UTC) 기준 「오늘 쓸 칸」 — 데이터가 멈춰도 날짜가 밀리지 않게
        rep["at"] = now.isoformat()
        rep["window_days"] = days
        rep["skipped_rows"] = bad
        rep["secs"] = round(time.monotonic() - t0, 1)
        blob = json.dumps(rep, ensure_ascii=False, allow_nan=False)
        try:
            from app.core.redis_client import get_redis_client
            r = get_redis_client()
            r.setex(LATEST_KEY, LATEST_TTL, blob)
            r.setex(DAY_KEY.format(now.date().isoformat()), DAY_TTL, blob)
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s] Redis 저장 실패: %s", FIX, e)
        sent = False
        try:
            from app.services.notification_service import NotificationService
            title, body = summary_text(rep)
            sent = NotificationService(db).send_system_alert(title=title, body=body) is not None
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s] 텔레그램 실패: %s", FIX, e)
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
        out = {"status": "ok", "rows": len(rows), "skipped": bad, "cells": len(rep["E_today"]["cells"]),
               "sent": sent, "secs": rep["secs"]}
        logger.info("[%s] 성적표 %s", FIX, out)
        return out
    except Exception as e:  # noqa: BLE001
        logger.exception("[%s] 실패: %s", FIX, e)
        return {"status": "error", "error": str(e)[:200]}
    finally:
        db.close()
