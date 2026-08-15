"""📊 Chart Pattern API (v152 신!) - 4H 패턴 학습 조회!

배경 (사장님 요청 2026-08-16):
"심볼들의 1달 차트를 분석해서 이런 패턴을 학습해서 메모리해줘"
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.models.chart_pattern import ChartPattern

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chart-patterns", tags=["chart-patterns"])


@router.get("/summary")
def pattern_summary(
    days: int = 30,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """📊 패턴 학습 통계 (최근 N일!)"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(ChartPattern).where(ChartPattern.detected_at >= cutoff)
    ).scalars().all()

    total = len(rows)
    success = sum(1 for r in rows if r.outcome_status == "SUCCESS")
    fail = sum(1 for r in rows if r.outcome_status == "FAIL")
    pending = sum(1 for r in rows if r.outcome_status == "PENDING")
    expired = sum(1 for r in rows if r.outcome_status == "EXPIRED")
    judged = success + fail

    # 패턴별 성공률!
    by_pattern: dict[str, dict[str, int]] = {}
    for r in rows:
        if r.outcome_status not in ("SUCCESS", "FAIL"):
            continue
        s = by_pattern.setdefault(r.pattern_type, {"total": 0, "wins": 0})
        s["total"] += 1
        if r.outcome_status == "SUCCESS":
            s["wins"] += 1

    pattern_stats = [
        {
            "pattern_type": pt,
            "total": s["total"],
            "wins": s["wins"],
            "rate": round((s["wins"] / s["total"] * 100), 1),
        }
        for pt, s in sorted(
            by_pattern.items(),
            key=lambda x: -(x[1]["wins"] / x[1]["total"] if x[1]["total"] else 0),
        )
    ]

    # 심볼별 성공률!
    by_symbol: dict[str, dict[str, int]] = {}
    for r in rows:
        if r.outcome_status not in ("SUCCESS", "FAIL"):
            continue
        s = by_symbol.setdefault(r.symbol, {"total": 0, "wins": 0})
        s["total"] += 1
        if r.outcome_status == "SUCCESS":
            s["wins"] += 1
    top_symbols = sorted(
        [{"symbol": sym, "total": s["total"], "wins": s["wins"],
          "rate": round(s["wins"] / s["total"] * 100, 1)}
         for sym, s in by_symbol.items() if s["total"] >= 2],
        key=lambda x: -x["rate"],
    )[:10]

    return {
        "days": days,
        "total": total,
        "success": success,
        "fail": fail,
        "pending": pending,
        "expired": expired,
        "success_rate": round((success / judged * 100), 1) if judged else 0,
        "pattern_stats": pattern_stats,
        "top_symbols": top_symbols,
    }


@router.get("/recent")
def recent_patterns(
    limit: int = 20,
    pattern_type: str | None = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[dict]:
    """최근 감지 패턴!"""
    q = select(ChartPattern).order_by(ChartPattern.detected_at.desc())
    if pattern_type:
        q = q.where(ChartPattern.pattern_type == pattern_type)
    rows = db.execute(q.limit(limit)).scalars().all()
    return [
        {
            "id": r.id,
            "symbol": r.symbol,
            "pattern_type": r.pattern_type,
            "side": r.side,
            "detected_at": r.detected_at.isoformat() if r.detected_at else None,
            "entry_price": str(r.entry_price or 0),
            "confidence": float(r.confidence or 0),
            "outcome_status": r.outcome_status,
            "outcome_max_favorable_pct": float(r.outcome_max_favorable_pct or 0)
                                          if r.outcome_max_favorable_pct is not None else None,
        }
        for r in rows
    ]


@router.post("/scan-now")
def scan_now(
    top_n: int = 100,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🎯 지금 즉시 = 전체 스캔!"""
    from app.core.crypto import decrypt_text
    from app.agents.chart_pattern_learning_team.team_lead import ChartPatternLearningTeamLead
    return ChartPatternLearningTeamLead().run_full_scan(db, decrypt_text, top_n=top_n)
