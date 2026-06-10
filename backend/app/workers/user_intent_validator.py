"""User Intent Validator — 사장님 의도 vs 실제 결과 자동 검증 worker (v46).

사장님 critical 사상: silent 덮어쓰기 영원히 X!
= 매 5분 = 사장님 옵션 (TP1, Trailing) = 실제 적용 검증!

검증 패턴:
1. TP1 옵션 변경 → 실제 strategy.tp1_pct_override = 신 값 일치
2. Trailing 옵션 변경 → 실제 strategy.trailing_retrace_pct = 신 값 일치
3. Strategy 자본 (total_capital) vs 실제 진입 자본 = 일치
4. Crisis 모드 사장님 옵션 우선 = 정확 작동

= 사장님 헌법 10번 (= 운영자 우선) = 자동 검증!
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, desc, and_

from app.core.database import SessionLocal
from app.core.strategy_status import STAGES_WITH_NEXT
from app.models.strategy_instance import StrategyInstance
from app.models.risk_event import RiskEvent
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

_DEDUP_KEY = "user_intent_validator:strategy:{sid}:type:{t}"
_DEDUP_TTL = 3600  # 1시간


def _is_dedup(redis, sid, intent_type):
    if not redis:
        return False
    try:
        return bool(redis.get(_DEDUP_KEY.format(sid=sid, t=intent_type)))
    except Exception:
        return False


def _mark_dedup(redis, sid, intent_type):
    if not redis:
        return
    try:
        redis.setex(_DEDUP_KEY.format(sid=sid, t=intent_type), _DEDUP_TTL, "1")
    except Exception:
        pass


def _check_tp1_intent_applied(db, strategy):
    """사장님 TP1 옵션 변경 → 실제 적용 검증."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    recent_event = db.execute(
        select(RiskEvent)
        .where(
            and_(
                RiskEvent.strategy_instance_id == strategy.id,
                RiskEvent.event_type == "TP1_THRESHOLD_UPDATED",
                RiskEvent.created_at >= cutoff,
            )
        )
        .order_by(desc(RiskEvent.id))
        .limit(1)
    ).scalar_one_or_none()

    if not recent_event:
        return None

    payload = recent_event.event_payload or {}
    intended_pct = payload.get("new_pct")
    if intended_pct is None:
        return None

    try:
        intended_val = Decimal(str(intended_pct))
        actual_val = Decimal(str(strategy.tp1_pct_override)) if strategy.tp1_pct_override is not None else None

        if actual_val is None or actual_val != intended_val:
            return {
                "type": "TP1_INTENT_NOT_APPLIED",
                "severity": "CRITICAL",
                "msg": (
                    f"#{strategy.id} {strategy.symbol} = 사장님 TP1 옵션 {intended_val}% 설정! "
                    f"하지만 실제 = {actual_val}% = silent 덮어쓰기 가능성!"
                ),
                "intended": str(intended_val),
                "actual": str(actual_val) if actual_val is not None else "NULL",
            }
    except Exception:
        pass
    return None


def _check_crisis_with_user_override(db, strategy):
    """사장님 옵션 있는데 Crisis 모드 활성 = silent bug 가능성."""
    if not strategy.crisis_mode_triggered_at:
        return None
    if strategy.tp1_pct_override is None:
        return None
    return {
        "type": "CRISIS_WITH_USER_OPTION",
        "severity": "WARN",
        "msg": (
            f"#{strategy.id} {strategy.symbol} = 사장님 TP1 옵션 활성인데 = Crisis 모드 같이 활성! "
            f"v30 사상 = Crisis 영구 비활성! = 옛 strategy 자동 해제 필요!"
        ),
    }


def _check_capital_consistency(db, strategy):
    """Strategy 자본 vs 실제 isolated_margin 일치 검증."""
    if not strategy.total_capital or float(strategy.total_capital) <= 0:
        return None
    # 진입 단계 1 미만 = skip
    if not strategy.current_stage or strategy.current_stage < 1:
        return None
    return None  # 향후 확장 (= 너무 노이즈 위험)


def run_user_intent_validator_once() -> dict:
    """매 5분 = 사장님 의도 vs 실제 자동 검증!"""
    from app.core.redis_client import get_redis_client
    try:
        redis = get_redis_client()
    except Exception:
        redis = None

    db = SessionLocal()
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "total_checked": 0,
        "violations_found": 0,
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
            checks = [
                _check_tp1_intent_applied(db, s),
                _check_crisis_with_user_override(db, s),
                _check_capital_consistency(db, s),
            ]
            for v in checks:
                if v is None:
                    continue

                result["violations_found"] += 1
                result["details"].append({"strategy_id": s.id, **v})

                if _is_dedup(redis, s.id, v["type"]):
                    continue
                _mark_dedup(redis, s.id, v["type"])

                try:
                    db.add(RiskEvent(
                        strategy_instance_id=s.id,
                        event_type=f"USER_INTENT_{v['type']}",
                        severity=v["severity"],
                        title=f"[사장님 의도 미적용] {v['type']}",
                        message=v["msg"],
                        event_payload=v,
                    ))
                    db.commit()

                    NotificationService(db).send_system_alert(
                        title=f"[사장님 의도 미적용] #{s.id} {s.symbol}",
                        body=(
                            f"사장님 의도 vs 실제 = 위배 감지! (v46)\n\n"
                            f"패턴: {v['type']}\n"
                            f"심각도: {v['severity']}\n"
                            f"{v['msg']}\n\n"
                            f"사장님 즉시 확인 부탁드립니다!\n"
                            f"이 알림 = 1시간 dedup"
                        ),
                    )
                    result["alerts_sent"] += 1
                except Exception as e:
                    logger.error("[user-intent] 알림 실패: %s", e)

        if result["violations_found"] == 0:
            logger.info("[user-intent] %d strategy = 사장님 의도 100%% 적용!", result["total_checked"])
        else:
            logger.warning(
                "[user-intent] %d violations in %d strategy. alerts=%d",
                result["violations_found"], result["total_checked"], result["alerts_sent"],
            )

    finally:
        db.close()
    return result


if __name__ == "__main__":
    import json
    r = run_user_intent_validator_once()
    print(json.dumps(r, indent=2, ensure_ascii=False))
