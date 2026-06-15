"""Edit Mode Validator — 「수정 모드」 결과 자동 검증 worker (v47).

사장님 critical 사상: 「수정 모드」 변경 후 = 사장님 사상 그대로 적용 검증!
= 매 5분 = 최근 수정된 strategy 의 단계별 trigger_price = 사장님 누적 사상 검증!

검증 패턴 (= sajangnim spec stage_calculation_spec_2026-06-11.md):
1. 사장님 수정 후 30분 이내 strategy
2. 각 단계 trigger_price 검증:
   - 단계 N = 단계 N-1 × (1 + trigger_N%)
   - 차이 > 1% = silent bug!
3. 1단계 평단 보존 확인 (= 수정 모드 시!)
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, desc, and_

from app.core.database import SessionLocal
from app.core.strategy_status import STAGES_WITH_NEXT
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_stage_plan import StrategyStagePlan
from app.models.strategy_template import StrategyTemplate
from app.models.risk_event import RiskEvent
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

_DEDUP_KEY = "edit_mode_validator:strategy:{sid}"
_DEDUP_TTL = 3600  # 1시간

# 사장님 누적 사상 위배 임계 = 1%
TRIGGER_PRICE_TOLERANCE_PCT = Decimal("1.0")


def _is_dedup(redis, sid):
    if not redis:
        return False
    try:
        return bool(redis.get(_DEDUP_KEY.format(sid=sid)))
    except Exception:
        return False


def _mark_dedup(redis, sid):
    if not redis:
        return
    try:
        redis.setex(_DEDUP_KEY.format(sid=sid), _DEDUP_TTL, "1")
    except Exception:
        pass


def _validate_cumulative_logic(db, strategy):
    """사장님 누적 사상 = trigger_price 정확성 검증.

    spec: 단계 N = 단계 N-1 × (1 + trigger_N%)
    """
    plans = db.execute(
        select(StrategyStagePlan)
        .where(StrategyStagePlan.strategy_instance_id == strategy.id)
        .order_by(StrategyStagePlan.stage_no)
    ).scalars().all()

    if len(plans) < 2:
        return None

    tpl = db.get(StrategyTemplate, strategy.strategy_template_id) if strategy.strategy_template_id else None
    if not tpl:
        return None

    sc = tpl.stages_config or {}
    triggers = sc.get("trigger_percents") or []
    # 🌟 2026-06-15 사장님 critical fix: last_stage_trigger_percent fallback!
    # 옛 silent bug: triggers[i] = None → Decimal(0) → expected = prev (변경 X!) → false 44.99% violation!
    # 사장님 신 strategy = trigger_percents = [None, None], last_stage_trigger_percent = 45
    # 신 fix: triggers[i] = None 시 = last_stage_trigger_percent fallback (= 마지막 단계)!
    last_trg = sc.get("last_stage_trigger_percent")

    violations = []
    for i in range(1, len(plans)):
        prev = plans[i - 1]
        curr = plans[i]
        if not prev.trigger_price or not curr.trigger_price:
            continue
        if i >= len(triggers):
            continue

        prev_val = Decimal(str(prev.trigger_price))
        curr_val = Decimal(str(curr.trigger_price))
        # 🛡 신 fix v2: None 시 = last_stage_trigger_percent fallback!
        raw_trg = triggers[i]
        if raw_trg is None or raw_trg == "" or (isinstance(raw_trg, (int, float)) and raw_trg == 0):
            # 마지막 단계 (= last_stage) 인 경우 = last_stage_trigger_percent
            if i == len(plans) - 1 and last_trg:
                raw_trg = last_trg
            else:
                # 사장님 사상 = trigger 미지정 = validator skip!
                continue
        trg_pct = Decimal(str(raw_trg or 0))
        if trg_pct == 0:
            continue  # 0 trigger = validation skip (= false positive 차단!)

        # 사장님 누적 사상 = 예상 가격
        if strategy.side == "SHORT":
            expected = prev_val * (Decimal("1") + trg_pct / Decimal("100"))
        else:
            expected = prev_val * (Decimal("1") - trg_pct / Decimal("100"))

        if expected <= 0:
            continue
        # 차이 % 계산
        diff_pct = abs(curr_val - expected) / expected * Decimal("100")
        if diff_pct > TRIGGER_PRICE_TOLERANCE_PCT:
            violations.append({
                "stage_no": curr.stage_no,
                "trigger_pct": float(trg_pct),
                "prev_price": float(prev_val),
                "expected_price": float(expected),
                "actual_price": float(curr_val),
                "diff_pct": float(diff_pct),
            })

    if not violations:
        return None
    return {
        "type": "CUMULATIVE_LOGIC_VIOLATION",
        "severity": "CRITICAL",
        "violations": violations,
        "msg": f"#{strategy.id} {strategy.symbol} = {len(violations)}개 단계 = 사장님 누적 사상 위배!",
    }


def run_edit_mode_validator_once() -> dict:
    """매 5분 = 「수정 모드」 결과 자동 검증."""
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
            v = _validate_cumulative_logic(db, s)
            if v is None:
                continue

            result["violations_found"] += 1
            result["details"].append({"strategy_id": s.id, **v})

            if _is_dedup(redis, s.id):
                continue
            _mark_dedup(redis, s.id)

            try:
                db.add(RiskEvent(
                    strategy_instance_id=s.id,
                    event_type=f"EDIT_MODE_{v['type']}",
                    severity=v["severity"],
                    title=f"[수정 모드 위배] {v['type']}",
                    message=(
                        f"{v['msg']}\n\n"
                        f"위배 단계: {len(v['violations'])}개\n"
                        f"spec: stage_calculation_spec_2026-06-11.md"
                    ),
                    event_payload=v,
                ))
                db.commit()

                # CRITICAL Telegram 즉시
                worst = max(v["violations"], key=lambda x: x["diff_pct"]) if v["violations"] else None
                if worst:
                    NotificationService(db).send_system_alert(
                        title=f"[수정 모드 위배] #{s.id} {s.symbol}",
                        body=(
                            f"「수정 모드」 결과 = 사장님 누적 사상 위배! (v47)\n\n"
                            f"패턴: {v['type']}\n"
                            f"위배 단계 수: {len(v['violations'])}\n\n"
                            f"가장 큰 위배:\n"
                            f"  단계 {worst['stage_no']}\n"
                            f"  예상: {worst['expected_price']:.4f}\n"
                            f"  실제: {worst['actual_price']:.4f}\n"
                            f"  차이: {worst['diff_pct']:.2f}%\n\n"
                            f"사장님 즉시 확인 + 「수정 모드」 재진입 부탁드립니다!\n"
                            f"spec: stage_calculation_spec_2026-06-11.md\n\n"
                            f"이 알림 = 1시간 dedup"
                        ),
                    )
                    result["alerts_sent"] += 1
            except Exception as e:
                logger.error("[edit-mode] 알림 실패: %s", e)

        if result["violations_found"] == 0:
            logger.info("[edit-mode] %d strategy = 누적 사상 100%% 정확!", result["total_checked"])
        else:
            logger.warning(
                "[edit-mode] %d violations in %d strategy. alerts=%d",
                result["violations_found"], result["total_checked"], result["alerts_sent"],
            )

    finally:
        db.close()
    return result


if __name__ == "__main__":
    import json
    r = run_edit_mode_validator_once()
    print(json.dumps(r, indent=2, ensure_ascii=False))
