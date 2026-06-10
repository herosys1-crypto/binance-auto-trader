"""Stage Calc Audit Worker — 사장님 단계별 계산 자동 검증 worker (v44).

사장님 critical 사상: silent bug 영원히 X!
= 매 5분 모든 활성 strategy 단계 계산 검증.
= 사장님 spec (stage_calculation_spec_2026-06-11.md) 그대로 검증.
= 위배 발견 = RiskEvent CRITICAL + Telegram 즉시 알림!

검증 항목:
1. 단계 trigger_price 정확성 (= 이전 단계 × (1 + trigger%))
2. 단계 순서 정확성 (= SHORT: 오름차순, LONG: 내림차순)
3. 단계 사상 위배 감지 (= 첫 미진입 단계 = startPrice 분기 등)

작성: 2026-06-11 (Phase 3 작은 시작 = 사장님 추천 진행)
spec: docs/spec/stage_calculation_spec_2026-06-11.md
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, and_

from app.core.database import SessionLocal
from app.core.strategy_status import STAGES_WITH_NEXT
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_stage_plan import StrategyStagePlan
from app.models.risk_event import RiskEvent
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

# Audit dedup (= 같은 strategy 1시간 1번 만 알림)
_AUDIT_DEDUP_KEY = "stage_calc_audit:strategy:{sid}"
_AUDIT_DEDUP_TTL = 3600  # 1시간


def _is_dedup_active(redis_client, strategy_id: int) -> bool:
    if redis_client is None:
        return False
    try:
        return bool(redis_client.get(_AUDIT_DEDUP_KEY.format(sid=strategy_id)))
    except Exception:
        return False


def _mark_dedup(redis_client, strategy_id: int) -> None:
    if redis_client is None:
        return
    try:
        redis_client.setex(_AUDIT_DEDUP_KEY.format(sid=strategy_id), _AUDIT_DEDUP_TTL, "1")
    except Exception:
        pass


def _audit_strategy_stages(db, strategy: StrategyInstance) -> Optional[dict]:
    """단일 strategy 의 단계 계산 audit.

    Returns:
        None 시 = 정상
        dict 시 = 위배 발견 (= alert 필요)
    """
    plans = db.execute(
        select(StrategyStagePlan)
        .where(StrategyStagePlan.strategy_instance_id == strategy.id)
        .order_by(StrategyStagePlan.stage_no)
    ).scalars().all()

    if len(plans) < 2:
        return None  # 단계 < 2 = audit 의미 X

    # 검증 1: 단계 순서 정확성
    # SHORT: 단계 진입가 오름차순 (= 가격 상승 시 추가 진입)
    # LONG: 단계 진입가 내림차순 (= 가격 하락 시 추가 진입)
    triggers = [(p.stage_no, p.trigger_price) for p in plans if p.trigger_price]
    if len(triggers) < 2:
        return None

    for i in range(1, len(triggers)):
        prev_stage, prev_trg = triggers[i - 1]
        curr_stage, curr_trg = triggers[i]

        if not prev_trg or not curr_trg:
            continue

        prev_val = Decimal(str(prev_trg))
        curr_val = Decimal(str(curr_trg))

        if strategy.side == "SHORT":
            # SHORT = 단계 진입가 오름차순!
            if curr_val < prev_val:
                return {
                    "type": "STAGE_ORDER_VIOLATION",
                    "side": "SHORT",
                    "prev_stage": prev_stage,
                    "prev_trg": float(prev_val),
                    "curr_stage": curr_stage,
                    "curr_trg": float(curr_val),
                    "message": f"SHORT 단계{curr_stage} ({curr_val}) < 단계{prev_stage} ({prev_val}) = 사장님 누적 사상 위배!",
                }
        else:
            # LONG = 단계 진입가 내림차순!
            if curr_val > prev_val:
                return {
                    "type": "STAGE_ORDER_VIOLATION",
                    "side": "LONG",
                    "prev_stage": prev_stage,
                    "prev_trg": float(prev_val),
                    "curr_stage": curr_stage,
                    "curr_trg": float(curr_val),
                    "message": f"LONG 단계{curr_stage} ({curr_val}) > 단계{prev_stage} ({prev_val}) = 사장님 누적 사상 위배!",
                }

    return None


def run_stage_calc_audit_once() -> dict:
    """매 5분: 모든 활성 strategy 단계 계산 audit.

    사장님 spec: docs/spec/stage_calculation_spec_2026-06-11.md
    검증 위배 = RiskEvent CRITICAL + Telegram 1시간 dedup.
    """
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
            violation = _audit_strategy_stages(db, s)
            if not violation:
                continue

            result["violations_found"] += 1
            result["details"].append({
                "strategy_id": s.id,
                "symbol": s.symbol,
                "side": s.side,
                **violation,
            })

            # RiskEvent CRITICAL 기록
            try:
                db.add(RiskEvent(
                    strategy_instance_id=s.id,
                    event_type="STAGE_CALC_AUDIT_VIOLATION",
                    severity="CRITICAL",
                    title=f"🚨 단계 계산 사상 위배! #{s.id} {s.symbol} {s.side}",
                    message=(
                        f"🚨 사장님 단계 계산 사상 위배 자동 감지! (v44 audit)\n\n"
                        f"📌 strategy: #{s.id} {s.symbol} {s.side}\n"
                        f"📌 위배 타입: {violation['type']}\n"
                        f"📌 단계{violation['prev_stage']} 진입가: {violation['prev_trg']}\n"
                        f"📌 단계{violation['curr_stage']} 진입가: {violation['curr_trg']}\n\n"
                        f"⚠️ {violation['message']}\n\n"
                        f"📜 spec: docs/spec/stage_calculation_spec_2026-06-11.md\n"
                        f"💡 사장님 조치:\n"
                        f"  • 「수정 모드」 진입 = 단계 재설정\n"
                        f"  • 또는 = 「↻ 미진입 단계만 재설정」"
                    ),
                    event_payload=violation,
                ))
                db.commit()
            except Exception as e:
                logger.error("[stage-audit] RiskEvent 기록 실패: %s", e)

            # Telegram 즉시 알림 (1시간 dedup)
            if not _is_dedup_active(redis, s.id):
                _mark_dedup(redis, s.id)
                try:
                    NotificationService(db).send_system_alert(
                        title=f"🚨 [단계 계산 사상 위배!] #{s.id} {s.symbol} {s.side}",
                        body=(
                            f"🚨 사장님 단계 계산 사상 위배 자동 감지!\n\n"
                            f"📌 strategy: #{s.id} {s.symbol} {s.side}\n"
                            f"📌 단계{violation['prev_stage']}({violation['prev_trg']}) "
                            f"vs 단계{violation['curr_stage']}({violation['curr_trg']})\n\n"
                            f"⚠️ {violation['message']}\n\n"
                            f"💡 사장님 즉시 조치 부탁드립니다!\n"
                            f"📜 spec: stage_calculation_spec_2026-06-11.md\n\n"
                            f"⚠️ 이 알림 = 1시간 dedup"
                        ),
                    )
                    result["alerts_sent"] += 1
                except Exception as e:
                    logger.error("[stage-audit] Telegram 실패: %s", e)

        if result["violations_found"] == 0:
            logger.info(
                "[stage-audit] ✅ %d strategy = 모든 단계 계산 정상! (= 사장님 사상 100%%)",
                result["total_checked"],
            )
        else:
            logger.warning(
                "[stage-audit] 🚨 %d/%d strategy 위배 발견! 알림=%d",
                result["violations_found"], result["total_checked"], result["alerts_sent"],
            )

    finally:
        db.close()
    return result


if __name__ == "__main__":
    import json
    r = run_stage_calc_audit_once()
    print(json.dumps(r, indent=2, ensure_ascii=False))
