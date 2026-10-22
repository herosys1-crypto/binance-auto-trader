"""🗄 Fix 480 (2026-10-22 사장님 「다음으로 진행」 — DB 줄이기) — 오래된 포지션 스냅샷 행 지우기 (전략별 최신 행은 남긴다).

positions = 거래소 포지션 **스냅샷 기록**(매번 INSERT, 지우는 곳 없음) · 10/22 실측 115만 행 · 224MB · 최근 하루 ≈ 1.9만 행.
읽는 곳 9곳은 전부 「전략별 최신 1행」만 읽는다 — 정렬이 두 가지:
  ① ORDER BY snapshot_time DESC, id DESC LIMIT 1   (position_repository.latest_by_strategy)
  ② ORDER BY id DESC LIMIT 1                       (monitoring·lifecycle·liquidation_risk·tp_miss 등)
- 남김: 전략마다 ② 최대 id 행 + ① 최대 snapshot_time 행(같은 시각 여러 개면 모두) · 보관 일수 안의 행 전부 · snapshot_time·전략 id 가 NULL 인 행
- 지움: 보관 일수(기본 30일)보다 오래된 나머지 행
- 남길 id 는 실행마다 한 번 모은다(Duel 교차 감사: 「더 새 행이 있나」 EXISTS 는 전략 색인만으로 행 많은 전략에서 O(k²) → 한 번 집계로 바꿈).
  모은 뒤 새로 들어온 행은 보관 일수 안이라 지울 대상이 아니다 → 경합 없음.
- 잠금: 작은 묶음 + 묶음마다 commit + 짧은 잠금 대기(Fix 409·428 과 같은 방식). 잠금이 막히면 다음 실행에.
- 표 파일 크기는 바로 줄지 않는다(VACUUM FULL 안 함) — 빈 자리를 새 행이 다시 써서 **더 커지지 않는다**.
"""
from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import bindparam, text

from app.core.database import SessionLocal

logger = logging.getLogger(__name__)
FIX = "Fix480"
SETTING_KEY = "position_snapshot_retention_days"
DEFAULT_DAYS = 30            # Claude가 정함 — 운영 화면·검사기는 최신 행만 읽는다
MIN_DAYS = 14                # Claude가 정함 — 사고 조사 여유 2주
MAX_DAYS = 3650
BATCH = 5000                 # Claude가 정함 — 한 묶음 행 수 (짧은 트랜잭션)
MAX_BATCHES = 60             # Claude가 정함 — 한 번 실행 상한(30만 행) · 남으면 다음 실행
LOCK_TIMEOUT_MS = 3000       # Fix 409 와 같은 값
LOCK_CODES = ("55P03", "40P01")   # lock_not_available · deadlock_detected

KEEP_SQL = text("""
    SELECT max(id) FROM positions WHERE strategy_instance_id IS NOT NULL GROUP BY strategy_instance_id
    UNION
    SELECT p.id FROM positions p
    JOIN (SELECT strategy_instance_id AS sid, max(snapshot_time) AS mt FROM positions
          WHERE strategy_instance_id IS NOT NULL GROUP BY strategy_instance_id) m
      ON p.strategy_instance_id = m.sid AND p.snapshot_time = m.mt
""")

DELETE_SQL = """
    DELETE FROM positions WHERE id IN (
        SELECT id FROM positions
        WHERE snapshot_time < :cutoff AND strategy_instance_id IS NOT NULL AND id NOT IN :keep
        ORDER BY id LIMIT :n
        {lock}
    )
"""


def retention_days(raw: object) -> int | None:
    """설정값 → 보관 일수. **정확히 0 = 끔(None)**. 정수가 아니거나(소수·inf·nan·문자·bool) 읽을 수 없으면 기본값. 범위 [14, 3650]."""
    if isinstance(raw, bool):
        return DEFAULT_DAYS
    try:
        x = float(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_DAYS
    if not math.isfinite(x) or x != int(x):
        return DEFAULT_DAYS
    d = int(x)
    if d == 0:
        return None
    return min(MAX_DAYS, max(MIN_DAYS, d))


def _one_line(e: BaseException, n: int) -> str:
    lines = str(e).splitlines()
    return (lines[0] if lines else type(e).__name__)[:n]


def _pgcode(e: BaseException) -> str | None:
    """SQLAlchemy 래퍼(.orig) → psycopg2 pgcode / psycopg3 sqlstate (교차 감사)."""
    orig = getattr(e, "orig", None) or e
    return getattr(orig, "pgcode", None) or getattr(orig, "sqlstate", None)


class SettingReadError(RuntimeError):
    pass


def _setting(db) -> object:
    """설정 행이 없을 때만 기본값. 조회 자체가 실패하면 예외 — 파괴 작업은 이번에 하지 않는다."""
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, SETTING_KEY)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise SettingReadError(str(e)) from e
    return row.value if row is not None and row.value not in (None, "") else DEFAULT_DAYS


def run_position_retention_once(*, now: datetime | None = None) -> dict:
    db = SessionLocal()
    stat = {"days": None, "deleted": 0, "batches": 0, "skipped_lock": 0}
    try:
        try:
            raw = _setting(db)
        except SettingReadError as e:
            logger.warning("[%s] 보관 일수 설정을 못 읽음 → 이번 실행 건너뜀: %s", FIX, _one_line(e, 160))
            stat["error"] = "setting"
            return stat
        days = retention_days(raw)
        stat["days"] = days
        if days is None:
            return stat
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
        try:
            is_pg = db.get_bind().dialect.name == "postgresql"
            keep = sorted({int(r[0]) for r in db.execute(KEEP_SQL).all() if r[0] is not None})
            db.rollback()                                     # 읽기 트랜잭션 끝 — 묶음은 각자 짧게
        except Exception as e:  # noqa: BLE001
            db.rollback()
            stat["error"] = type(e).__name__
            logger.warning("[%s] 남길 최신 행 집계 실패 — 확인 필요: %s", FIX, _one_line(e, 200))
            return stat
        if not keep:                                          # 남길 행을 모르면 지우지 않는다
            return stat
        sql = text(DELETE_SQL.format(lock="FOR UPDATE SKIP LOCKED" if is_pg else "")).bindparams(
            bindparam("keep", expanding=True))
        t0 = time.time()
        for _ in range(MAX_BATCHES):
            try:
                if is_pg:
                    db.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT_MS}ms'"))
                n = db.execute(sql, {"cutoff": cutoff, "keep": keep, "n": BATCH}).rowcount or 0
                db.commit()
            except Exception as e:  # noqa: BLE001
                db.rollback()
                if _pgcode(e) in LOCK_CODES:                  # 잠금 대기 초과·교착 = 정상적인 양보, 다음 실행에 이어서
                    stat["skipped_lock"] += 1
                    logger.info("[%s] 잠금 막힘 → 다음 실행에 이어서", FIX)
                else:
                    stat["error"] = type(e).__name__
                    logger.warning("[%s] 스냅샷 지우기 실패 — 확인 필요: %s", FIX, _one_line(e, 200))
                break
            stat["batches"] += 1
            stat["deleted"] += n
            if n < BATCH:
                break
        if stat["deleted"]:
            logger.info("[%s] 포지션 스냅샷 지움: %d행 (%d일 지난 · 전략별 최신 %d행 남김) · %.0fs",
                        FIX, stat["deleted"], days, len(keep), time.time() - t0)
        return stat
    finally:
        db.close()
