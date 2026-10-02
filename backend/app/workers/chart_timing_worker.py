"""📐 Fix 372 진입 타이밍 채점 워커 — 30분마다. 주문 없음 (읽기 전용 5분봉 조회 + 학습 기록 쓰기).

사장님 (2026-09-15): "지금 우리가 놓치고있는 빠른 진입과 늦은 진입그리고 잘못된 포지션을 많이 개선할수 있을것 같아"

진입 뒤 `timing_after_bars`(기본 48 = 4시간)가 지난 진입을 골라, 진입 전 1시간 + 진입 뒤 4시간 5분봉으로
chart_state.timing_label 을 계산해 저장한다.
  가상매매  paper_trades(source=live, 최근 LOOKBACK_PAPER_DAYS 일) → snapshot.chart_timing
  실거래    trade_learning_records(최근 LOOKBACK_REAL_DAYS 일)       → insights.chart_timing
저장은 jsonb_set 으로 그 키만 바꾼다(큰 JSONB 를 읽지 않는다). 봉이 모자라면 error 와 함께 저장해 다시 훑지 않는다.
연속 조회 실패 MAX_CONSEC_FAIL 이면 사이클을 멈춘다(IP ban 보호).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

logger = logging.getLogger(__name__)

BATCH_PAPER = 150
BATCH_REAL = 40
LOOKBACK_PAPER_DAYS = 3
LOOKBACK_REAL_DAYS = 7
SLEEP_SEC = 0.15
MAX_CONSEC_FAIL = 3
# 🔒 Fix 409 (2026-10-03, Duel chart-timing-deadlock): 가상매매 워커와 paper_trades 교착(24h 2번 — 가상매매 사이클 전체 실패).
#   행마다 UPDATE 직후 commit(잠금 최대 1개) + 짧은 잠금 대기 → 잠금 충돌이면 그 행만 건너뛴다(chart_timing 이 비어 다음 사이클 재시도).
# UPDATE 한 번이 남의 행 잠금을 기다리는 최대 시간(ms). Claude가 정함.
# PostgreSQL 에서 0 은 '무한 대기'이므로 금지 — 양의 정수만 허용.
LOCK_TIMEOUT_MS = 3000

_PG_LOCK_CODES = {"55P03": "잠금 대기 초과", "40P01": "교착"}
# pgcode 를 못 읽을 때만 쓰는 드라이버 원본 메시지 표식
_LOCK_TEXT_MARKERS = (("lock timeout", "55P03"), ("deadlock detected", "40P01"))


def _safe_str(obj) -> str:
    try:
        return str(obj)
    except Exception:
        return type(obj).__name__


def _driver_error(exc):
    """SQLAlchemy DBAPIError 면 드라이버 원본 예외(.orig), 아니면 그 자신."""
    orig = getattr(exc, "orig", None)
    return orig if orig is not None else exc


def _pgcode_of(exc) -> str | None:
    """psycopg2(.pgcode) / psycopg3(.sqlstate). 못 읽으면 None."""
    src = _driver_error(exc)
    for attr in ("pgcode", "sqlstate"):
        try:
            code = getattr(src, attr, None)
        except Exception:
            code = None
        if isinstance(code, str) and code.strip():
            return code.strip().upper()
    return None


def _lock_conflict_code(exc) -> str | None:
    """잠금 대기 초과/교착이면 '55P03'/'40P01', 아니면 None.
    pgcode 가 읽히면 그것만으로 판정(문자열보다 우선). 못 읽을 때만 원본 메시지로 판정.
    str(exc) 는 SQL·파라미터가 섞여 오탐 위험이 있어 쓰지 않는다."""
    code = _pgcode_of(exc)
    if code is not None:
        return code if code in _PG_LOCK_CODES else None
    msg = _safe_str(_driver_error(exc)).lower()
    for marker, c in _LOCK_TEXT_MARKERS:
        if marker in msg:
            return c
    return None


def _one_line(exc, limit: int = 300) -> str:
    """로그 한 줄용: 개행(DETAIL 등)을 공백으로 접고 길이 제한."""
    return " ".join(_safe_str(_driver_error(exc)).split())[:limit]


def _is_postgresql(db) -> bool:
    """확인 실패 = PostgreSQL 아님으로 간주 (SET LOCAL 을 보내지 않는다)."""
    try:
        name = db.get_bind().dialect.name
    except Exception as e:
        logger.warning("[Fix372] DB 방언 확인 실패 → lock_timeout 생략: %s", _one_line(e))
        return False
    return isinstance(name, str) and name.lower() == "postgresql"


def _lock_timeout_stmt():
    ms = LOCK_TIMEOUT_MS
    if isinstance(ms, bool) or not isinstance(ms, int) or ms <= 0:
        raise ValueError(f"LOCK_TIMEOUT_MS 는 양의 정수(ms)여야 한다 (0 = 무한 대기): {ms!r}")
    # SET 은 바인드 파라미터를 못 받는다 → 검증된 int 만 문자열에 넣는다.
    return text(f"SET LOCAL lock_timeout = '{ms}ms'")


def _safe_rollback(db, where: str) -> None:
    try:
        db.rollback()
    except Exception as e:
        logger.error("[Fix372] rollback 실패(%s): %s", where, _one_line(e), exc_info=True)


def _safe_close(db) -> None:
    try:
        db.close()
    except Exception as e:
        logger.error("[Fix372] 세션 close 실패: %s", _one_line(e), exc_info=True)



def _set_json_stmt(model, column, key: str, record_id: int, payload: dict[str, Any]):
    from sqlalchemy import cast, func, literal, literal_column, update
    from sqlalchemy.dialects.postgresql import JSONB
    col = getattr(model, column)
    return (
        update(model).where(model.id == record_id)
        .values({column: func.jsonb_set(func.coalesce(col, cast(literal("{}"), JSONB)),
                                        literal_column(f"'{{{key}}}'"),
                                        cast(literal(json.dumps(payload, ensure_ascii=False, default=str)), JSONB))})
    )


def paper_stmt(*, now: datetime, horizon: timedelta, limit: int):
    from sqlalchemy import select
    from app.models.paper_trade import PaperTrade as P
    return (
        select(P.id, P.symbol, P.side, P.entry_price, P.opened_at)
        .where(P.source == "live", P.opened_at <= now - horizon - timedelta(minutes=10),
               P.opened_at >= now - timedelta(days=LOOKBACK_PAPER_DAYS), P.snapshot["chart_timing"].is_(None))
        .order_by(P.opened_at.desc()).limit(limit)
    )


def real_stmt(*, now: datetime, horizon: timedelta, limit: int):
    from sqlalchemy import or_, select
    from app.models.trade_learning_record import TradeLearningRecord as T
    return (
        select(T.id, T.symbol, T.side, T.entry_price, T.entry_time)
        .where(T.entry_time.isnot(None), T.entry_price.isnot(None),
               T.entry_time <= now - horizon - timedelta(minutes=10),
               T.entry_time >= now - timedelta(days=LOOKBACK_REAL_DAYS),
               or_(T.insights.is_(None), T.insights["chart_timing"].is_(None)))
        .order_by(T.entry_time.desc()).limit(limit)
    )


def _label_one(bc: Any, CS, th: dict, symbol: str, side: str, entry_price: float, entry_at: datetime, now_ms: int) -> dict:
    entry_ms = int(entry_at.timestamp() * 1000)
    pre, after = int(th["timing_pre_bars"]), int(th["timing_after_bars"])
    raw = bc.get_klines(symbol=symbol, interval="5m", limit=pre + after, start_time=entry_ms - pre * CS.MS["5m"])
    res = CS.timing_label(side, float(entry_price), entry_ms, CS.normalize(raw, "5m", now_ms), th)
    res["labeled_at"] = datetime.now(timezone.utc).isoformat()
    return res


def run_chart_timing_once(decrypt_text) -> dict:
    from app.models.paper_trade import PaperTrade
    from app.models.trade_learning_record import TradeLearningRecord
    from app.services import chart_state as CS
    from app.workers.chart_learning_worker import _open

    db, bc = _open(decrypt_text)
    if db is None:
        return {"error": "no account"}
    stat = {"paper": 0, "real": 0, "no_bars": 0, "fail": 0, "lock_skip": 0}
    try:
        if not CS.setting_on(db, CS.S_ENABLED, True):
            return {"skipped": "disabled"}
        th = CS.thresholds(db)
        now = datetime.now(timezone.utc)
        now_ms = int(now.timestamp() * 1000)
        horizon = timedelta(minutes=5 * int(th["timing_after_bars"]))
        jobs = [(PaperTrade, "snapshot", "paper", r)
                for r in db.execute(paper_stmt(now=now, horizon=horizon, limit=BATCH_PAPER)).all()]
        jobs += [(TradeLearningRecord, "insights", "real", r)
                 for r in db.execute(real_stmt(now=now, horizon=horizon, limit=BATCH_REAL)).all()]
        # 조회용 트랜잭션을 여기서 끝낸다 → 첫 거래소 조회 중에도 열린 트랜잭션 0개.
        db.commit()

        # 방언은 사이클 동안 바뀌지 않으므로 한 번만 판단. 잘못된 상수는 루프 전에 크게 실패.
        lock_stmt = _lock_timeout_stmt() if _is_postgresql(db) else None

        consec = 0
        for model, column, kind, (rid, symbol, side, entry_price, entry_at) in jobs:
            # ── 거래소 조회: 트랜잭션 밖 (행 잠금 0개) ──
            try:
                res = _label_one(bc, CS, th, symbol, side, entry_price, entry_at, now_ms)
                consec = 0
            except Exception as e:
                consec += 1
                stat["fail"] += 1
                logger.warning("[Fix372] %s #%s %s 5분봉 조회 실패 (%d/%d): %s",
                               kind, rid, symbol, consec, MAX_CONSEC_FAIL, e)
                if consec >= MAX_CONSEC_FAIL:
                    logger.error("[Fix372] 연속 실패 → 사이클 중단 (ban 보호)")
                    break
                continue

            bucket = "no_bars" if res.get("label") is None else kind

            # ── 한 행 = 한 트랜잭션: SET LOCAL → UPDATE → commit ──
            try:
                if lock_stmt is not None:
                    db.execute(lock_stmt)
                db.execute(_set_json_stmt(model, column, "chart_timing", rid, res))
                db.commit()
            except DBAPIError as e:
                code = _lock_conflict_code(e)
                if code is None:
                    # 잠금 문제가 아닌 DB 오류: 정리 후 바깥으로 → 사이클 오류 (삼키지 않음)
                    _safe_rollback(db, f"{kind} #{rid} 갱신 실패")
                    raise
                # rollback 자체가 실패하면(커넥션 사망 등) 계속할 수 없다 → 바깥 except 로 전파
                db.rollback()
                stat["lock_skip"] += 1
                logger.warning(
                    "[Fix372] %s #%s %s %s(%s) → 이 행 건너뜀, 다음 사이클 재시도: %s",
                    kind, rid, symbol, _PG_LOCK_CODES[code],
                    _pgcode_of(e) or "pgcode 없음·메시지 판정", _one_line(e))
                time.sleep(SLEEP_SEC)  # 거래소 조회는 이미 했으므로 속도 보호는 그대로
                continue

            stat[bucket] += 1
            time.sleep(SLEEP_SEC)

        db.commit()  # 기존 의미 유지 (보통은 비어 있는 트랜잭션)
        logger.info("[Fix372] 진입 타이밍 채점: 가상 %d · 실거래 %d · 봉부족 %d · 실패 %d · 잠금 건너뜀 %d (대상 %d)",
                    stat["paper"], stat["real"], stat["no_bars"], stat["fail"], stat["lock_skip"], len(jobs))
        return stat
    except Exception as e:
        _safe_rollback(db, "사이클 오류")
        logger.error("[Fix372] 타이밍 채점 워커 오류: %s", e, exc_info=True)
        return {**stat, "error": str(e)}
    finally:
        _safe_close(db)
