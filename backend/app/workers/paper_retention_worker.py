"""🗄 Fix 428 (2026-10-10 사장님 「5번 진행」) — 오래된 가상매매 마감 행의 상세 기록 비우기 (결과는 남긴다).

DB(Neon) 1.3 GB 중 paper_trades 912 MB(70%), 하루 +27 MB. 큰 칸 = snapshot 420 MB(진입 지표) · engines 148 MB(엔진 결과) · adds 103 MB(추가매수 로트).
- 대상: status = CLOSED 이고 **진입(opened_at)한 지 보관 일수(기본 60일)가 지난** 행
- 비우는 칸: snapshot · adds  (진입 당시 지표·추가매수 로트 — 필터 재분석·피라미딩 분석에만 쓰임)
- 남기는 칸: rule · side · symbol · 진입가 · 청산 사유 · mfe/mae · tags · engines(엔진별 결과 = 판정 보고서) · 시각 전부
- 채택 판단 보고서(v3)는 진입 시각 기준 최대 60일만 읽는다 → 보관 일수 하한 60 + 하루 여유(교차 감사).
  옛 보고서(legacy, 참고용, 최대 3650일)는 adds 가 비면 빈 것으로 읽는다(예외 없음) — 60일 넘는 창의 추가매수 통계는 그만큼 빠진다.
- 잠금: 가상매매 워커와 겹치지 않게 작은 묶음 + 묶음마다 commit + 짧은 잠금 대기(Fix 409 교착 교훈). 잠금이 막히면 다음 실행에.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.database import SessionLocal

logger = logging.getLogger(__name__)
FIX = "Fix428"
SETTING_KEY = "paper_detail_retention_days"
DEFAULT_DAYS = 60            # 사장님 10/10 「5번 진행」 (제안 「예: 60일」)
MIN_DAYS = 60                # 보고서 최대 창(_REPORT_V3_MAX_DAYS = 60) 아래로 못 내린다
BATCH = 2000                 # Claude가 정함 — 한 묶음 행 수 (짧은 트랜잭션)
MAX_BATCHES = 50             # Claude가 정함 — 한 번 실행 상한(10만 행) · 남으면 다음 실행
MAX_DAYS = 3650
MARGIN_DAYS = 1              # 교차 감사: 보고서 창(now − 60일)과 비움 경계 사이 하루 여유
LOCK_TIMEOUT_MS = 3000       # Fix 409 와 같은 값
LOCK_CODES = ("55P03", "40P01")   # lock_not_available · deadlock_detected


def retention_days(raw: object) -> int | None:
    """설정값 → 보관 일수. **정확히 0 = 끔(None)**. 정수가 아니거나(소수·inf·nan·문자) 읽을 수 없으면 기본값. 범위 [60, 3650]."""
    import math
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
    """예외 첫 줄(빈 메시지도 안전 — Gemini: "".splitlines()[0] 이 IndexError 로 원래 오류를 가린다)."""
    lines = str(e).splitlines()
    return (lines[0] if lines else type(e).__name__)[:n]


class SettingReadError(RuntimeError):
    pass


def _setting(db) -> object:
    """설정 행이 없을 때만 기본값. 조회 자체가 실패하면 예외 — 파괴 작업은 이번에 하지 않는다(교차 감사: 「끔」·「90일」 설정을 기본값으로 덮지 않게)."""
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, SETTING_KEY)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise SettingReadError(str(e)) from e
    return row.value if row is not None and row.value not in (None, "") else DEFAULT_DAYS


UPDATE_SQL = text("""
    UPDATE paper_trades SET snapshot = NULL, adds = NULL
    WHERE id IN (
        SELECT id FROM paper_trades
        WHERE status = 'CLOSED' AND opened_at < :cutoff AND (snapshot IS NOT NULL OR adds IS NOT NULL)
        ORDER BY id LIMIT :n
        FOR UPDATE SKIP LOCKED
    )
""")


def run_paper_retention_once(*, now: datetime | None = None) -> dict:
    db = SessionLocal()
    stat = {"days": None, "cleared": 0, "batches": 0, "skipped_lock": 0}
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
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days + MARGIN_DAYS)
        is_pg = db.get_bind().dialect.name == "postgresql"        # 교차 감사: Session.bind 가 None 이어도 실제 엔진으로 판정
        t0 = time.time()
        for _ in range(MAX_BATCHES):
            try:
                if is_pg:
                    db.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT_MS}ms'"))
                    n = db.execute(UPDATE_SQL, {"cutoff": cutoff, "n": BATCH}).rowcount or 0
                else:                                         # 테스트(sqlite): FOR UPDATE SKIP LOCKED 없음
                    n = db.execute(text(str(UPDATE_SQL).replace("FOR UPDATE SKIP LOCKED", "")),
                                   {"cutoff": cutoff, "n": BATCH}).rowcount or 0
                db.commit()
            except Exception as e:  # noqa: BLE001
                db.rollback()
                code = getattr(getattr(e, "orig", None), "pgcode", None)
                if code in LOCK_CODES:                        # 잠금 대기 초과·교착 = 정상적인 양보, 다음 실행에 이어서
                    stat["skipped_lock"] += 1
                    logger.info("[%s] 잠금 막힘(%s) → 다음 실행에 이어서", FIX, code)
                else:                                         # Gemini: 그 밖의 오류(제약 위반 등)는 숨기지 않는다
                    stat["error"] = type(e).__name__
                    logger.warning("[%s] 상세 비우기 실패 — 확인 필요: %s", FIX, _one_line(e, 200))
                break
            stat["batches"] += 1
            stat["cleared"] += n
            if n < BATCH:
                break
        if stat["cleared"]:
            logger.info("[%s] 가상매매 상세 비움: %d행 (진입 %d일 지난 마감 행 · snapshot·adds) · %.0fs",
                        FIX, stat["cleared"], days, time.time() - t0)
        return stat
    finally:
        db.close()
