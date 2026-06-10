"""Trade Anomaly Monitor — 사장님 거래 실시간 자동 분석 worker (v20).

사장님 critical 사상: "왜 이런 일이 일어나면 안 되는 부분이잖아"
= TP/SL 청산 silent bug = 영원히 X = 거래 직후 자동 분석 + 알림.

핵심 동작 (매 5분):
1. 최근 5분 RiskEvent (= event_type=TP_EXECUTION_AUDIT) 조회
2. severity=CRITICAL = 즉시 Telegram 알림 (1시간 dedup)
3. severity=WARN = 누적 (= 5건 이상 = 알림)

= 사장님 자본 보호 = silent bug 자동 차단 시스템.

작성: 2026-06-10 (사장님 VELVETUSDT TP1 전량 청산 silent bug 사례 직후)
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, and_

from app.core.database import SessionLocal
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

# 알림 dedup (= Redis TTL 1시간)
_ALERT_DEDUP_KEY = "trade_anomaly_alert:event:{eid}"
_ALERT_DEDUP_TTL = 3600  # 1시간


def _is_alert_sent(redis_client, event_id: int) -> bool:
    if redis_client is None:
        return False
    try:
        return bool(redis_client.get(_ALERT_DEDUP_KEY.format(eid=event_id)))
    except Exception:
        return False


def _mark_alert_sent(redis_client, event_id: int) -> None:
    if redis_client is None:
        return
    try:
        redis_client.setex(_ALERT_DEDUP_KEY.format(eid=event_id), _ALERT_DEDUP_TTL, "1")
    except Exception:
        pass


def run_trade_anomaly_monitor_once() -> dict:
    """매 5분: 최근 거래 분석 + 비정상 패턴 즉시 알림.

    분석 대상:
    1. TP_EXECUTION_AUDIT RiskEvent (= tp_sl_orchestrator 가 매 청산 시 기록)
       - severity CRITICAL (= 의도 vs 실제 차이 > 20%) → 즉시 Telegram
       - severity WARN (= 차이 > 5%) → 5건 이상 누적 시 알림

    사장님 사상: silent bug = 거래 직후 = 자동 분석 + 사장님 즉시 인지.
    """
    from app.core.redis_client import get_redis_client
    try:
        redis = get_redis_client()
    except Exception:
        redis = None

    db = SessionLocal()
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "critical_count": 0,
        "warn_count": 0,
        "alerts_sent": 0,
        "events": [],
    }
    try:
        # 최근 5분 (= cycle 간격) + 약간 버퍼 = 10분 조회
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
        events = db.execute(
            select(RiskEvent)
            .where(
                and_(
                    RiskEvent.event_type == "TP_EXECUTION_AUDIT",
                    RiskEvent.created_at >= cutoff,
                    RiskEvent.severity.in_(["CRITICAL", "WARN"]),
                )
            )
            .order_by(RiskEvent.created_at.desc())
        ).scalars().all()

        for event in events:
            payload = event.event_payload or {}
            level = payload.get("level", "?")
            expected_pct = payload.get("expected_pct", 0)
            actual_pct = payload.get("actual_pct", 0)
            pct_diff = payload.get("pct_diff", 0)
            current_stage = payload.get("current_stage", 0)

            if event.severity == "CRITICAL":
                result["critical_count"] += 1
            else:
                result["warn_count"] += 1

            result["events"].append({
                "event_id": event.id,
                "strategy_id": event.strategy_instance_id,
                "severity": event.severity,
                "level": level,
                "expected_pct": expected_pct,
                "actual_pct": actual_pct,
                "pct_diff": pct_diff,
            })

            # CRITICAL = 즉시 Telegram (1시간 dedup)
            if event.severity == "CRITICAL" and not _is_alert_sent(redis, event.id):
                strategy = db.execute(
                    select(StrategyInstance).where(StrategyInstance.id == event.strategy_instance_id)
                ).scalar_one_or_none()
                symbol = strategy.symbol if strategy else "?"
                side = strategy.side if strategy else "?"

                try:
                    NotificationService(db).send_system_alert(
                        title=f"🚨 [TP 청산 silent bug 가능성!] #{event.strategy_instance_id} {symbol} {side} {level}",
                        body=(
                            f"🔥 사장님 critical = TP 청산 silent bug 가능성 자동 감지!\n\n"
                            f"📊 분석 결과:\n"
                            f"  • strategy: #{event.strategy_instance_id} {symbol} {side}\n"
                            f"  • TP level: {level}\n"
                            f"  • current_stage: {current_stage}\n"
                            f"  • 의도 청산 %: {expected_pct:.2f}%\n"
                            f"  • 실제 청산 %: {actual_pct:.2f}% ⚠️\n"
                            f"  • 차이: {pct_diff:.2f}% (= CRITICAL 임계 20% 초과!)\n\n"
                            f"💡 사장님 조치:\n"
                            f"  • 거래 내역 확인: 「전략 인스턴스」 카드\n"
                            f"  • 진단: /api/v1/admin/diagnostic/strategy-history/{event.strategy_instance_id}\n"
                            f"  • 의심 시: 신 PR 검증 또는 code review 요청\n\n"
                            f"⚠️ 이 알림 = 1시간 dedup (= spam 차단)\n"
                            f"📌 RiskEvent ID: {event.id}"
                        ),
                    )
                    _mark_alert_sent(redis, event.id)
                    result["alerts_sent"] += 1
                    logger.warning(
                        "[trade-anomaly] CRITICAL Telegram sent: strategy=%s level=%s diff=%.2f%%",
                        event.strategy_instance_id, level, pct_diff,
                    )
                except Exception as e:
                    logger.error("[trade-anomaly] Telegram send 실패: %s", e)

        # WARN 누적 알림 (= 5건 이상 시)
        if result["warn_count"] >= 5:
            try:
                NotificationService(db).send_system_alert(
                    title=f"⚠️ [TP 청산 audit WARN 누적] 최근 10분 {result['warn_count']}건",
                    body=(
                        f"⚠️ 사장님 검토 권장 = TP 청산 의도 vs 실제 차이 누적!\n\n"
                        f"📊 누적: {result['warn_count']}건 (= 5건 이상)\n"
                        f"📌 임계: 차이 5% 초과 (= CRITICAL 20% 보다 작음)\n\n"
                        f"💡 사장님 조치:\n"
                        f"  • 진단: 신 RiskEvent 검토 (= 화면 우측 위 종)\n"
                        f"  • 패턴 분석 = 코드 검증 권장"
                    ),
                )
                logger.warning("[trade-anomaly] WARN 누적 알림 발송 (%d건)", result["warn_count"])
            except Exception as e:
                logger.error("[trade-anomaly] WARN 누적 Telegram 실패: %s", e)

        if result["critical_count"] == 0 and result["warn_count"] == 0:
            logger.info("[trade-anomaly] ✅ 최근 5분 = 비정상 거래 0건 (= 모두 정상)")
        else:
            logger.warning(
                "[trade-anomaly] 최근 10분: CRITICAL=%d WARN=%d 알림=%d",
                result["critical_count"], result["warn_count"], result["alerts_sent"],
            )

    finally:
        db.close()
    return result


if __name__ == "__main__":
    # 수동 실행 (= 디버깅)
    import json
    r = run_trade_anomaly_monitor_once()
    print(json.dumps(r, indent=2, ensure_ascii=False))
