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

logger = logging.getLogger(__name__)

BATCH_PAPER = 150          # Claude가 정함 — 사이클당 (5분봉 조회 1회/건)
BATCH_REAL = 40
LOOKBACK_PAPER_DAYS = 3
LOOKBACK_REAL_DAYS = 7
SLEEP_SEC = 0.15
MAX_CONSEC_FAIL = 3


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
    stat = {"paper": 0, "real": 0, "no_bars": 0, "fail": 0}
    try:
        if not CS.setting_on(db, CS.S_ENABLED, True):
            return {"skipped": "disabled"}
        th = CS.thresholds(db)
        now = datetime.now(timezone.utc)
        now_ms = int(now.timestamp() * 1000)
        horizon = timedelta(minutes=5 * int(th["timing_after_bars"]))
        jobs = [(PaperTrade, "snapshot", "paper", r) for r in db.execute(paper_stmt(now=now, horizon=horizon, limit=BATCH_PAPER)).all()]
        jobs += [(TradeLearningRecord, "insights", "real", r) for r in db.execute(real_stmt(now=now, horizon=horizon, limit=BATCH_REAL)).all()]
        consec = 0
        for i, (model, column, kind, (rid, symbol, side, entry_price, entry_at)) in enumerate(jobs):
            try:
                res = _label_one(bc, CS, th, symbol, side, entry_price, entry_at, now_ms)
                consec = 0
            except Exception as e:  # noqa: BLE001
                consec += 1
                stat["fail"] += 1
                logger.warning("[Fix372] %s #%s %s 5분봉 조회 실패 (%d/%d): %s", kind, rid, symbol, consec, MAX_CONSEC_FAIL, e)
                if consec >= MAX_CONSEC_FAIL:
                    logger.error("[Fix372] 연속 실패 → 사이클 중단 (ban 보호)")
                    break
                continue
            if res.get("label") is None:
                stat["no_bars"] += 1
            else:
                stat[kind] += 1
            db.execute(_set_json_stmt(model, column, "chart_timing", rid, res))
            if i % 25 == 24:
                db.commit()
            time.sleep(SLEEP_SEC)
        db.commit()
        logger.info("[Fix372] 진입 타이밍 채점: 가상 %d · 실거래 %d · 봉부족 %d · 실패 %d (대상 %d)",
                    stat["paper"], stat["real"], stat["no_bars"], stat["fail"], len(jobs))
        return stat
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.error("[Fix372] 타이밍 채점 워커 오류: %s", e, exc_info=True)
        return {**stat, "error": str(e)}
    finally:
        db.close()
