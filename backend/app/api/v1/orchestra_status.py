"""🎼 v206 Phase 3 사장님 오케스트라 상태 API!

사장님 지적 (2026-08-21):
"우리 에이전트 팀이 많은데 왜 이런 문제가?
 오케스트라 지휘자가 각각의 에이전트팀을 컨트롤!"

= 팀 상태 = UI 대시보드!
= 사장님 = 모든 팀 = 한눈에!
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orchestra", tags=["orchestra"])


@router.get("/status")
def get_orchestra_status(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🎼 v206 Phase 3: 오케스트라 팀 + 워커 상태 종합!"""
    from app.models.risk_event import RiskEvent

    teams = {}

    # 1. 학습 팀 (v187!)
    try:
        from app.workers.pattern_learning_worker import get_learning_insights
        insights = get_learning_insights(db)
        if insights:
            gen_at = datetime.fromisoformat(insights.get("generated_at", ""))
            age_min = (datetime.now(timezone.utc) - gen_at).total_seconds() / 60
            snap = insights.get("snapshot_conditions", {})
            teams["pattern_learning"] = {
                "status": "✅ 정상" if age_min < 65 else "⚠️ 지연",
                "samples": insights.get("total_samples", 0),
                "last_run_min_ago": round(age_min, 1),
                "conditions_learned": sum(len(v) for v in snap.values()),
                "top_types": len(insights.get("type_side_rankings", [])),
            }
        else:
            teams["pattern_learning"] = {"status": "❌ 미실행!", "samples": 0}
    except Exception as e:
        teams["pattern_learning"] = {"status": f"❌ 오류: {e}"}

    # 2. Watchlist (v199!)
    try:
        from app.workers.realtime_watchlist_worker import get_watchlist_from_cache, WATCHLIST_KEY
        from app.core.redis_client import get_redis_client
        watch = get_watchlist_from_cache()
        r = get_redis_client()
        ttl = r.ttl(WATCHLIST_KEY)
        teams["realtime_watchlist"] = {
            "status": "✅ 정상" if watch else "⚠️ 갱신 필요",
            "count": len(watch) if watch else 0,
            "ttl_sec": ttl if ttl > 0 else 0,
        }
    except Exception as e:
        teams["realtime_watchlist"] = {"status": f"❌ 오류: {e}"}

    # 3. 자동 진입 (v174~v204!)
    try:
        from app.workers.auto_bb_breakdown_worker import _count_used_slots
        from app.models.system_setting import SystemSetting
        limit_row = db.get(SystemSetting, "auto_bb_break_daily_limit")
        limit = int(limit_row.value) if limit_row and limit_row.value else 0
        used = _count_used_slots(db)
        teams["auto_entry"] = {
            "status": ("✅ 활성" if limit > 0 else "🚫 OFF") if used < limit else "⏸ 만료",
            "limit": limit,
            "used": used,
            "remaining": max(0, limit - used),
        }
    except Exception as e:
        teams["auto_entry"] = {"status": f"❌ 오류: {e}"}

    # 4. API Ban 상태!
    try:
        from app.core.api_backoff import check_api_ban
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        banned, expiry_ms = check_api_ban(r, 1)
        teams["api_backoff"] = {
            "status": "🚨 BAN 중!" if banned else "✅ 정상",
            "banned_until": (
                datetime.fromtimestamp(expiry_ms/1000, tz=timezone.utc).strftime("%H:%M UTC")
                if banned and expiry_ms else None
            ),
        }
    except Exception as e:
        teams["api_backoff"] = {"status": f"❌ 오류: {e}"}

    # 5. Silent Bug Detector (v206 Phase 2!)
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        silent_bugs = db.execute(
            select(RiskEvent)
            .where(RiskEvent.event_type.like("SILENT_BUG_%"))
            .where(RiskEvent.created_at >= cutoff)
        ).scalars().all()
        v206_bugs = [b for b in silent_bugs if "V206" in (b.event_type or "")]
        teams["silent_bug_detector"] = {
            "status": "⚠️ 이슈 있음" if silent_bugs else "✅ 정상",
            "recent_1h": len(silent_bugs),
            "v206_bugs": len(v206_bugs),
        }
    except Exception as e:
        teams["silent_bug_detector"] = {"status": f"❌ 오류: {e}"}

    # 6. 최근 이벤트 (30분!)
    recent_events = []
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
        events = db.execute(
            select(RiskEvent)
            .where(RiskEvent.created_at >= cutoff)
            .where(RiskEvent.severity.in_(["CRITICAL", "WARN"]))
            .order_by(desc(RiskEvent.created_at))
            .limit(10)
        ).scalars().all()
        for e in events:
            recent_events.append({
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "type": e.event_type,
                "severity": e.severity,
                "title": (e.title or "")[:80],
                "message": (e.message or "")[:100],
            })
    except Exception:
        pass

    # 7. 시스템 요약!
    total_teams = len(teams)
    healthy = sum(1 for t in teams.values() if "✅" in t.get("status", ""))
    warnings = sum(1 for t in teams.values() if "⚠️" in t.get("status", ""))
    errors = sum(1 for t in teams.values() if "❌" in t.get("status", ""))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_teams": total_teams,
            "healthy": healthy,
            "warnings": warnings,
            "errors": errors,
            "recent_events_30m": len(recent_events),
        },
        "teams": teams,
        "recent_events": recent_events,
        "note": "🎼 v206 Phase 3 사장님 오케스트라 상태!",
    }
