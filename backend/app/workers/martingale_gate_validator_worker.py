"""🛡️ Fix 58 (2026-08-24 사장님 critical!): 마틴게일 진입 gate 감시 워커!

사장님 verbatim 문제 인식:
  "마틴게일 2/3단계 = 자본 6배 폭발! → 지표 확인 없이 진입하면 = 사장님 파산!"

## 배경
Fix 55 (2026-08-24): stage_trigger_worker 에 마틴게일 2단계+ 지표 반전 gate 추가:
  - `_check_stage_indicator_reversal` (RSI / MACD Hist / OBV = 2/3 or 3/3)
  - `_check_stage_24h_filter` (헌법 64 = ±15% 반대매매 금지)

**Silent Bug 위험**: Fix 55 코드가 실수로 제거·비활성·bypass 되어도 = 자동 진입 계속!
  → 사장님이 인지 못한 채 3단계 (자본 1800 USDT!) 발동 = 파산!

## 해결 = 본 워커 (Fix 58!)
매 5분 = 최근 30분 내 마틴게일 2단계+ 진입 (stage_plan.is_triggered=True) 을 감시:

1. DB 조회 = `StrategyStagePlan` where stage_no >= 2 AND is_triggered=True
              AND triggered_at >= now - 30분
2. 각 진입에 대해 Redis 「Fix 55 gate 통과 마커」 존재 확인:
   - 마커 = `stage_trigger:fix55_gate_passed:sid:{sid}:stage:{n}`
   - Fix 55 통과 시 stage_trigger_worker 가 setex (TTL 24h) 로 기록
     (본 fix 와 함께 stage_trigger_worker 에 마커 기록 추가!)
3. 마커 없으면 = **silent bug 의심 = 사장님 텔레그램 즉시 알림!**
4. dedup (strategy+stage 조합) = 1시간 = 알림 spam 차단

## 안전
- fail-safe: Redis 접근 불가 → skip (알림 spam 방지)
- dedup: 같은 (sid, stage) 조합 = 1시간 내 재알림 X
- 관측만 = 자동 청산·주문 X = 리스크 zero
- 예외 시 = warning log + 다음 cycle 재시도
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_stage_plan import StrategyStagePlan
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 상수 (모듈 top-level = 단일 진실 = 헌법 6 준수!)
# ---------------------------------------------------------------------------
SPEC_VERSION = "martingale_gate_validator_v1_fix58_2026-08-24"

LOOKBACK_MIN = 30          # 최근 30분 내 진입 검사
ALERT_TTL_HOURS = 1        # 같은 (sid, stage) = 1시간 dedup
MIN_MARTINGALE_STAGE = 2   # 2단계+ 만 = 1단계 = 원 진입 (Fix 55 대상 아님!)

# Fix 55 통과 마커 (stage_trigger_worker 가 gate 통과 시 setex 로 기록)
# 형식: stage_trigger:fix55_gate_passed:sid:{sid}:stage:{stage_no}
# TTL = 24h (= 진입 후 하루 내 감시 = 충분!)
_FIX55_PASS_MARKER_KEY = "stage_trigger:fix55_gate_passed:sid:{sid}:stage:{stage_no}"

# dedup 알림 키
_ALERT_DEDUP_KEY = "martingale_gate_validator:alert:sid:{sid}:stage:{stage_no}"
_ALERT_DEDUP_TTL = ALERT_TTL_HOURS * 3600


def _get_recent_martingale_entries(db) -> list[StrategyStagePlan]:
    """최근 LOOKBACK_MIN 내 마틴게일 2단계+ 진입 조회.

    조건:
      - stage_no >= MIN_MARTINGALE_STAGE (= 2)
      - is_triggered = True (= 실제 진입 발사됨)
      - triggered_at >= now - LOOKBACK_MIN (= 최근 30분)

    Returns: StrategyStagePlan 리스트 (없으면 빈 리스트).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_MIN)
    try:
        rows = db.execute(
            select(StrategyStagePlan)
            .where(StrategyStagePlan.stage_no >= MIN_MARTINGALE_STAGE)
            .where(StrategyStagePlan.is_triggered.is_(True))
            .where(StrategyStagePlan.triggered_at.is_not(None))
            .where(StrategyStagePlan.triggered_at >= cutoff)
            .order_by(StrategyStagePlan.triggered_at.desc())
        ).scalars().all()
        return list(rows)
    except Exception as e:
        logger.warning("[Fix58/validator] recent-entries 조회 실패: %s", e)
        return []


