"""🎯 v200 사장님 실시간 모니터링 UI API! (5패턴!)

사장님 요구:
- 5가지 차트 패턴 감지 (A~E!)
- 진입 중 / 진입 예정 / 성공/실패 = UI 표시!
- 모든 심볼 = 한눈에!
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/realtime-monitor", tags=["realtime-monitor"])


@router.get("/dashboard")
def get_dashboard(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🎯 v200: 사장님 실시간 모니터링 대시보드!

    4 섹션:
    1. 진입 대기 (watchlist + 5패턴 매칭!)
    2. 진입 중 (활성 포지션!)
    3. 진입 예정 (자동 진입 큐!)
    4. 최근 성공/실패 기록!
    """
    from app.core.strategy_status import TERMINAL_STATUSES
    from app.models.strategy_instance import StrategyInstance
    from app.models.strategy_suggestion import StrategySuggestion

    # 1. 진입 대기 (watchlist!)
    watchlist_symbols = []
    try:
        from app.workers.realtime_watchlist_worker import get_watchlist_from_cache
        watchlist = get_watchlist_from_cache() or []
        for w in watchlist[:30]:
            # 5패턴 매칭 (change_24h 기반 간단 분류!)
            pattern = _classify_pattern(w)
            watchlist_symbols.append({**w, "pattern": pattern})
    except Exception as e:
        logger.warning("[v200] watchlist 로드 실패: %s", e)

    # 2. 진입 중 (활성 포지션!)
    active = db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.status.notin_(list(TERMINAL_STATUSES)))
        .where(StrategyInstance.is_archived.is_(False))
        .order_by(desc(StrategyInstance.started_at))
    ).scalars().all()
    active_list = []
    for a in active:
        pnl = float(a.unrealized_pnl or 0)
        total_cap = float(a.total_capital or 1)
        roi_pct = (pnl / total_cap * 100) if total_cap > 0 else 0
        active_list.append({
            "id": a.id,
            "symbol": a.symbol,
            "side": a.side,
            "current_stage": a.current_stage,
            "unrealized_pnl": round(pnl, 2),
            "roi_pct": round(roi_pct, 2),
            "status": a.status,
            "started_at": a.started_at.isoformat() if a.started_at else None,
        })

    # 3. 진입 예정 (PENDING suggestions!)
    pending = db.execute(
        select(StrategySuggestion)
        .where(StrategySuggestion.status == "PENDING")
        .where(StrategySuggestion.confidence_score >= 0.75)
        .order_by(desc(StrategySuggestion.confidence_score))
        .limit(20)
    ).scalars().all()
    pending_list = []
    for p in pending:
        pending_list.append({
            "id": p.id,
            "symbol": p.symbol,
            "side": p.side,
            "confidence": float(p.confidence_score or 0),
            "reason": (p.reason or "")[:100],
            "type": p.suggestion_type,
        })

    # 4. 최근 성공/실패 기록 (24h!)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent = db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.stopped_at >= cutoff)
        .where(StrategyInstance.status.in_(list(TERMINAL_STATUSES)))
        .order_by(desc(StrategyInstance.stopped_at))
        .limit(30)
    ).scalars().all()
    results_list = []
    for r in recent:
        pnl = float(r.realized_pnl or 0)
        results_list.append({
            "id": r.id,
            "symbol": r.symbol,
            "side": r.side,
            "realized_pnl": round(pnl, 2),
            "outcome": "SUCCESS" if pnl > 0 else "FAIL" if pnl < 0 else "NEUTRAL",
            "stopped_at": r.stopped_at.isoformat() if r.stopped_at else None,
            "status": r.status,
        })

    # 요약!
    wins = sum(1 for r in results_list if r["outcome"] == "SUCCESS")
    losses = sum(1 for r in results_list if r["outcome"] == "FAIL")
    total_pnl = sum(r["realized_pnl"] for r in results_list)

    return {
        "watchlist": watchlist_symbols,
        "active": active_list,
        "pending": pending_list,
        "recent_results": results_list,
        "summary": {
            "watchlist_count": len(watchlist_symbols),
            "active_count": len(active_list),
            "pending_count": len(pending_list),
            "results_24h": {
                "total": len(results_list),
                "wins": wins,
                "losses": losses,
                "total_pnl": round(total_pnl, 2),
                "win_rate": round(wins * 100 / (wins + losses), 1) if (wins + losses) > 0 else 0,
            },
        },
        "note": "🎯 v200 사장님 실시간 모니터링! (매 15분 watchlist + 5패턴 매칭!)",
    }


def _classify_pattern(w: dict) -> str:
    """5패턴 간단 분류!

    A. 급등 시작 = change_24h 10~20%
    B. 급등 후 하락 시작 = change_24h 30%+ + reason = TOP_LOSS
    C. 급등 후 급락 = change_24h 여전 +이지만 최근 하락 = TOP_LOSS
    D. 급등 후 조정 = change_24h 20%+ + TOP_GAIN
    E. 실패 반등 후 재하락 = REENTRY_CANDIDATE
    """
    change = w.get("change_24h", 0)
    reason = w.get("reason", "")

    if reason == "REENTRY_CANDIDATE":
        return "E_FAKE_BOUNCE"
    if reason == "TOP_LOSS":
        if change < -20:
            return "C_SURGE_CRASH"
        return "B_DROP_START"
    if reason == "TOP_GAIN":
        if change >= 30:
            return "D_PULLBACK_RESUME"
        if change >= 10:
            return "A_INITIAL_SURGE"
    return "UNKNOWN"
