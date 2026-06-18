"""Liquidation Risk Worker — 사장님 Liquidation 사전 알림! (v58)

🚨 사장님 critical 사건 (2026-06-19):
사장님 SYNUSDT = Liquidation = -585 USDT 손실!
= SL -100% = Liquidation 보다 먼저 발동 X = silent bug!

= 신 fix: ROI -70% 도달 = critical 사전 알림!
= 사장님 = 즉시 「수동 익절」 or 「증거금 추가」 가능!
= 사장님 자본 영구 보호!
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, desc

from app.core.database import SessionLocal
from app.core.strategy_status import STAGES_WITH_NEXT
from app.models.strategy_instance import StrategyInstance
from app.models.position import Position
from app.models.risk_event import RiskEvent
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

_DEDUP_KEY = "liq_risk:strategy:{sid}"
_DEDUP_TTL = 600  # 10분 dedup

# 사장님 critical: ROI -70% 도달 = 사전 알림!
LIQUIDATION_RISK_ROI_THRESHOLD = Decimal("-70")


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


def run_liquidation_risk_once() -> dict:
    """매 1분 = Liquidation 위험 사전 알림!"""
    from app.core.redis_client import get_redis_client
    try:
        redis = get_redis_client()
    except Exception:
        redis = None

    db = SessionLocal()
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "total_checked": 0,
        "warnings": 0,
        "alerts_sent": 0,
    }
    try:
        strats = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.is_archived.is_(False))
            .where(StrategyInstance.status.in_(STAGES_WITH_NEXT))
        ).scalars().all()
        result["total_checked"] = len(strats)

        for s in strats:
            if not s.avg_entry_price or not s.leverage or not s.current_position_qty:
                continue
            if abs(float(s.current_position_qty)) == 0:
                continue
            # 마지막 mark_price
            p = db.execute(
                select(Position)
                .where(Position.strategy_instance_id == s.id)
                .order_by(desc(Position.id))
                .limit(1)
            ).scalar_one_or_none()
            mark = p.mark_price if p else None
            if not mark:
                continue

            avg_d = Decimal(str(s.avg_entry_price))
            mark_d = Decimal(str(mark))
            lev_d = Decimal(str(s.leverage))
            if avg_d <= 0:
                continue

            # ROI 계산
            if s.side == "LONG":
                price_pct = (mark_d - avg_d) / avg_d * Decimal("100")
            else:  # SHORT
                price_pct = (avg_d - mark_d) / avg_d * Decimal("100")
            roi = price_pct * lev_d

            # ROI <= -70% = 위험!
            if roi > LIQUIDATION_RISK_ROI_THRESHOLD:
                continue

            result["warnings"] += 1
            if _is_dedup(redis, s.id):
                continue
            _mark_dedup(redis, s.id)

            try:
                msg = (
                    f"🚨 #{s.id} {s.symbol} {s.side} Liquidation 위험 사전 알림!\n\n"
                    f"📊 현재 ROI: {roi:.2f}% (= 위험 임계 -70% 도달!)\n"
                    f"📐 평단: {avg_d}, 현재가: {mark_d}\n"
                    f"⚙️ 단계: {s.current_stage}, qty: {s.current_position_qty}\n\n"
                    f"⚠️ 가격 + 약 +15~25% 변동 시 = Liquidation 가능!\n\n"
                    f"💡 사장님 권장 (= 자본 보호!):\n"
                    f"   1. 「💰 수동 익절」 = 손실 확정 + 자본 일부 회수!\n"
                    f"   2. 「💉 증거금 추가」 = 청산가 멀리 + 안전 마진!\n"
                    f"   3. 「💉 포지션 추가」 = 평단 개선 (= 추가 위험 인지!)\n\n"
                    f"= 사장님 자본 보호 = 즉시 결정!"
                )
                db.add(RiskEvent(
                    strategy_instance_id=s.id,
                    event_type="LIQUIDATION_RISK_ALERT",
                    severity="CRITICAL",
                    title=f"🚨 [Liquidation 위험] #{s.id} {s.symbol} ROI {roi:.2f}%",
                    message=msg,
                    event_payload={
                        "strategy_id": s.id,
                        "roi": str(roi),
                        "avg_entry": str(avg_d),
                        "mark_price": str(mark_d),
                        "side": s.side,
                    },
                ))
                db.commit()
                NotificationService(db).send_system_alert(
                    title=f"🚨 [Liquidation 위험] #{s.id} {s.symbol} ROI {roi:.2f}%",
                    body=msg,
                )
                result["alerts_sent"] += 1
                logger.warning("[liq-risk] #%s %s ROI %.2f%% = 위험!", s.id, s.symbol, float(roi))
            except Exception as e:
                logger.error("[liq-risk] 알림 실패 #%s: %s", s.id, e)

        if result["warnings"] == 0:
            logger.info("[liq-risk] %d strategy = 모든 ROI 안전!", result["total_checked"])
        else:
            logger.warning("[liq-risk] %d 위험 in %d, alerts=%d", result["warnings"], result["total_checked"], result["alerts_sent"])
    finally:
        db.close()
    return result


if __name__ == "__main__":
    import json
    r = run_liquidation_risk_once()
    print(json.dumps(r, indent=2, ensure_ascii=False))
