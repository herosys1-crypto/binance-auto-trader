"""🛡️ v215 사장님 (2026-08-21): 일일 손실 한도 감시 + 자동 진입 중단!

사장님 실 자금 = 절대 보호!

= 일일 손실 임계값 초과 시 = 신규 자동 진입 = 즉시 중단!
= 텔레그램 알림!
= 다음 KST 자정 = 자동 리셋!

로직 (매 15분!):
1. 오늘 KST (00:00~24:00) 청산된 자동 진입 = realized_pnl 합계!
2. 초기 자본 대비 손실률 계산!
3. -3% 초과 = Redis kill switch ON!
4. -5% 초과 = CRITICAL 알림!
5. 다음 KST 자정 = 자동 리셋!

효과:
- 사장님 = 실 자금 = 완전 보호!
- 급격한 손실 = 즉시 방어!
- 회복 시간 확보!

⚠️ 수동 진입 = 영향 X (자동만 중단!)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.strategy_status import TERMINAL_STATUSES
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_suggestion import StrategySuggestion

logger = logging.getLogger(__name__)

# 임계값!
DRAWDOWN_WARN_PCT = -3.0    # -3% = 진입 중단!
DRAWDOWN_CRITICAL_PCT = -5.0  # -5% = CRITICAL 알림!
BASE_CAPITAL_USDT = 1000.0   # 기준 자본 (사장님 조정 가능!)

REDIS_KEY = "v215:auto_entry_killed"
REDIS_TTL_SEC = 3600 * 24  # 24시간!

_LAST_ALERT_LEVEL: str | None = None
_LAST_ALERT_AT: datetime | None = None


def run_drawdown_guardian() -> dict:
    """매 15분 = 손실 한도 감시!"""
    db: Session = SessionLocal()
    try:
        # 오늘 KST 자정 이후 = UTC 어제 15:00부터!
        now_utc = datetime.now(timezone.utc)
        today_kst_start_utc = _today_kst_start_utc(now_utc)

        # 오늘 청산된 자동 진입!
        closed_today = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.stopped_at >= today_kst_start_utc)
            .where(StrategyInstance.status.in_(list(TERMINAL_STATUSES)))
        ).scalars().all()

        # bb4h_auto_entry로 시작된 것만!
        auto_entry_ids = set()
        auto_entries = db.execute(
            select(StrategySuggestion)
            .where(StrategySuggestion.created_at >= today_kst_start_utc - timedelta(days=1))
            .where(StrategySuggestion.suggestion_type == "bb4h_auto_entry")
            .where(StrategySuggestion.executed_strategy_id.isnot(None))
        ).scalars().all()
        for s in auto_entries:
            auto_entry_ids.add(s.executed_strategy_id)

        auto_closed = [s for s in closed_today if s.id in auto_entry_ids]

        total_pnl = sum(float(s.realized_pnl or 0) for s in auto_closed)
        pnl_pct = (total_pnl / BASE_CAPITAL_USDT) * 100 if BASE_CAPITAL_USDT > 0 else 0

        # 임계값 판단!
        killed = False
        alert_level = None
        if pnl_pct <= DRAWDOWN_CRITICAL_PCT:
            alert_level = "CRITICAL"
            killed = True
        elif pnl_pct <= DRAWDOWN_WARN_PCT:
            alert_level = "WARN"
            killed = True

        # Redis kill switch!
        _set_kill_switch(killed, pnl_pct)

        # 알림 (레벨 변경 시!)
        if alert_level:
            _alert_if_needed(db, alert_level, pnl_pct, total_pnl, len(auto_closed))

        result = {
            "checked_at": now_utc.isoformat(),
            "today_closed_auto": len(auto_closed),
            "total_pnl_usdt": round(total_pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "kill_switch_active": killed,
            "alert_level": alert_level,
        }
        logger.info(
            "[v215 drawdown] pnl=%.2f USDT (%.2f%%) killed=%s",
            total_pnl, pnl_pct, killed,
        )
        return result
    except Exception as e:
        logger.warning("[v215 drawdown_guardian] 실행 실패: %s", e)
        return {"error": str(e)}
    finally:
        db.close()


def _today_kst_start_utc(now_utc: datetime) -> datetime:
    """오늘 KST 자정 = UTC 어제 15:00!"""
    # KST = UTC+9. UTC now → KST now → KST 오늘 자정 → UTC 변환.
    kst_now = now_utc + timedelta(hours=9)
    kst_today_start = kst_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return (kst_today_start - timedelta(hours=9)).replace(tzinfo=timezone.utc)


def _set_kill_switch(killed: bool, pnl_pct: float) -> None:
    """Redis kill switch!"""
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        if killed:
            r.setex(REDIS_KEY, REDIS_TTL_SEC, f"KILLED:{pnl_pct:.2f}")
        else:
            r.delete(REDIS_KEY)
    except Exception as e:
        logger.warning("[v215] Redis kill switch 실패: %s", e)


def is_auto_entry_killed() -> tuple[bool, str | None]:
    """auto_bb_breakdown_worker에서 호출! = kill 상태 체크!"""
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        val = r.get(REDIS_KEY)
        if val:
            if isinstance(val, bytes):
                val = val.decode()
            return True, val
        return False, None
    except Exception:
        return False, None


def _alert_if_needed(db: Session, level: str, pnl_pct: float, total_pnl: float, count: int) -> None:
    """레벨 변경 시 알림 (30분 dedup!)"""
    global _LAST_ALERT_LEVEL, _LAST_ALERT_AT
    now = datetime.now(timezone.utc)
    # 같은 레벨 30분 내 = skip!
    if (_LAST_ALERT_LEVEL == level and _LAST_ALERT_AT and
        (now - _LAST_ALERT_AT).total_seconds() < 1800):
        return

    emoji = "🚨" if level == "CRITICAL" else "⚠️"
    title = f"{emoji} [v215] 일일 손실 한도 = {level}!"
    body = (
        f"{emoji} 오늘 자동 진입 손실 = {pnl_pct:.2f}%!\n"
        f"\n"
        f"💸 총 손실: {total_pnl} USDT ({count}건 청산)\n"
        f"📊 기준 자본: {BASE_CAPITAL_USDT} USDT\n"
        f"\n"
        f"🛡️ 신규 자동 진입 = 중단!\n"
        f"⏰ 다음 KST 자정 = 자동 재개!\n"
        f"\n"
        f"⚠️ 수동 진입은 정상 가능!"
    )
    try:
        from app.services.notification_service import NotificationService
        NotificationService(db).send_system_alert(title=title, body=body)
        _LAST_ALERT_LEVEL = level
        _LAST_ALERT_AT = now
    except Exception as e:
        logger.warning("[v215] 알림 실패: %s", e)
