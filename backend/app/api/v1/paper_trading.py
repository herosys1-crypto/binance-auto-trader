"""🧪 가상 매매 학습 API (Fix 361) — 읽기 전용. 실주문 0건인 학습 엔진의 상태 · 보고서(JSON/markdown) · 최근 건 조회.

사장님 (2026-09-08 verbatim): "지금부터 실시간 자동은 종료했어 가상으로 포지션 진입해서 성공과 실패를
기록저장 학습해서 다시 실시간 운영시작 하면 그때 적용할 수 있게 학습해줘 …"

엔진/워커: app/services/paper_trading.py / app/workers/paper_trading_worker.py.
PaperTrade / app.services.paper_trading 은 여기서 **핸들러 안에서만** import 한다 — 워커·엔진 모듈이
아직 배포 순서상 먼저 로드되지 않았거나(마이그레이션 전) 서로 다른 담당자가 병렬로 고치는 동안
API 모듈 임포트 시점에 깨지지 않게 하기 위함(house rule: 매매 판정과 화면/API 코드는 분리해 배치).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db

router = APIRouter(prefix="/paper-trading", tags=["paper-trading"])

_REPORT_CACHE_TTL = 600           # 10분 — 보고서는 15분 사이클마다 바뀌므로 짧게만 캐시
_REPORT_MAX_DAYS = 3650
_TRADES_MAX_LIMIT = 1000


def _jsonable(v: Any) -> Any:
    """JSONB/Numeric/datetime → JSON-safe 값 (Decimal→float, datetime→ISO)."""
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


def _row_to_dict(row: Any) -> dict[str, Any]:
    """PaperTrade ORM row → build_report()/화면이 기대하는 plain dict (JSON-safe)."""
    return {
        "id": row.id,
        "source": row.source,
        "symbol": row.symbol,
        "side": row.side,
        "rule": row.rule,
        "entry_bar_ts": row.entry_bar_ts,
        "entry_price": _jsonable(row.entry_price),
        "tp1_pct": _jsonable(row.tp1_pct),
        "opened_at": _jsonable(row.opened_at),
        "closed_at": _jsonable(row.closed_at),
        "status": row.status,
        "close_reason": row.close_reason,
        "tags": row.tags or [],
        "chg_24h": _jsonable(row.chg_24h),
        "chg_3d": _jsonable(row.chg_3d),
        "chg_5d": _jsonable(row.chg_5d),
        "snapshot": _jsonable(row.snapshot),
        "engines": _jsonable(row.engines),
        "adds": _jsonable(row.adds),
        "bars_seen": row.bars_seen,
        "mfe": _jsonable(row.mfe),
        "mae": _jsonable(row.mae),
        "version": row.version,
    }


def _build_report(db: Session, days: int) -> dict[str, Any]:
    """CLOSED 건을 모아 build_report() 실행 + Redis 10분 캐시 (사이클 15분보다 짧게)."""
    cache_key = f"paper_trading:report:{days}"
    try:
        from app.core.redis_client import get_redis_client

        r = get_redis_client()
        cached = r.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        r = None  # Redis 불통이어도 보고서 자체는 나가야 한다(읽기 전용 화면 — fail-open)

    from sqlalchemy import select

    from app.models.paper_trade import PaperTrade
    from app.services import paper_trading as PT

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(PaperTrade).where(PaperTrade.status == "CLOSED", PaperTrade.opened_at >= cutoff)
    ).scalars().all()
    trades = [_row_to_dict(row) for row in rows]
    report = PT.build_report(trades)

    if r is not None:
        try:
            r.setex(cache_key, _REPORT_CACHE_TTL, json.dumps(report, ensure_ascii=False))
        except Exception:
            pass  # 캐시 저장 실패는 무시 — 다음 요청이 다시 계산할 뿐
    return report


@router.get("/status")
def paper_trading_status(db: Session = Depends(get_db), user_id: int = Depends(get_current_user_id)) -> dict:
    """열림/닫힘 건수(출처별) + 마지막 사이클(Redis) + 백필 커서 + 채택 문턱."""
    from sqlalchemy import func, select

    from app.models.paper_trade import PaperTrade
    from app.models.system_setting import SystemSetting

    rows = db.execute(
        select(PaperTrade.status, PaperTrade.source, func.count()).group_by(PaperTrade.status, PaperTrade.source)
    ).all()
    counts: dict[str, dict[str, int]] = {}
    for status, source, cnt in rows:
        counts.setdefault(status, {})[source] = int(cnt)

    last_cycle: dict | None = None
    try:
        from app.core.redis_client import get_redis_client

        raw = get_redis_client().get("paper_trading:last_cycle")
        if raw:
            last_cycle = json.loads(raw)
    except Exception:
        last_cycle = None  # 조회 실패는 「모름」이지 「사이클 없음」이 아니다 — None 으로 구분

    last_id_row = db.get(SystemSetting, "paper_backfill_last_id")
    done_row = db.get(SystemSetting, "paper_backfill_done")

    adopt_min_n = None
    try:
        from app.services import paper_trading as PT

        adopt_min_n = PT.ADOPT_MIN_N
    except Exception:
        pass

    return {
        "counts": counts,
        "last_cycle": last_cycle,
        "backfill": {
            "last_id": int(last_id_row.value) if last_id_row and last_id_row.value else 0,
            "done": bool(done_row and done_row.value == "1"),
        },
        "adopt_min_n": adopt_min_n,
    }


@router.get("/report")
def paper_trading_report(days: int = 60, db: Session = Depends(get_db),
                         user_id: int = Depends(get_current_user_id)) -> dict:
    """규칙×방향×자리×엔진 + 추가 변형 + CV + 채택 제안 (JSON, 10분 캐시)."""
    return _build_report(db, max(1, min(days, _REPORT_MAX_DAYS)))


@router.get("/report.md", response_class=PlainTextResponse)
def paper_trading_report_md(days: int = 60, db: Session = Depends(get_db),
                            user_id: int = Depends(get_current_user_id)) -> str:
    from app.services import paper_trading as PT

    report = _build_report(db, max(1, min(days, _REPORT_MAX_DAYS)))
    return PT.render_markdown(report)


@router.get("/trades")
def paper_trading_trades(limit: int = 100, status: str | None = None, rule: str | None = None,
                         side: str | None = None, db: Session = Depends(get_db),
                         user_id: int = Depends(get_current_user_id)) -> dict:
    """최근 가상 매매 건 (필터: status/rule/side)."""
    from sqlalchemy import select

    from app.models.paper_trade import PaperTrade

    q = select(PaperTrade)
    if status:
        q = q.where(PaperTrade.status == status)
    if rule:
        q = q.where(PaperTrade.rule == rule)
    if side:
        q = q.where(PaperTrade.side == side)
    q = q.order_by(PaperTrade.opened_at.desc()).limit(max(1, min(limit, _TRADES_MAX_LIMIT)))
    rows = db.execute(q).scalars().all()
    return {"n": len(rows), "trades": [_row_to_dict(row) for row in rows]}
