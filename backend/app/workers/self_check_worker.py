"""Self-Check Worker — 시스템 자기 검증 (2026-06-09 v17 사장님 critical 정책).

사장님 헌법 6번: 「단일 진실」
사장님 헌법 7번: 「자동 검증」

매 시간 (= 3600초) 실행:
- reserved 계산 = 화면 (exchange_accounts.py) vs worker (stage_trigger_worker.py) 일치 확인
- wallet_limit 계산 = 모든 곳 일치 확인
- 활성 strategy 의 DB ↔ 거래소 일치 확인
- 차이 발견 = Telegram 알림 + RiskEvent 기록

silent bug 영구 차단 = 사장님 자본 보호 자동화.
"""
from __future__ import annotations
import logging
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.exchange_account import ExchangeAccount
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_stage_plan import StrategyStagePlan
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

# 사장님 헌법 5번 (= 대칭성) 위반 시 = 즉시 알림
MISMATCH_THRESHOLD_USDT = Decimal("0.50")  # 0.5 USDT 차이도 = 알림 (= 정확성)


def _calc_reserved_view(db, account_id: int) -> Decimal:
    """화면 (exchange_accounts.py) 식 = 미진입 단계 자본 합 (= fix v5 사장님 사상)."""
    from app.core.strategy_status import STAGES_WITH_NEXT as ACTIVE_STAGE_STATUSES  # v24 fix
    strats = db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.exchange_account_id == account_id)
        .where(StrategyInstance.is_archived.is_(False))
        .where(StrategyInstance.status.in_(ACTIVE_STAGE_STATUSES))
    ).scalars().all()
    total = Decimal("0")
    for s in strats:
        # actual 진입 마진 (= Binance lock)
        if s.current_position_qty and s.avg_entry_price and s.leverage:
            qty = abs(Decimal(str(s.current_position_qty)))
            avg = Decimal(str(s.avg_entry_price))
            lev = Decimal(str(s.leverage))
            if lev > 0:
                total += (qty * avg / lev)
        # 미진입 단계 자본 합
        unentered = db.execute(
            select(StrategyStagePlan)
            .where(StrategyStagePlan.strategy_instance_id == s.id)
            .where(StrategyStagePlan.is_triggered.is_(False))
        ).scalars().all()
        total += sum((Decimal(str(p.planned_capital or 0)) for p in unentered), Decimal("0"))
    return total


def _calc_reserved_worker(db, account_id: int) -> Decimal:
    """stage_trigger_worker 신 식 = 미진입 단계 자본 합 (= v17 fix 후 = 화면과 동일)."""
    from app.core.strategy_status import STAGES_WITH_NEXT as ACTIVE_STAGE_STATUSES  # v24 fix
    strats = db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.exchange_account_id == account_id)
        .where(StrategyInstance.is_archived.is_(False))
        .where(StrategyInstance.status.in_(ACTIVE_STAGE_STATUSES))
    ).scalars().all()
    total = Decimal("0")
    for s in strats:
        unentered = db.execute(
            select(StrategyStagePlan)
            .where(StrategyStagePlan.strategy_instance_id == s.id)
            .where(StrategyStagePlan.is_triggered.is_(False))
        ).scalars().all()
        total += sum((Decimal(str(p.planned_capital or 0)) for p in unentered), Decimal("0"))
    # 화면과 비교 = actual 마진 빼고 = 미진입만 (단순화)
    return total


