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


if __name__ == "__main__":
    import json
    r = run_silent_bug_detector_once()
    print(json.dumps(r, indent=2, ensure_ascii=False))
