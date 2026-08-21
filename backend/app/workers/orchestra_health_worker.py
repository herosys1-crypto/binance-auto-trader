"""🎼 v206 Phase 4 사장님 오케스트라 자동 진단 + 자동 fix!

사장님 지적 (2026-08-21):
"우리 에이전트 팀이 많은데 왜 이런 문제가?
 오케스트라 지휘자가 각각의 에이전트팀을 컨트롤!"

= 매 5분 = 자동 진단 + 복구!
= 사장님 개입 최소!

로직:
1. 각 팀 상태 확인!
2. 문제 발견 시 = 자동 fix 시도!
3. 실패 시 = 텔레그램 알림!
4. EventBus에 = ORCHESTRA_HEALTH_CHECK 발신!
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.core.database import SessionLocal

logger = logging.getLogger(__name__)

# 자동 fix 이력 (30분 dedup!)
_LAST_FIX_ATTEMPTS: dict[str, datetime] = {}


def run_orchestra_health() -> dict:
    """🎼 매 5분 = 자동 진단 + 자동 fix!"""
    db: Session = SessionLocal()
    checks: list[dict] = []
    fixes_attempted: list[dict] = []
    alerts: list[str] = []
    try:
        # 1. 학습 stale 감지 + 자동 재실행!
        _check_and_fix_learning(db, checks, fixes_attempted, alerts)

        # 2. Watchlist 없음 감지 + 자동 재갱신!
        _check_and_fix_watchlist(db, checks, fixes_attempted, alerts)

        # 3. API BAN 감지 (fix 없음, 알림만!)
        _check_api_ban(db, checks, alerts)

        # 4. entry_snapshot 저장 실패 감지 (알림만!)
        _check_entry_snapshot_saving(db, checks, alerts)

        # 5. EventBus 발신!
        _publish_health_event(checks, fixes_attempted)

        # 6. 알림 발송!
        if alerts:
            _send_health_alerts(db, alerts)

        result = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
            "fixes_attempted": fixes_attempted,
            "alerts_sent": len(alerts),
        }
        logger.info(
            "[v206 P4] health check: %d checks, %d fixes, %d alerts",
            len(checks), len(fixes_attempted), len(alerts),
        )
        return result
    except Exception as e:
        logger.exception("[v206 P4] 실패: %s", e)
        return {"error": str(e)}
    finally:
        db.close()


def _check_and_fix_learning(db, checks, fixes, alerts):
    """학습 stale 감지 + 자동 재실행!"""
    try:
        from app.workers.pattern_learning_worker import get_learning_insights, run_pattern_learning
        insights = get_learning_insights(db)
        if not insights:
            checks.append({"team": "pattern_learning", "status": "MISSING"})
            if _can_attempt_fix("learning_missing"):
                logger.info("[v206 P4] 학습 인사이트 없음 → 강제 재실행!")
                r = run_pattern_learning()
                fixes.append({"team": "pattern_learning", "action": "run_pattern_learning", "result": r})
            alerts.append("학습 인사이트 없음! 자동 재실행!")
            return

        gen_at = datetime.fromisoformat(insights.get("generated_at", ""))
        age_h = (datetime.now(timezone.utc) - gen_at).total_seconds() / 3600
        checks.append({
            "team": "pattern_learning",
            "status": "OK" if age_h < 3 else "STALE",
            "age_h": round(age_h, 1),
            "samples": insights.get("total_samples", 0),
        })

        if age_h > 3 and _can_attempt_fix("learning_stale"):
            logger.info("[v206 P4] 학습 %.1fh stale → 강제 재실행!", age_h)
            r = run_pattern_learning()
            fixes.append({
                "team": "pattern_learning",
                "action": "run_pattern_learning",
                "reason": f"{age_h:.1f}h stale",
                "result": r,
            })
    except Exception as e:
        logger.warning("[v206 P4] learning check 실패: %s", e)


def _check_and_fix_watchlist(db, checks, fixes, alerts):
    """Watchlist 없음 감지 + 자동 재갱신!"""
    try:
        from app.workers.realtime_watchlist_worker import (
            get_watchlist_from_cache, run_realtime_watchlist, WATCHLIST_KEY,
        )
        from app.core.redis_client import get_redis_client
        watch = get_watchlist_from_cache()
        r = get_redis_client()
        ttl = r.ttl(WATCHLIST_KEY)

        checks.append({
            "team": "realtime_watchlist",
            "status": "OK" if watch and ttl > 0 else "MISSING",
            "count": len(watch) if watch else 0,
            "ttl_sec": ttl if ttl > 0 else 0,
        })

        if (not watch or ttl <= 0) and _can_attempt_fix("watchlist_missing"):
            logger.info("[v206 P4] watchlist 없음 → 강제 재갱신!")
            result = run_realtime_watchlist()
            fixes.append({
                "team": "realtime_watchlist",
                "action": "run_realtime_watchlist",
                "result": result,
            })
    except Exception as e:
        logger.warning("[v206 P4] watchlist check 실패: %s", e)


def _check_api_ban(db, checks, alerts):
    """API BAN 감지 (fix 없음, 알림만!)"""
    try:
        from app.core.api_backoff import check_api_ban
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        banned, expiry_ms = check_api_ban(r, 1)
        checks.append({
            "team": "api_backoff",
            "status": "BANNED" if banned else "OK",
            "expiry_ms": expiry_ms if banned else None,
        })
        if banned:
            expiry = datetime.fromtimestamp(expiry_ms/1000, tz=timezone.utc)
            mins_left = (expiry - datetime.now(timezone.utc)).total_seconds() / 60
            if mins_left > 30 and _can_attempt_fix("api_ban_long"):
                alerts.append(
                    f"⚠️ API BAN {mins_left:.0f}분 남음! (자연 회복 대기!)"
                )
    except Exception as e:
        logger.warning("[v206 P4] api_ban check 실패: %s", e)


def _check_entry_snapshot_saving(db, checks, alerts):
    """entry_snapshot 저장 실패 감지 (알림만!) — v208 사장님: 필드별 상세!"""
    try:
        from app.models.strategy_suggestion import StrategySuggestion
        from sqlalchemy import select
        cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
        rows = db.execute(
            select(StrategySuggestion)
            .where(StrategySuggestion.created_at >= cutoff)
            .where(StrategySuggestion.suggestion_type == "bb4h_auto_entry")
        ).scalars().all()
        total = len(rows)
        with_snapshot = 0
        # v208: 필드별 누락 카운트!
        field_missing = {"rsi": 0, "cci": 0, "obv_slope_pct": 0, "regime": 0}
        for r in rows:
            cfg = r.strategy_config or {}
            snap = cfg.get("entry_snapshot") if isinstance(cfg, dict) else None
            if snap and isinstance(snap, dict):
                with_snapshot += 1
                for f in field_missing:
                    if snap.get(f) is None:
                        field_missing[f] += 1

        checks.append({
            "team": "entry_snapshot",
            "status": "OK" if with_snapshot == total else "PARTIAL",
            "total_6h": total,
            "with_snapshot": with_snapshot,
            "field_missing_6h": field_missing,
        })

        if total > 0 and with_snapshot < total / 2 and _can_attempt_fix("snapshot_missing"):
            alerts.append(
                f"⚠️ entry_snapshot: {with_snapshot}/{total} 저장! "
                f"(학습 조건 분석 저하!)"
            )
        # v208: 필드 누락 알림!
        if with_snapshot > 0:
            severe = [f"{k}={v}" for k, v in field_missing.items() if v > with_snapshot * 0.3]
            if severe and _can_attempt_fix("snapshot_field_missing"):
                alerts.append(
                    f"⚠️ [v208] entry_snapshot 필드 누락 {with_snapshot}건 중 "
                    f"{', '.join(severe)} 결측! 학습 손실!"
                )
    except Exception as e:
        logger.warning("[v206 P4] snapshot check 실패: %s", e)


def _can_attempt_fix(key: str) -> bool:
    """30분 dedup = 같은 fix 반복 방지!"""
    now = datetime.now(timezone.utc)
    last = _LAST_FIX_ATTEMPTS.get(key)
    if last and (now - last).total_seconds() < 1800:
        return False
    _LAST_FIX_ATTEMPTS[key] = now
    return True


def _publish_health_event(checks, fixes):
    """EventBus에 = ORCHESTRA_HEALTH_CHECK 발신!"""
    try:
        from app.agents.orchestrator.event_bus import get_event_bus
        from app.agents.orchestrator.event_types import EventType
        get_event_bus().publish(EventType.ORCHESTRA_HEALTH_CHECK, {
            "checks": len(checks),
            "healthy": sum(1 for c in checks if c["status"] == "OK"),
            "fixes": len(fixes),
        })
    except Exception as e:
        logger.debug("[v206 P4] EventBus 실패: %s", e)


def _send_health_alerts(db, alerts):
    """텔레그램 알림 발송!"""
    try:
        from app.services.notification_service import NotificationService
        ns = NotificationService(db)
        ns.send_system_alert(
            title="🎼 [v206 P4] 오케스트라 자동 진단!",
            body="\n".join(alerts) + "\n\n= 이 알림 = 30분 dedup!",
        )
    except Exception as e:
        logger.warning("[v206 P4] 알림 실패: %s", e)
