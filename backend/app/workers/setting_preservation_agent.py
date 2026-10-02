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


# 🚦 Fix 410 (2026-10-03, Duel auto-entry-missed): 「트리거 도달 = 즉시 CRITICAL」 오탐 (사람 수동 포지션 3건, 이틀 13건 + 알림).
#   ① 2분 이상 계속 닿아 있을 때만 (위 AUTO_ENTRY_GRACE_MINUTES 가 정의만 있고 안 쓰였다)
#   ② 단계 워커가 의도적으로 막은 사유(Redis)가 있으면 INFO AUTO_ENTRY_BLOCKED (알림 없음)
#   ③ Redis 로 확인할 수 없으면 WARN AUTO_ENTRY_UNVERIFIED — CRITICAL 과 유형을 나눠 dedup 이 진짜 CRITICAL 을 막지 않게
_REACHED_KEY = "setting_preserve:reached:{sid}:{stage}"
_REACHED_TTL = 6 * 3600
_REACHED_GAP_SEC = 7 * 60          # Claude가 정함 — 3분 주기 2회 + 여유. 이보다 오래 관측이 끊기면 처음부터 다시 센다
_BLOCK_KEY = "stage_trigger_block:strategy:{sid}"     # stage_trigger_worker._BLOCK_REASON_KEY 와 같은 키
_BLOCK_FRESH_SEC = 600             # 사유 TTL 10분과 같다
_BLOCK_FUTURE_TOL_SEC = 60         # 다른 프로세스가 방금 덮어쓴 시각(약간 미래) 허용 — 버리면 오탐이 되살아난다 (Claude 감사)


def _aware_utc(dt):
    if dt is None:
        return datetime.now(timezone.utc)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _as_text(v):
    if v is None:
        return None
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return v if isinstance(v, str) else None


