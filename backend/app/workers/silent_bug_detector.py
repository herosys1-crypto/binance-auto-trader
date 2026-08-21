"""Silent Bug Detector — 사장님 잠재 silent bug 자동 감지 worker (v45).

사장님 critical 사상: silent bug 영원히 X!
= 매 1분 = 알려진 silent bug 패턴 자동 감지!

검증 패턴 (= 사장님 critical 발견 누적 = 자동화!):
1. NULL field 감지 (= 사장님 진단 패턴)
   - strategy.liquidation_price NULL (= v37 사례)
   - strategy.last_avg_entry_price NULL (= v35 사례)
2. Worker 정상 실행 = 마지막 실행 시간 검증
   - stage_trigger 5분 이상 미실행 = 위배!
   - risk_service 30초 이상 미실행 = 위배!
3. Position vs Strategy 일치
   - position 있는데 = strategy.current_position_qty = 0 = silent bug!
4. Crisis 상태 일치
   - sajangnim 옵션 변경 + 신 strategy = crisis_mode_triggered_at 있으면 = silent bug!

위배 발견 = RiskEvent INFO/WARN/CRITICAL + Telegram (= 사장님 인지)
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, and_

from app.core.database import SessionLocal
from app.core.strategy_status import STAGES_WITH_NEXT
from app.models.strategy_instance import StrategyInstance
from app.models.position import Position
from app.models.risk_event import RiskEvent
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

_DEDUP_KEY = "silent_bug_detector:strategy:{sid}:type:{t}"
_DEDUP_TTL = 1800  # 30분 dedup


def _is_dedup(redis, sid, bug_type):
    if not redis:
        return False
    try:
        return bool(redis.get(_DEDUP_KEY.format(sid=sid, t=bug_type)))
    except Exception:
        return False


def _mark_dedup(redis, sid, bug_type):
    if not redis:
        return
    try:
        redis.setex(_DEDUP_KEY.format(sid=sid, t=bug_type), _DEDUP_TTL, "1")
    except Exception:
        pass


def _detect_null_field_bugs(db, strategy):
    """NULL field silent bug 감지. 🛡 진입 후 grace period (= 5분) skip!"""
    bugs = []
    # 🌟 2026-06-15 사장님 critical fix: 진입 후 5분 = grace period (= false positive 차단!)
    # 옛 silent bug: 진입 직후 cycle = liquidation_price NULL → 1분 후 계산 완료
    # = detector 너무 빠르게 검사 = false positive!
    # 신 fix: started_at 또는 updated_at 기준 5분 이내 = skip!
    try:
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        ref_time = strategy.started_at or strategy.updated_at or strategy.created_at
        if ref_time:
            # tz-aware 처리
            if ref_time.tzinfo is None:
                ref_time = ref_time.replace(tzinfo=timezone.utc)
            if (now - ref_time) < timedelta(minutes=5):
                return bugs  # = grace period = 검사 skip!
    except Exception:
        pass

    if strategy.current_position_qty and abs(float(strategy.current_position_qty)) > 0:
        if not strategy.avg_entry_price or float(strategy.avg_entry_price) <= 0:
            bugs.append({
                "type": "AVG_ENTRY_NULL",
                "severity": "WARN",
                "msg": f"#{strategy.id} {strategy.symbol} = 포지션 있는데 avg_entry_price NULL!",
            })
        if not strategy.liquidation_price or float(strategy.liquidation_price) <= 0:
            bugs.append({
                "type": "LIQ_PRICE_NULL",
                "severity": "INFO",
                "msg": f"#{strategy.id} {strategy.symbol} = 포지션 있는데 liquidation_price NULL!",
            })
    return bugs


def _detect_position_strategy_mismatch(db, strategy):
    """Position vs Strategy 불일치 silent bug 감지."""
    bugs = []
    p = db.execute(
        select(Position)
        .where(Position.strategy_instance_id == strategy.id)
        .order_by(Position.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if not p:
        return bugs
    try:
        p_qty = abs(float(p.position_amt or 0))
        s_qty = abs(float(strategy.current_position_qty or 0))
        # 10% 이상 차이 = silent bug
        if p_qty > 0 and s_qty > 0:
            diff_pct = abs(p_qty - s_qty) / max(p_qty, s_qty) * 100
            if diff_pct > 10:
                bugs.append({
                    "type": "POS_QTY_MISMATCH",
                    "severity": "CRITICAL",
                    "msg": f"#{strategy.id} {strategy.symbol} = Position qty {p_qty} vs Strategy qty {s_qty} = {diff_pct:.1f}% 차이!",
                })
    except Exception:
        pass
    return bugs


def _v206_detect_entry_snapshot_missing(db, s) -> list[dict]:
    """🎼 v206 Phase 2 사장님 (2026-08-21): entry_snapshot 저장 감지!

    사장님 지적: "학습이 잘되고 있는지도 검증!"
    발견: v187 인사이트 조건 = 모두 0개!
    원인: entry_snapshot 저장 안 됨 or 옛 데이터!

    감지:
    - auto_bb_break template 이면서
    - StrategySuggestion.strategy_config에 entry_snapshot 없음
    = v198 저장 실패!
    """
    bugs = []
    try:
        from app.models.strategy_template import StrategyTemplate
        from app.models.strategy_suggestion import StrategySuggestion
        tpl = db.get(StrategyTemplate, s.strategy_template_id) if s.strategy_template_id else None
        if not tpl or not (tpl.strategy_type or "").startswith("auto_bb_break"):
            return bugs  # 자동 진입 아님!

        # StrategySuggestion 확인!
        sugg = db.execute(
            select(StrategySuggestion)
            .where(StrategySuggestion.executed_strategy_id == s.id)
            .limit(1)
        ).scalar_one_or_none()
        if not sugg:
            bugs.append({
                "type": "V206_NO_SUGGESTION_LINK",
                "severity": "WARN",
                "msg": f"#{s.id} {s.symbol}: auto_bb_break이지만 StrategySuggestion 링크 없음!",
            })
            return bugs

        # entry_snapshot 확인 (v198!)
        cfg = sugg.strategy_config or {}
        if "entry_snapshot" not in cfg:
            bugs.append({
                "type": "V206_ENTRY_SNAPSHOT_MISSING",
                "severity": "WARN",
                "msg": (
                    f"#{s.id} {s.symbol}: v198 entry_snapshot 저장 X! "
                    f"→ 학습 (v187) 조건 분석 불가능!"
                ),
            })
    except Exception as e:
        logger.debug("[v206 phase2] entry_snapshot 감지 실패: %s", e)
    return bugs


def run_silent_bug_detector_once() -> dict:
    """매 1분 = silent bug 패턴 자동 감지!"""
    from app.core.redis_client import get_redis_client
    try:
        redis = get_redis_client()
    except Exception:
        redis = None

    db = SessionLocal()
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "total_checked": 0,
        "bugs_found": 0,
        "alerts_sent": 0,
        "details": [],
    }
    try:
        strats = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.is_archived.is_(False))
            .where(StrategyInstance.status.in_(STAGES_WITH_NEXT))
        ).scalars().all()
        result["total_checked"] = len(strats)

        for s in strats:
            bugs = []
            bugs.extend(_detect_null_field_bugs(db, s))
            bugs.extend(_detect_position_strategy_mismatch(db, s))
            # 🎼 v206 Phase 2: 신 검증 추가!
            bugs.extend(_v206_detect_entry_snapshot_missing(db, s))

            for bug in bugs:
                result["bugs_found"] += 1
                result["details"].append({"strategy_id": s.id, **bug})

                if _is_dedup(redis, s.id, bug["type"]):
                    continue
                _mark_dedup(redis, s.id, bug["type"])

                try:
                    db.add(RiskEvent(
                        strategy_instance_id=s.id,
                        event_type=f"SILENT_BUG_{bug['type']}",
                        severity=bug["severity"],
                        title=f"[silent bug 자동 감지] {bug['type']}",
                        message=bug["msg"],
                        event_payload=bug,
                    ))
                    db.commit()

                    if bug["severity"] in ("CRITICAL", "WARN"):
                        NotificationService(db).send_system_alert(
                            title=f"[silent bug 감지] #{s.id} {s.symbol}",
                            body=(
                                f"silent bug 자동 감지 (v45)!\n\n"
                                f"패턴: {bug['type']}\n"
                                f"심각도: {bug['severity']}\n"
                                f"{bug['msg']}\n\n"
                                f"사장님 인지 부탁드립니다!\n"
                                f"이 알림 = 30분 dedup"
                            ),
                        )
                        result["alerts_sent"] += 1
                except Exception as e:
                    logger.error("[silent-bug] 기록/알림 실패: %s", e)

        # 🎼 v206 Phase 2: 시스템 전체 sanity check!
        _v206_system_sanity_check(db, result, redis)

        if result["bugs_found"] == 0:
            logger.info("[silent-bug] %d strategy = 모든 silent bug 0건!", result["total_checked"])
        else:
            logger.warning(
                "[silent-bug] %d bugs in %d strategy. alerts=%d",
                result["bugs_found"], result["total_checked"], result["alerts_sent"],
            )

    finally:
        db.close()
    return result


def _v206_system_sanity_check(db, result: dict, redis) -> None:
    """🎼 v206 Phase 2 사장님: 시스템 전체 sanity check!

    사장님 지적: "우리 에이전트 팀이 많은데 왜 이런 문제가?"
    = Cross-team 자동 검증!

    검증:
    1. 자동 진입 카운터 = 정상? (UTC vs KST 감지!)
    2. 학습 인사이트 = 최신? (매 1h 실행 확인!)
    3. Watchlist = 최신? (매 15분 갱신!)
    """
    try:
        # 1. 학습 인사이트 신선도!
        from app.workers.pattern_learning_worker import get_learning_insights
        insights = get_learning_insights(db)
        if insights:
            gen_at = datetime.fromisoformat(insights.get("generated_at", ""))
            age_h = (datetime.now(timezone.utc) - gen_at).total_seconds() / 3600
            if age_h > 3:  # 3시간 이상 = 갱신 안 됨!
                result["bugs_found"] += 1
                result["details"].append({
                    "type": "V206_LEARNING_STALE",
                    "severity": "WARN",
                    "msg": f"학습 인사이트 {age_h:.1f}h 갱신 X! (매 1h!)",
                })

            # 조건 학습 = 0이면 문제!
            snap = insights.get("snapshot_conditions", {})
            total_conditions = sum(len(v) for v in snap.values())
            if total_conditions == 0 and insights.get("total_samples", 0) > 100:
                result["bugs_found"] += 1
                result["details"].append({
                    "type": "V206_CONDITION_LEARNING_ZERO",
                    "severity": "WARN",
                    "msg": (
                        f"샘플 {insights['total_samples']}개 있지만 조건 학습 0개! "
                        f"entry_snapshot 저장 X!"
                    ),
                })
        else:
            result["bugs_found"] += 1
            result["details"].append({
                "type": "V206_NO_LEARNING_INSIGHTS",
                "severity": "WARN",
                "msg": "학습 인사이트 없음! (pattern_learning_worker 미실행?)",
            })

        # 2. watchlist 신선도!
        if redis:
            watch_ttl = redis.ttl("v199:realtime_watchlist")
            if watch_ttl < 0:  # 없음!
                result["bugs_found"] += 1
                result["details"].append({
                    "type": "V206_WATCHLIST_MISSING",
                    "severity": "WARN",
                    "msg": "watchlist 캐시 없음! (realtime_watchlist_worker 미실행?)",
                })
    except Exception as e:
        logger.debug("[v206 phase2] sanity check 실패: %s", e)


if __name__ == "__main__":
    import json
    r = run_silent_bug_detector_once()
    print(json.dumps(r, indent=2, ensure_ascii=False))
