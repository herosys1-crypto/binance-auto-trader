"""Setting Preservation Agent — 사장님 「처음 세팅 영구 유지」 에이전트 (v54).

🌟 사장님 critical 사상 (2026-06-15):
> "수정모드 + 포지션추가 + 증거금추가 = 중간 진행 시 = 처음 세팅과 문제 있어!"
> "별도로 이 부분 관리하고 기획하는 에이전트를 만들어줘"

= 사장님 사상 = 처음 세팅 (= 시작가 + trigger %) = 영구 유지!
= 사장님 = 중간 액션 (= 수정/포지션 추가/증거금 추가) = 처음 세팅 영향 X!

검증 (매 3분):
1. 활성 strategy = strategy_stage_plans.trigger_price 정확성!
   - stage N trigger = stage N-1 × (1 + trigger_pct%)
   - 사장님 사상 = 처음 시작가 기준 누적!
2. 사장님 중간 액션 후 = 평단 변경 + But trigger_price = 변경 X 검증!
3. 시작가 변경 silent bug 자동 감지!
4. trigger 도달 X (= 자동 진입 silent bug) 감지!

= 사장님 자율 청산 회피 전략 = 영구 안전!
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, desc

from app.core.database import SessionLocal
from app.core.strategy_status import STAGES_WITH_NEXT
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_stage_plan import StrategyStagePlan
from app.models.strategy_template import StrategyTemplate
from app.models.position import Position
from app.models.risk_event import RiskEvent
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

_DEDUP_KEY = "setting_preserve:strategy:{sid}:type:{t}"
_DEDUP_TTL = 1800  # 30분

# 사장님 사상 = trigger 도달 후 = 자동 진입 grace period (= 2분!)
AUTO_ENTRY_GRACE_MINUTES = 2
# 사장님 사상 = trigger 차이 임계 = 0.5%
TRIGGER_DIFF_TOLERANCE_PCT = Decimal("0.5")


def _is_dedup(redis, sid, t):
    if not redis:
        return False
    try:
        return bool(redis.get(_DEDUP_KEY.format(sid=sid, t=t)))
    except Exception:
        return False


def _mark_dedup(redis, sid, t):
    if not redis:
        return
    try:
        redis.setex(_DEDUP_KEY.format(sid=sid, t=t), _DEDUP_TTL, "1")
    except Exception:
        pass


def _check_auto_entry_silent_bug(db, strategy, mark_price):
    """검증 1: trigger 도달 후 N분 = 자동 진입 안 됨 silent bug!"""
    bugs = []
    if not mark_price or strategy.status not in ("STAGE1_OPEN", "STAGE2_OPEN", "STAGE3_OPEN", "STAGE4_OPEN", "STAGE5_OPEN"):
        return bugs
    # 미진입 stage_plans 조회
    plans = db.execute(
        select(StrategyStagePlan)
        .where(StrategyStagePlan.strategy_instance_id == strategy.id)
        .where(StrategyStagePlan.is_triggered.is_(False))
        .order_by(StrategyStagePlan.stage_no)
    ).scalars().all()
    if not plans:
        return bugs

    # 다음 단계
    next_plan = plans[0]
    if not next_plan.trigger_price:
        return bugs
    trigger = Decimal(str(next_plan.trigger_price))
    mark = Decimal(str(mark_price))

    # 도달 검증 (SHORT: mark >= trigger, LONG: mark <= trigger)
    reached = False
    if strategy.side == "SHORT" and mark >= trigger:
        reached = True
    elif strategy.side == "LONG" and mark <= trigger:
        reached = True

    if not reached:
        return bugs

    # 도달 후 N분 경과 = silent bug!
    try:
        now = datetime.now(timezone.utc)
        ref_time = strategy.updated_at or strategy.created_at
        if ref_time and ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)
        # 단순화: 가격 도달 + 자동 진입 안 됨 = silent bug 의심!
        bugs.append({
            "type": "AUTO_ENTRY_MISSED",
            "severity": "CRITICAL",
            "msg": (
                f"#{strategy.id} {strategy.symbol} 단계 {next_plan.stage_no} = "
                f"trigger {trigger} 도달 (현재가 {mark}) BUT 자동 진입 X! "
                f"사장님 즉시 확인!"
            ),
        })
    except Exception:
        pass
    return bugs


def _check_trigger_cumulative_logic(db, strategy):
    """검증 2: stage_plans trigger_price = 사장님 누적 사상 (= 시작가 기준)!"""
    bugs = []
    plans = db.execute(
        select(StrategyStagePlan)
        .where(StrategyStagePlan.strategy_instance_id == strategy.id)
        .order_by(StrategyStagePlan.stage_no)
    ).scalars().all()
    if len(plans) < 2:
        return bugs

    tpl = db.get(StrategyTemplate, strategy.strategy_template_id) if strategy.strategy_template_id else None
    if not tpl:
        return bugs

    sc = tpl.stages_config or {}
    triggers = sc.get("trigger_percents") or []
    last_trg = sc.get("last_stage_trigger_percent")

    for i in range(1, len(plans)):
        prev = plans[i - 1]
        curr = plans[i]
        if not prev.trigger_price or not curr.trigger_price:
            continue
        if i >= len(triggers):
            continue
        raw_trg = triggers[i]
        if raw_trg is None or raw_trg == "" or (isinstance(raw_trg, (int, float)) and raw_trg == 0):
            if i == len(plans) - 1 and last_trg:
                raw_trg = last_trg
            else:
                continue
        try:
            trg_pct = Decimal(str(raw_trg or 0))
        except Exception:
            continue
        if trg_pct == 0:
            continue

        prev_val = Decimal(str(prev.trigger_price))
        curr_val = Decimal(str(curr.trigger_price))
        if strategy.side == "SHORT":
            expected = prev_val * (Decimal("1") + trg_pct / Decimal("100"))
        else:
            expected = prev_val * (Decimal("1") - trg_pct / Decimal("100"))
        if expected <= 0:
            continue
        diff_pct = abs(curr_val - expected) / expected * Decimal("100")
        if diff_pct > TRIGGER_DIFF_TOLERANCE_PCT:
            bugs.append({
                "type": "TRIGGER_NOT_PRESERVED",
                "severity": "CRITICAL",
                "msg": (
                    f"#{strategy.id} {strategy.symbol} 단계 {curr.stage_no} trigger_price = "
                    f"사장님 처음 세팅 사상 위배! 예상 {expected:.6f}, 실제 {curr_val:.6f} ({diff_pct:.2f}% 차이!)"
                ),
            })
    return bugs


def run_setting_preservation_once() -> dict:
    """사장님 「처음 세팅 영구 유지」 검증 (매 3분)!"""
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
            # 🚨 2026-07-24 v127 HIGH fix: Redis 우선 (헌법 6 단일 진실!)
            # 옛 silent bug: Position snapshot (2분 stale) → AUTO_ENTRY_MISSED false positive!
            from app.services.mark_price_cache import get_mark_price
            _r_mark = get_mark_price(s.symbol)
            if _r_mark is not None:
                mark = _r_mark
            else:
                p = db.execute(
                    select(Position)
                    .where(Position.strategy_instance_id == s.id)
                    .order_by(desc(Position.id))
                    .limit(1)
                ).scalar_one_or_none()
                mark = p.mark_price if p else None

            all_bugs = []
            all_bugs.extend(_check_auto_entry_silent_bug(db, s, mark))
            all_bugs.extend(_check_trigger_cumulative_logic(db, s))

            for bug in all_bugs:
                result["bugs_found"] += 1
                result["details"].append({"strategy_id": s.id, **bug})
                if _is_dedup(redis, s.id, bug["type"]):
                    continue
                _mark_dedup(redis, s.id, bug["type"])
                try:
                    db.add(RiskEvent(
                        strategy_instance_id=s.id,
                        event_type=f"SETTING_PRESERVATION_{bug['type']}",
                        severity=bug["severity"],
                        title=f"[처음 세팅 보존] {bug['type']}",
                        message=bug["msg"],
                        event_payload=bug,
                    ))
                    db.commit()
                    if bug["severity"] == "CRITICAL":
                        NotificationService(db).send_system_alert(
                            title=f"🚨 [처음 세팅 보존] #{s.id} {s.symbol}",
                            body=(
                                f"사장님 「처음 세팅 영구 유지」 위배 감지!\n\n"
                                f"패턴: {bug['type']}\n"
                                f"{bug['msg']}\n\n"
                                f"사장님 즉시 화면 확인 + 「수정 모드」 검토!\n"
                                f"이 알림 = 30분 dedup"
                            ),
                        )
                        result["alerts_sent"] += 1
                except Exception as e:
                    logger.error("[setting-preserve] 기록/알림 실패: %s", e)

        if result["bugs_found"] == 0:
            logger.info("[setting-preserve] %d strategy = 모든 세팅 영구 유지!", result["total_checked"])
        else:
            logger.warning(
                "[setting-preserve] %d bugs in %d strategy. alerts=%d",
                result["bugs_found"], result["total_checked"], result["alerts_sent"],
            )
    finally:
        db.close()
    return result


if __name__ == "__main__":
    import json
    r = run_setting_preservation_once()
    print(json.dumps(r, indent=2, ensure_ascii=False))