def _small_int(v):
    """bool·소수·4,300자리 넘는 문자열 등은 None (int 변환 예외 차단)."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().lstrip("-").isdigit() and len(v.strip()) <= 9:
        return int(v.strip())
    return None


def _parse_block(raw, next_stage: int, now) -> dict | None:
    """유효한(같은 단계 또는 0 · 10분 이내 · 약간의 미래 허용) 차단 기록이면 {"reason": str}, 아니면 None. 예외를 내지 않는다."""
    import json
    try:
        d = json.loads(_as_text(raw) or "")
        if not isinstance(d, dict):
            return None
        st = _small_int(d.get("stage_no"))
        if st is None or st not in (0, next_stage):
            return None
        at = d.get("blocked_at")
        if not isinstance(at, str) or len(at) > 64:
            return None
        t = datetime.fromisoformat(at.replace("Z", "+00:00"))
        if t.tzinfo is None:
            return None
        age = (now - t).total_seconds()
        if not (-_BLOCK_FUTURE_TOL_SEC <= age <= _BLOCK_FRESH_SEC):
            return None
        reason = d.get("reason")
        reason = reason.strip() if isinstance(reason, str) and reason.strip() else "(사유 미기재)"
        return {"reason": reason[:200]}
    except (ValueError, TypeError, OverflowError):
        return None


def _reached_elapsed(redis, sid: int, stage: int, now) -> float:
    """처음 닿은 뒤 경과 초 (첫·마지막 관측 함께 저장 — 지우기 실패로 남은 옛 표식이 「지속」 증거가 되지 않게). Redis 예외는 그대로 올린다."""
    import json
    key = _REACHED_KEY.format(sid=sid, stage=stage)
    ts = now.timestamp()
    first = ts
    d = None
    try:
        d = json.loads(_as_text(redis.get(key)) or "null")
    except (ValueError, TypeError):
        d = None
    if isinstance(d, dict):
        f, last = d.get("first"), d.get("last")
        if (isinstance(f, (int, float)) and isinstance(last, (int, float)) and not isinstance(f, bool)
                and f <= last <= ts + 1 and ts - last <= _REACHED_GAP_SEC):
            first = float(f)
    redis.setex(key, _REACHED_TTL, json.dumps({"first": first, "last": ts}))
    return max(0.0, ts - first)


def _forget_reached(redis, sid: int, stage: int) -> None:
    if redis is None:
        return
    try:
        redis.delete(_REACHED_KEY.format(sid=sid, stage=stage))
    except Exception as e:  # noqa: BLE001 — 지우지 못해도 다음 관측에서 7분 간격 규칙으로 다시 센다
        logger.debug("[setting-preserve] 도달 표식 삭제 실패(무시): %s", e)


def _check_auto_entry_silent_bug(db, strategy, mark_price, redis=None, now=None):
    """검증 1: trigger 도달 후 N분 = 자동 진입 안 됨 silent bug!"""
    bugs = []
    if not mark_price or strategy.status not in ("STAGE1_OPEN", "STAGE2_OPEN", "STAGE3_OPEN", "STAGE4_OPEN", "STAGE5_OPEN"):
        return bugs
    # 🔀 Fix 369: OBV 자동은 가격이 아니라 stage_entry_signal 로 단계에 들어간다 — 계획에 남은 가격 트리거로 「진입 누락」을 판정하면
    #   CRITICAL 오탐이다 (워커 감사 9/13). 가격 트리거 가족(기존 방식 등)만 본다.
    try:
        from app.services.strategy_family import OBV_AUTO, family_of
        if family_of(strategy) == OBV_AUTO:
            return bugs
    except Exception:  # noqa: BLE001
        pass
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

    stage = int(next_plan.stage_no)
    if not reached:
        _forget_reached(redis, strategy.id, stage)
        return bugs

    now = _aware_utc(now)
    head = f"#{strategy.id} {strategy.symbol} 단계 {stage} = trigger {trigger} 도달 (현재가 {mark})"
    if redis is None:
        bugs.append({"type": "AUTO_ENTRY_UNVERIFIED", "severity": "WARN",
                     "msg": f"{head} — Redis 없음: 지속 시간·차단 사유 확인 불가 (자동 진입 여부 직접 확인)"})
        return bugs
    try:
        elapsed = _reached_elapsed(redis, strategy.id, stage, now)
    except Exception as e:  # noqa: BLE001
        bugs.append({"type": "AUTO_ENTRY_UNVERIFIED", "severity": "WARN",
                     "msg": f"{head} — Redis 오류로 지속 시간 확인 불가: {str(e)[:120]}"})
        return bugs
    if elapsed < AUTO_ENTRY_GRACE_MINUTES * 60:
        return bugs                                     # 아직 유예 — 단계 워커(15초 주기)가 들어갈 시간
    try:
        block = _parse_block(redis.get(_BLOCK_KEY.format(sid=strategy.id)), stage, now)
    except Exception as e:  # noqa: BLE001
        bugs.append({"type": "AUTO_ENTRY_UNVERIFIED", "severity": "WARN",
                     "msg": f"{head} {elapsed / 60:.0f}분째 — 차단 사유 조회 실패: {str(e)[:120]}"})
        return bugs
    if block is not None:
        bugs.append({"type": "AUTO_ENTRY_BLOCKED", "severity": "INFO",
                     "msg": f"{head} {elapsed / 60:.0f}분째 — 진입 워커가 의도적으로 보류: {block['reason']}"})
        return bugs
    bugs.append({
        "type": "AUTO_ENTRY_MISSED",
        "severity": "CRITICAL",
        "msg": f"{head} {elapsed / 60:.0f}분째 BUT 자동 진입 X · 차단 사유 기록도 없음! 사장님 즉시 확인!",
    })
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
            all_bugs.extend(_check_auto_entry_silent_bug(db, s, mark, redis=redis))   # Fix 410: 지속·차단 사유 확인
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
                    try:  # Fix 410 (Gemini 심판): 롤백 안 하면 세션이 PendingRollback 으로 오염돼 이후 전략 검사가 전부 실패
                        db.rollback()
                    except Exception:  # noqa: BLE001
                        pass

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
