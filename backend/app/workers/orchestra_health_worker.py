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
_LAST_STALE_ALERT: dict[str, datetime] = {}       # 📥 Fix 450: 학습 멈춤 알림 12시간 dedup (Claude가 정함)
STALE_ALERT_DEDUP_S = 12 * 3600


def run_orchestra_health() -> dict:
    """🎼 매 5분 = 자동 진단 + 자동 fix!"""
    db: Session = SessionLocal()
    checks: list[dict] = []
    fixes_attempted: list[dict] = []
    alerts: list[str] = []
    try:
        # 1. 학습 stale 감지 + 자동 재실행!
        _check_and_fix_learning(db, checks, fixes_attempted, alerts)

        # 1b. 📥 Fix 450: 팀별 학습 완료 기록(orchestra:learning:last)으로 「학습 멈춤」 판정 (알림만, 자동 재실행 없음)
        _check_learning_record(checks, alerts)

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
        # ⏸ Fix 455: 학습 재료가 없어서 멈춘 것 = 고장 아님 → 헛 재실행·지연 판정 안 함 (24h 46번 헛 재실행이었다)
        from app.workers.pattern_learning_worker import no_data_state
        _nd = no_data_state()
        if _nd is not None and age_h > 3:
            checks.append({"team": "pattern_learning", "status": "OK", "note": "no_data",
                           "age_h": round(age_h, 1), "newest_outcome": _nd.get("newest_outcome")})
            return
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


def _check_learning_record(checks, alerts, now=None):
    """📥 Fix 450: 학습 팀이 보낸 「학습 완료」 기록이 26시간 넘게 없으면 STALE. 기록이 아예 없으면 판정하지 않는다(배포 직후)."""
    try:
        from app.agents.orchestrator import receivers as RCV
        rec = RCV.learning_last()
        stale = dict(RCV.stale_learning(rec, now=now))
        for team in sorted(rec):
            checks.append({"team": f"learning_record:{team}", "status": "STALE" if team in stale else "OK",
                           "age_h": stale.get(team)})
        t = now or datetime.now(timezone.utc)
        for team, age in stale.items():
            last = _LAST_STALE_ALERT.get(team)
            if last is not None and (t - last).total_seconds() < STALE_ALERT_DEDUP_S:
                continue
            _LAST_STALE_ALERT[team] = t
            if RCV.alert_once(team, STALE_ALERT_DEDUP_S):     # 반박 리뷰: 재시작해도 12시간 안엔 다시 안 보낸다
                alerts.append(f"📚 {team} 학습 완료 기록 {age:.0f}시간 없음 (학습 멈춤?)")
    except Exception as e:  # noqa: BLE001
        logger.warning("[Fix450] 학습 기록 판정 실패: %s", e)


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
    """entry_snapshot 저장 실패 감지 (알림만!)"""
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
        with_snapshot = sum(
            1 for r in rows
            if r.strategy_config and "entry_snapshot" in (r.strategy_config or {})
        )
        checks.append({
            "team": "entry_snapshot",
            "status": "OK" if with_snapshot == total else "PARTIAL",
            "total_6h": total,
            "with_snapshot": with_snapshot,
        })
        if total > 0 and with_snapshot < total / 2 and _can_attempt_fix("snapshot_missing"):
            alerts.append(
                f"⚠️ entry_snapshot: {with_snapshot}/{total} 저장! "
                f"(학습 조건 분석 저하!)"
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
        _base = [c for c in checks if not str(c.get("team", "")).startswith("learning_record:")]   # 📥 Fix 450
        get_event_bus().publish(EventType.ORCHESTRA_HEALTH_CHECK, {
            "checks": len(_base),
            "healthy": sum(1 for c in _base if c["status"] == "OK"),
            "fixes": len(fixes),
            "learning_stale": sum(1 for c in checks if str(c.get("team", "")).startswith("learning_record:")
                                  and c["status"] == "STALE"),
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
            body="\n".join(alerts) + "\n\n= 같은 알림은 30분(학습 멈춤은 12시간) 안에 다시 안 보냄",
        )
    except Exception as e:
        logger.warning("[v206 P4] 알림 실패: %s", e)