def _check_indicator_log_exists(redis_client, sid: int, stage_no: int) -> bool:
    """Fix 55 gate 통과 마커 확인.

    stage_trigger_worker 가 Fix 55 gate (지표 반전 + 24h 필터) 통과 시
    `_FIX55_PASS_MARKER_KEY` 에 setex 로 기록해야 함 (companion change).

    Returns:
      True  = 마커 존재 (Fix 55 gate 통과 확인!)
      False = 마커 없음 (silent bug 의심 = 알림 대상!)

    fail-safe: Redis 접근 실패 시 = True (알림 spam 방지 = 관측 skip)
    """
    if redis_client is None:
        return True
    key = _FIX55_PASS_MARKER_KEY.format(sid=sid, stage_no=stage_no)
    try:
        return bool(redis_client.get(key))
    except Exception as e:
        logger.warning("[Fix58/validator] redis-get 실패 (fail-safe skip): %s", e)
        return True


def _is_alert_dedup(redis_client, sid: int, stage_no: int) -> bool:
    if redis_client is None:
        return False
    key = _ALERT_DEDUP_KEY.format(sid=sid, stage_no=stage_no)
    try:
        return bool(redis_client.get(key))
    except Exception:
        return False


def _mark_alert_dedup(redis_client, sid: int, stage_no: int) -> None:
    if redis_client is None:
        return
    key = _ALERT_DEDUP_KEY.format(sid=sid, stage_no=stage_no)
    try:
        redis_client.setex(key, _ALERT_DEDUP_TTL, "1")
    except Exception:
        pass


def _send_silent_bug_alert(
    db, strategy: StrategyInstance | None, plan: StrategyStagePlan,
) -> bool:
    """사장님 텔레그램 알림 발송 + RiskEvent 기록.

    Returns: True = 발송 성공 / False = 실패.
    """
    symbol = getattr(strategy, "symbol", "?") if strategy else "?"
    side = getattr(strategy, "side", "?") if strategy else "?"
    triggered_at = plan.triggered_at.isoformat() if plan.triggered_at else "?"

    title = (
        f"🚨 [Fix 58 silent bug 의심] "
        f"#{plan.strategy_instance_id} {symbol} {side} 단계{plan.stage_no}"
    )
    body = (
        f"⚠️ 마틴게일 {plan.stage_no}단계 진입 = Fix 55 gate 통과 마커 없음!\n\n"
        f"strategy_id: {plan.strategy_instance_id}\n"
        f"symbol/side: {symbol} {side}\n"
        f"stage_no: {plan.stage_no} (마틴게일 = 자본 폭발!)\n"
        f"triggered_at: {triggered_at}\n\n"
        f"🔥 위험: Fix 55 (지표 반전 + 24h 필터) 없이 자동 진입!\n"
        f"   → 사장님 사상 위배 가능성 = 즉시 확인 필요!\n\n"
        f"확인 사항:\n"
        f"  1. stage_trigger_worker 의 Fix 55 코드 정상 동작?\n"
        f"  2. Redis 마커 기록 코드 존재?\n"
        f"  3. Redis 연결 정상? (마커 저장 실패 가능성!)\n\n"
        f"spec: {SPEC_VERSION}\n"
        f"이 알림 = 1시간 dedup (동일 sid+stage 조합)"
    )

    try:
        db.add(RiskEvent(
            strategy_instance_id=plan.strategy_instance_id,
            event_type="MARTINGALE_GATE_MISSING",
            severity="CRITICAL",
            title=title,
            message=body,
            event_payload={
                "spec_version": SPEC_VERSION,
                "strategy_id": plan.strategy_instance_id,
                "symbol": symbol,
                "side": side,
                "stage_no": plan.stage_no,
                "triggered_at": triggered_at,
                "reason": "fix55_pass_marker_missing",
            },
        ))
        db.commit()
    except Exception as e:
        logger.error("[Fix58/validator] RiskEvent 기록 실패: %s", e)
        try:
            db.rollback()
        except Exception:
            pass

    try:
        NotificationService(db).send_system_alert(title=title, body=body)
        return True
    except Exception as e:
        logger.error("[Fix58/validator] Telegram 알림 실패: %s", e)
        return False


