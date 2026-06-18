"""TP Miss Detector Worker — TP 단계 도달 + 자동 진입 X = critical 감지! (v57)

🌟 사장님 critical 사상 (2026-06-18):
> "결과 좋은 게 문제가 아니야! 이런 문제가 없어야 해!"
> "실제 수익은 이것보다 더 많았어야 했어!"

= 사장님 ESPORTSUSDT #182 = TP1 후 TP2/TP3 도달 = But 시스템 자동 X!
= 외부 청산 = 잔여 익절 손실!

검증 (매 2분):
1. 활성 strategy = TP_DONE_PARTIAL 상태!
2. 다음 TP 트리거 도달 (= ROI %)
3. 자동 진입 X = grace 5분 초과 = CRITICAL!

= 사장님 자율 청산 회피 전략 = 영구 보호!
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, desc

from app.core.database import SessionLocal
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_template import StrategyTemplate
from app.models.position import Position
from app.models.risk_event import RiskEvent
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

_DEDUP_KEY = "tp_miss:strategy:{sid}:level:{level}"
_DEDUP_TTL = 600  # 10분

# TP 도달 후 = N분 안에 자동 진입 = 안 되면 = critical!
TP_AUTO_GRACE_MINUTES = 5

# TP 단계 매핑
TP_DONE_LEVELS = {
    "TP1_DONE_PARTIAL": 1,
    "TP2_DONE_PARTIAL": 2,
    "TP3_DONE_PARTIAL": 3,
    "TP4_DONE_PARTIAL": 4,
    "TP5_DONE_PARTIAL": 5,
}


def _is_dedup(redis, sid, level):
    if not redis:
        return False
    try:
        return bool(redis.get(_DEDUP_KEY.format(sid=sid, level=level)))
    except Exception:
        return False


def _mark_dedup(redis, sid, level):
    if not redis:
        return
    try:
        redis.setex(_DEDUP_KEY.format(sid=sid, level=level), _DEDUP_TTL, "1")
    except Exception:
        pass


def run_tp_miss_detector_once() -> dict:
    """매 2분 = TP 단계 도달 + 자동 진입 X = critical 감지!"""
    from app.core.redis_client import get_redis_client
    try:
        redis = get_redis_client()
    except Exception:
        redis = None

    db = SessionLocal()
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "total_checked": 0,
        "miss_found": 0,
        "alerts_sent": 0,
    }
    try:
        # TP_DONE_PARTIAL 상태 strategy 조회
        strats = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.is_archived.is_(False))
            .where(StrategyInstance.status.in_(list(TP_DONE_LEVELS.keys())))
        ).scalars().all()
        result["total_checked"] = len(strats)

        for s in strats:
            current_tp_level = TP_DONE_LEVELS.get(s.status or "", 0)
            if current_tp_level <= 0:
                continue

            # 마지막 mark_price 조회
            p = db.execute(
                select(Position)
                .where(Position.strategy_instance_id == s.id)
                .order_by(desc(Position.id))
                .limit(1)
            ).scalar_one_or_none()
            mark = p.mark_price if p else None
            if not mark or not s.avg_entry_price or not s.leverage:
                continue

            mark_d = Decimal(str(mark))
            avg_d = Decimal(str(s.avg_entry_price))
            lev_d = Decimal(str(s.leverage))
            if avg_d <= 0:
                continue

            # ROI 계산
            if s.side == "LONG":
                price_pct = (mark_d - avg_d) / avg_d * Decimal("100")
            else:  # SHORT
                price_pct = (avg_d - mark_d) / avg_d * Decimal("100")
            roi = price_pct * lev_d

            # 다음 TP 트리거 % 조회 (template 또는 사장님 override)
            tpl = db.get(StrategyTemplate, s.strategy_template_id) if s.strategy_template_id else None
            if not tpl:
                continue
            next_tp_level = current_tp_level + 1
            next_tp_pct = getattr(tpl, f"tp{next_tp_level}_percent", None)
            if not next_tp_pct:
                continue  # 다음 TP = 미설정 = OK

            next_tp_pct_d = Decimal(str(next_tp_pct))

            # 도달 검증: ROI >= 다음 TP %!
            if roi < next_tp_pct_d:
                continue  # 미도달 = OK

            # 도달 + grace period 초과 = CRITICAL!
            try:
                ref_time = s.updated_at
                if ref_time and ref_time.tzinfo is None:
                    ref_time = ref_time.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                if ref_time and (now - ref_time) < timedelta(minutes=TP_AUTO_GRACE_MINUTES):
                    continue  # grace = skip
            except Exception:
                pass

            # CRITICAL = TP 누락!
            result["miss_found"] += 1
            if _is_dedup(redis, s.id, next_tp_level):
                continue
            _mark_dedup(redis, s.id, next_tp_level)

            try:
                msg = (
                    f"🚨 #{s.id} {s.symbol} TP{next_tp_level} 누락 silent bug 의심!\n\n"
                    f"📊 ROI: {roi:.2f}% (= TP{next_tp_level} 임계 {next_tp_pct_d}% 도달!)\n"
                    f"📐 평단: {avg_d}, 현재가: {mark_d}\n"
                    f"⚙️ status: {s.status} (= TP{current_tp_level} 완료 + TP{next_tp_level} 미발동!)\n\n"
                    f"💡 사장님 확인 권장:\n"
                    f"   1. scheduler 작동 상태?\n"
                    f"   2. orchestrator log 확인!\n"
                    f"   3. 사장님 = 「💰 수동 익절」 가능!\n\n"
                    f"= 사장님 이익 보호! 즉시 인지!"
                )
                db.add(RiskEvent(
                    strategy_instance_id=s.id,
                    event_type="TP_MISS_DETECTED",
                    severity="CRITICAL",
                    title=f"🚨 [TP 누락 의심] #{s.id} {s.symbol} TP{next_tp_level}",
                    message=msg,
                    event_payload={
                        "strategy_id": s.id,
                        "current_tp_level": current_tp_level,
                        "next_tp_level": next_tp_level,
                        "roi": str(roi),
                        "next_tp_pct": str(next_tp_pct_d),
                        "avg_entry": str(avg_d),
                        "mark_price": str(mark_d),
                    },
                ))
                db.commit()
                NotificationService(db).send_system_alert(
                    title=f"🚨 [TP 누락 의심] #{s.id} {s.symbol} TP{next_tp_level}",
                    body=msg,
                )
                result["alerts_sent"] += 1
                logger.warning("[tp-miss] #%s %s TP%s 도달 But 미발동!", s.id, s.symbol, next_tp_level)
            except Exception as e:
                logger.error("[tp-miss] 알림 실패 #%s: %s", s.id, e)

        if result["miss_found"] == 0:
            logger.info("[tp-miss] %d strategy = 모든 TP 정상!", result["total_checked"])
        else:
            logger.warning("[tp-miss] %d miss in %d, alerts=%d", result["miss_found"], result["total_checked"], result["alerts_sent"])
    finally:
        db.close()
    return result


if __name__ == "__main__":
    import json
    r = run_tp_miss_detector_once()
    print(json.dumps(r, indent=2, ensure_ascii=False))