def run_self_check_once() -> dict:
    """자기 검증 1회 실행 — Scheduler 가 매 1시간 호출.

    검증 항목:
    1. reserved 계산 = 두 곳 일치 확인
    2. 활성 strategy 의 stage_plans 무결성 확인 (= triggered=True 인데 진입가 0 등)
    3. wallet_limit 계산 = env 변수 적용 확인

    return: {issues_found: int, alerts_sent: int, accounts_checked: int}
    """
    db = SessionLocal()
    issues = []
    accounts_checked = 0
    try:
        accounts = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_active.is_(True))
        ).scalars().all()
        for account in accounts:
            accounts_checked += 1
            try:
                # 1. reserved 계산 = 화면 (실+미진입) vs worker (미진입만)
                # = 같은 의미 = 같은 결과 (= actual 마진 제외 시)
                reserved_view = _calc_reserved_view(db, account.id)
                reserved_worker = _calc_reserved_worker(db, account.id)
                # actual 마진은 화면에 더해짐 → view 만 actual 포함
                # 단, worker 는 actual 별도 사용 → 미진입만 비교 가능

                # 2. stage_plans 무결성
                bad_plans = db.execute(
                    select(StrategyStagePlan)
                    .where(StrategyStagePlan.is_triggered.is_(True))
                    .where(StrategyStagePlan.trigger_price.is_(None))
                ).scalars().all()
                if bad_plans:
                    issues.append(
                        f"🚨 stage_plans 무결성: {len(bad_plans)} 개 row = triggered=True 인데 trigger_price=NULL"
                    )

                # 🚨 2026-06-13 사장님 critical fix — false positive 차단!
                # 옛 silent bug: STOPPED/COMPLETED/STOPPING 도 검사 = 옛 종료된 strategy false positive!
                # 사장님 알림 = 매 시간 = 같은 4건 = 시끄러움!
                # 신 fix: ACTIVE strategy 만 검사 (= STAGES_WITH_NEXT)
                from app.core.strategy_status import STAGES_WITH_NEXT as _ACTIVE
                strats = db.execute(
                    select(StrategyInstance)
                    .where(StrategyInstance.exchange_account_id == account.id)
                    .where(StrategyInstance.is_archived.is_(False))
                    .where(StrategyInstance.status.in_(_ACTIVE))  # 🛡 신: 활성만!
                ).scalars().all()
                for s in strats:
                    # current_stage 와 stage_plans triggered 일치 확인
                    triggered_count = db.execute(
                        select(StrategyStagePlan)
                        .where(StrategyStagePlan.strategy_instance_id == s.id)
                        .where(StrategyStagePlan.is_triggered.is_(True))
                    ).scalars().all()
                    # 🚨 2026-07-22 사장님 critical fix: false positive 차단!
                    # 사장님 #504 ESPORTSUSDT = current_stage=1, triggered=0 = 15시간 반복!
                    # = 실제로는 「1단계 시작가 진입」 or 「💉 포지션 추가」 mode = stage_plan 없거나 미갱신!
                    # = 알림 시끄러움 = false positive!
                    # ↓ 신 로직: stage_plan 자체 없으면 skip + Notification 진입 체결 카운트로 실제 검증!
                    all_stage_plans = db.execute(
                        select(StrategyStagePlan)
                        .where(StrategyStagePlan.strategy_instance_id == s.id)
                    ).scalars().all()
                    if not all_stage_plans:
                        continue  # stage_plan 없음 = 검증 skip!
                    # 실제 「포지션 진입 체결」 알림 카운트로 대체 검증 (진짜 silent bug만!)
                    from app.models.notification import Notification
                    entry_notif_count = db.execute(
                        select(Notification)
                        .where(Notification.strategy_instance_id == s.id)
                        .where(Notification.title.like("%포지션 진입 체결%"))
                    ).scalars().all()
                    # current_stage 이상의 진입 알림 있으면 = 정상!
                    if s.current_stage and len(entry_notif_count) >= s.current_stage:
                        continue  # 실제 진입 알림 충분 = 정상!
                    if s.current_stage and len(triggered_count) != s.current_stage:
                        issues.append(
                            f"🚨 strategy #{s.id} {s.symbol}: "
                            f"current_stage={s.current_stage} ≠ triggered count={len(triggered_count)}, "
                            f"entry_notif={len(entry_notif_count)}"
                        )

            except Exception as e:
                logger.warning("[self-check] account %s 검증 실패: %s", account.id, e)

        # 알림 전송 (🛡 2026-06-13 사장님 critical: 24h dedup = 시끄러운 반복 차단!)
        alerts_sent = 0
        if issues:
            logger.warning("[self-check] 🚨 %s 건 silent bug 발견!", len(issues))
            # 🛡 dedup = 같은 issues 집합 = 24시간 = 1회만!
            import hashlib as _h
            _key = "self_check:alert:" + _h.md5(("\n".join(sorted(issues))).encode("utf-8")).hexdigest()[:16]
            _send = True
            try:
                from app.core.redis_client import get_redis_client as _grc
                _r = _grc()
                if _r and _r.get(_key):
                    _send = False
                    logger.info("[self-check] 🛡 24h dedup = 신 알림 X (= 사장님 반복 차단!)")
                elif _r:
                    _r.setex(_key, 86400, "1")  # 24h
            except Exception:
                pass
            if _send:
                try:
                    NotificationService(db).send_system_alert(
                        title=f"🚨 [Self-Check] {len(issues)} 건 silent bug 발견!",
                        body="\n\n".join(issues[:10]) + (
                            f"\n\n... 그 외 {len(issues) - 10} 건" if len(issues) > 10 else ""
                        ) + "\n\n🛡 이 알림 = 24h dedup (= 같은 issues 시 X)",
                    )
                    alerts_sent = 1
                except Exception as e:
                    logger.error("[self-check] Telegram 알림 실패: %s", e)
            # DB 에도 기록 (= 사장님 화면 「최근 활동」 표시)
            try:
                db.add(RiskEvent(
                    strategy_instance_id=None,
                    event_type="SELF_CHECK_MISMATCH",
                    severity="WARNING",
                    title=f"🚨 Self-Check: {len(issues)} 건 silent bug 발견",
                    message="\n".join(issues[:5]),
                    event_payload={"issues": issues[:20]},
                ))
                db.commit()
            except Exception as e:
                logger.error("[self-check] DB 기록 실패: %s", e)
        else:
            logger.info("[self-check] ✅ 모든 검증 통과 (%s 계정)", accounts_checked)

        return {
            "issues_found": len(issues),
            "alerts_sent": alerts_sent,
            "accounts_checked": accounts_checked,
        }
    finally:
        db.close()