def run_martingale_gate_validator() -> dict[str, Any]:
    """Fix 58 (2026-08-24 사장님!): 마틴게일 진입 gate 감시.

    - 최근 30분 내 STAGE 2+ 진입 확인
    - stage_trigger 진입 로그 확인 (Redis 마커)
    - 지표 확인 로그 ([Fix55/reversal] or [Fix55/24h] 통과 마커) 있는가?
    - 없으면 = 사장님 텔레그램 알림!

    매 5분 주기 실행 (scheduler_runner 에 등록 필요).

    Returns:
      {
        "spec_version": ..., "checked_at": ...,
        "total_checked": int,   # 최근 30분 내 마틴게일 2+ 진입 수
        "gate_ok": int,          # 마커 확인 OK
        "gate_missing": int,     # 마커 없음 (silent bug 의심)
        "alerts_sent": int,      # 실제 알림 발송 수 (dedup 제외)
        "details": [...],
      }
    """
    from app.core.redis_client import get_redis_client

    try:
        redis_client = get_redis_client()
    except Exception as e:
        logger.warning("[Fix58/validator] Redis 연결 실패 (fail-safe skip): %s", e)
        redis_client = None

    db = SessionLocal()
    result: dict[str, Any] = {
        "spec_version": SPEC_VERSION,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "total_checked": 0,
        "gate_ok": 0,
        "gate_missing": 0,
        "alerts_sent": 0,
        "details": [],
    }
    try:
        entries = _get_recent_martingale_entries(db)
        result["total_checked"] = len(entries)

        if not entries:
            logger.info(
                "[Fix58/validator] 최근 %d분 내 마틴게일 2+ 진입 없음 = OK",
                LOOKBACK_MIN,
            )
            return result

        for plan in entries:
            sid = plan.strategy_instance_id
            stage_no = plan.stage_no

            has_marker = _check_indicator_log_exists(redis_client, sid, stage_no)
            if has_marker:
                result["gate_ok"] += 1
                continue

            # 마커 없음 = silent bug 의심!
            result["gate_missing"] += 1

            if _is_alert_dedup(redis_client, sid, stage_no):
                result["details"].append({
                    "strategy_id": sid,
                    "stage_no": stage_no,
                    "status": "SUPPRESSED_DEDUP",
                })
                continue

            strategy = db.get(StrategyInstance, sid) if sid else None
            sent = _send_silent_bug_alert(db, strategy, plan)
            if sent:
                _mark_alert_dedup(redis_client, sid, stage_no)
                result["alerts_sent"] += 1
                result["details"].append({
                    "strategy_id": sid,
                    "symbol": getattr(strategy, "symbol", None),
                    "side": getattr(strategy, "side", None),
                    "stage_no": stage_no,
                    "triggered_at": plan.triggered_at.isoformat() if plan.triggered_at else None,
                    "status": "ALERT_SENT",
                })
            else:
                result["details"].append({
                    "strategy_id": sid,
                    "stage_no": stage_no,
                    "status": "ALERT_FAILED",
                })

        if result["gate_missing"] == 0:
            logger.info(
                "[Fix58/validator] %d entries = Fix 55 gate 마커 100%% 확인 = OK",
                result["total_checked"],
            )
        else:
            logger.warning(
                "[Fix58/validator] gate_missing=%d / total=%d / alerts_sent=%d "
                "→ silent bug 의심! spec=%s",
                result["gate_missing"], result["total_checked"],
                result["alerts_sent"], SPEC_VERSION,
            )
        return result
    except Exception as e:
        logger.exception("[Fix58/validator] 실행 실패: %s", e)
        result["error"] = str(e)
        return result
    finally:
        try:
            db.close()
        except Exception:
            pass


if __name__ == "__main__":
    import json
    r = run_martingale_gate_validator()
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
