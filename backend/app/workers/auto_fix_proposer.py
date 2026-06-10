"""Auto Fix Proposer — silent bug 자동 fix 제안 worker (v49).

사장님 critical 사상: silent bug 발견 = 자동 fix 제안!
= 매 5분 = 신 RiskEvent CRITICAL/WARN 조회 = 알려진 fix 패턴 자동 제안!

검증 + fix 매핑:
1. USER_INTENT_TP1_INTENT_NOT_APPLIED → Crisis 자동 해제 + Redis flag
2. EDIT_MODE_CUMULATIVE_LOGIC_VIOLATION → 「수정 모드」 재진입 안내
3. SILENT_BUG_POS_QTY_MISMATCH → reconcile_worker 강제 실행 제안
4. STAGE_CALC_AUDIT_VIOLATION → 「↻ 미진입 단계 재설정」 안내

= 사장님 인지 + 즉시 액션!
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, and_, desc

from app.core.database import SessionLocal
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

_DEDUP_KEY = "auto_fix_proposer:event:{eid}"
_DEDUP_TTL = 7200  # 2시간


def _is_dedup(redis, event_id):
    if not redis:
        return False
    try:
        return bool(redis.get(_DEDUP_KEY.format(eid=event_id)))
    except Exception:
        return False


def _mark_dedup(redis, event_id):
    if not redis:
        return
    try:
        redis.setex(_DEDUP_KEY.format(eid=event_id), _DEDUP_TTL, "1")
    except Exception:
        pass


# Fix 매핑 = 알려진 패턴 → 사장님 액션 가이드
FIX_PROPOSALS = {
    "USER_INTENT_TP1_INTENT_NOT_APPLIED": {
        "action": "Crisis 자동 해제 + Redis flag 설정",
        "ssh_cmd": (
            "docker compose exec api python -c \"\n"
            "from app.core.database import SessionLocal\n"
            "from app.models.strategy_instance import StrategyInstance\n"
            "from sqlalchemy import select\n"
            "db = SessionLocal()\n"
            "s = db.execute(select(StrategyInstance).where(StrategyInstance.id == {sid})).scalar_one_or_none()\n"
            "if s and s.crisis_mode_triggered_at:\n"
            "    s.crisis_mode_triggered_at = None\n"
            "    db.commit()\n"
            "    print('✅ Crisis 해제!')\n"
            "db.close()\"\n"
        ),
        "explain": "사장님 TP1 옵션 = 즉시 적용 시 = Crisis 모드 자동 해제 필요 (v30 사상)",
    },
    "EDIT_MODE_CUMULATIVE_LOGIC_VIOLATION": {
        "action": "「수정 모드」 재진입 + 「현재가」 클릭",
        "ssh_cmd": None,
        "explain": "단계 진입가 사상 위배! 사장님 UI 에서 「✏️ 수정」 → 「💲 현재가」 클릭 시 = 신 v40 누적 logic 적용!",
    },
    "SILENT_BUG_POS_QTY_MISMATCH": {
        "action": "reconcile_worker 강제 실행",
        "ssh_cmd": (
            "docker compose exec api python -c \"\n"
            "from app.workers.reconcile_worker import run_position_reconcile_once\n"
            "from app.core.crypto import decrypt_text\n"
            "run_position_reconcile_once(decrypt_text)\n"
            "print('✅ reconcile 완료!')\"\n"
        ),
        "explain": "Position DB ↔ Binance qty 불일치! reconcile_worker 강제 실행 = 즉시 sync!",
    },
    "STAGE_CALC_AUDIT_VIOLATION": {
        "action": "「↻ 미진입 단계만 재설정」 또는 「✏️ 수정」",
        "ssh_cmd": None,
        "explain": "단계 가격 순서 위배! 사장님 UI = 「↻ 미진입 단계 재설정」 신 기능 또는 = 「✏️ 수정」 후 「💲 현재가」!",
    },
}


def run_auto_fix_proposer_once() -> dict:
    """매 5분 = 신 RiskEvent CRITICAL/WARN 조회 + 자동 fix 제안."""
    from app.core.redis_client import get_redis_client
    try:
        redis = get_redis_client()
    except Exception:
        redis = None

    db = SessionLocal()
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "events_found": 0,
        "proposals_sent": 0,
        "details": [],
    }
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
        events = db.execute(
            select(RiskEvent)
            .where(
                and_(
                    RiskEvent.created_at >= cutoff,
                    RiskEvent.severity.in_(["CRITICAL", "WARN"]),
                )
            )
            .order_by(desc(RiskEvent.id))
            .limit(50)
        ).scalars().all()

        result["events_found"] = len(events)

        for e in events:
            # 알려진 fix 매핑 찾기
            fix = None
            for key, proposal in FIX_PROPOSALS.items():
                if key in (e.event_type or ""):
                    fix = proposal
                    break

            if not fix:
                continue
            if _is_dedup(redis, e.id):
                continue
            _mark_dedup(redis, e.id)

            # Strategy 정보
            s = db.execute(
                select(StrategyInstance)
                .where(StrategyInstance.id == e.strategy_instance_id)
            ).scalar_one_or_none()
            sym = s.symbol if s else "?"
            sid = s.id if s else e.strategy_instance_id

            # SSH 명령 = strategy_id 치환
            ssh_cmd = fix.get("ssh_cmd")
            if ssh_cmd:
                ssh_cmd = ssh_cmd.replace("{sid}", str(sid))

            # Telegram 자동 fix 제안!
            try:
                NotificationService(db).send_system_alert(
                    title=f"[자동 fix 제안] #{sid} {sym}",
                    body=(
                        f"silent bug 자동 fix 제안! (v49)\n\n"
                        f"이벤트: {e.event_type}\n"
                        f"심각도: {e.severity}\n\n"
                        f"제안 액션:\n  {fix['action']}\n\n"
                        f"설명:\n  {fix['explain']}\n\n"
                        + (f"SSH 명령:\n```\n{ssh_cmd}```\n" if ssh_cmd else "사장님 UI 에서 직접 액션!\n")
                        + f"\n이 알림 = 2시간 dedup"
                    ),
                )
                result["proposals_sent"] += 1
                result["details"].append({
                    "event_id": e.id,
                    "event_type": e.event_type,
                    "strategy_id": sid,
                    "symbol": sym,
                    "action": fix["action"],
                })
            except Exception as ex:
                logger.error("[auto-fix] 알림 실패: %s", ex)

        if result["proposals_sent"] == 0:
            logger.info("[auto-fix] %d events 조회, fix 제안 = 0", result["events_found"])
        else:
            logger.warning(
                "[auto-fix] %d events / %d proposals",
                result["events_found"], result["proposals_sent"],
            )

    finally:
        db.close()
    return result


if __name__ == "__main__":
    import json
    r = run_auto_fix_proposer_once()
    print(json.dumps(r, indent=2, ensure_ascii=False))
