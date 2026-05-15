"""운영 점검 — 거래중 이벤트/오류를 한눈에 확인.

사용 (PowerShell):
  # 최근 24시간 요약
  docker compose exec api python scripts/health_check.py --hours 24

  # 지금 즉시 시스템 상태 (컨테이너 / 연결 / Active 일치)
  docker compose exec api python scripts/health_check.py --now

  # 7일 trend (장기 추이 비교)
  docker compose exec api python scripts/health_check.py --hours 168

기획: 1인 운영자가 매일 1~2분으로 「오늘 문제 있었나?」 빠른 점검.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

# scripts/ 에서 실행할 때 app 모듈 import 경로 보장 (/app 이 cwd 일 때 상대 경로 보강)
_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import desc, func, select

from app.core.crypto import decrypt_text
from app.core.database import SessionLocal
from app.integrations.binance.client import BinanceClient
from app.models.exchange_account import ExchangeAccount
from app.models.notification import Notification
from app.models.order import Order
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance


# 알려진 「정상이지만 자주 발생」 이벤트 — 통계엔 표시하되 「검토 필요」 분류 제외
_BENIGN_EVENT_TYPES = {
    "ORDER_TRADE_UPDATE",  # 매칭 안 된 stream 이벤트 (수동 거래 등)
    "ZOMBIE_ORPHAN_RACE_DEFERRED",  # 안전망 작동 (KS 차단) — 정상
    "RECONCILE_RECOVERED_PENDING",  # 자가 회복 — 정상
    "RECONCILE_AUTO_STOP_ORPHAN",  # 외부 청산 정리 — 정상
    "RECONCILE_STOPPING_ZOMBIE_CLEANUP",  # 좀비 정리 — 정상
}


def _emoji(severity: str) -> str:
    return {
        "CRITICAL": "🔴",
        "ERROR": "🟠",
        "WARN": "🟡",
        "INFO": "🟢",
    }.get(severity, "⚪")


def cmd_recent(hours: int) -> None:
    """최근 N시간 이벤트 + 거래 통계 요약."""
    db = SessionLocal()
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        period_label = f"최근 {hours}시간" if hours < 168 else f"최근 {hours // 24}일"

        print(f"\n{'=' * 60}")
        print(f"  운영 점검 — {period_label}")
        print(f"  ({since.strftime('%Y-%m-%d %H:%M')} UTC ~ 현재)")
        print(f"{'=' * 60}\n")

        # ---- 거래 활동 ----
        entry_count = db.execute(
            select(func.count(Order.id))
            .where(Order.purpose == "ENTRY")
            .where(Order.status == "FILLED")
            .where(Order.created_at >= since)
        ).scalar() or 0
        exit_count = db.execute(
            select(func.count(Order.id))
            .where(Order.purpose == "EXIT")
            .where(Order.status == "FILLED")
            .where(Order.created_at >= since)
        ).scalar() or 0
        new_strategies = db.execute(
            select(func.count(StrategyInstance.id))
            .where(StrategyInstance.created_at >= since)
        ).scalar() or 0

        print(f"📊 거래 활동")
        print(f"  • 신규 strategy:   {new_strategies}건")
        print(f"  • 진입 체결:       {entry_count}건")
        print(f"  • 청산 체결:       {exit_count}건")

        # ---- 텔레그램 알림 ----
        notif_total = db.execute(
            select(func.count(Notification.id)).where(Notification.created_at >= since)
        ).scalar() or 0
        notif_failed = db.execute(
            select(func.count(Notification.id))
            .where(Notification.created_at >= since)
            .where(Notification.send_status != "SENT")
        ).scalar() or 0
        print(f"\n📡 텔레그램 알림")
        print(f"  • 발송:           {notif_total}건")
        print(f"  • 실패:           {notif_failed}건  {'⚠️' if notif_failed else '✅'}")

        # ---- 위험 이벤트 — 심각도별 ----
        events = db.execute(
            select(RiskEvent)
            .where(RiskEvent.created_at >= since)
            .order_by(desc(RiskEvent.id))
        ).scalars().all()

        sev_counts: Counter[str] = Counter()
        type_counts: Counter[str] = Counter()
        action_needed: list[RiskEvent] = []
        for e in events:
            sev_counts[e.severity] += 1
            type_counts[e.event_type] += 1
            if e.severity in ("CRITICAL", "ERROR") and e.event_type not in _BENIGN_EVENT_TYPES:
                action_needed.append(e)

        print(f"\n⚠️ 위험 이벤트 ({len(events)}건 전체)")
        for sev in ("CRITICAL", "ERROR", "WARN", "INFO"):
            cnt = sev_counts.get(sev, 0)
            if cnt > 0:
                print(f"  {_emoji(sev)} {sev:8s}: {cnt:3d}건")
        if not events:
            print(f"  ✅ 이벤트 없음")

        # ---- 검토 필요 (CRITICAL/ERROR 중 정상 이벤트 제외) ----
        if action_needed:
            print(f"\n🚨 검토 필요 ({len(action_needed)}건)")
            for e in action_needed[:10]:
                ts = e.created_at.strftime("%m-%d %H:%M")
                sid = f"#{e.strategy_instance_id}" if e.strategy_instance_id else "-"
                print(f"  {ts}  {_emoji(e.severity)} {sid:6s} {e.event_type[:30]:30s}")
                print(f"          {e.title[:75]}")
            if len(action_needed) > 10:
                print(f"  ... +{len(action_needed) - 10}건 더 (자세히는 dashboard 에서)")
        else:
            print(f"\n🚨 검토 필요   ✅ 0건 — 운영 정상")

        # ---- 빈도 높은 이벤트 (top 5) ----
        if type_counts:
            print(f"\n📋 이벤트 빈도 top 5")
            for et, cnt in type_counts.most_common(5):
                marker = "  (정상)" if et in _BENIGN_EVENT_TYPES else ""
                print(f"  {cnt:3d}건  {et}{marker}")

        # ---- 패턴 감지 권장 ----
        recommendations = []
        rate_limit_count = (
            type_counts.get("POSITION_RECONCILE_FAILED", 0)
            + type_counts.get("POSITION_RECONCILE_ERROR", 0)
        )
        if rate_limit_count >= 3:
            recommendations.append(
                f"⚙️ Reconcile 실패 패턴 ({rate_limit_count}회) — Binance API rate limit 가능성, "
                "reconcile_worker 주기 확인 권장"
            )
        orphan_count = type_counts.get("ZOMBIE_ORPHAN_EXCHANGE_POSITION", 0)
        if orphan_count >= 5:
            recommendations.append(
                f"🚨 Orphan 감지 반복 ({orphan_count}회) — 같은 사고 cascade 가능성, "
                "거래소 직접 확인 + 정리 후 KS 해제"
            )
        qty_mismatch = type_counts.get("POSITION_QTY_MISMATCH", 0)
        if qty_mismatch >= 3:
            recommendations.append(
                f"⚖️ DB↔거래소 수량 mismatch ({qty_mismatch}회) — 부분 체결 처리 검토"
            )
        if sev_counts.get("CRITICAL", 0) > 0:
            recommendations.append("🚨 CRITICAL 이벤트 발생 — 즉시 상세 확인")
        if notif_failed > 0:
            recommendations.append(f"📱 텔레그램 발송 실패 {notif_failed}건 — 토큰/네트워크 확인")
        if recommendations:
            print(f"\n💡 권장 조치")
            for r in recommendations:
                print(f"  {r}")
        else:
            print(f"\n💡 권장 조치   없음 — 그대로 운영")

        print(f"\n{'=' * 60}\n")
    finally:
        db.close()


def cmd_now() -> None:
    """현재 시점 시스템 건강 즉시 진단."""
    db = SessionLocal()
    try:
        print(f"\n{'=' * 60}")
        print(f"  운영 점검 — 즉시 진단 ({datetime.now().strftime('%H:%M:%S')})")
        print(f"{'=' * 60}\n")

        # ---- 1. DB 연결 ----
        try:
            db.execute(select(func.count(StrategyInstance.id))).scalar()
            print(f"🟢 DB 연결           OK")
        except Exception as e:
            print(f"🔴 DB 연결           FAIL — {e}")

        # ---- 2. Active strategy vs 거래소 포지션 매칭 ----
        from app.core.strategy_status import TERMINAL_STATUSES
        active = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.status.notin_(TERMINAL_STATUSES))
            .where(StrategyInstance.is_archived.is_(False))
        ).scalars().all()
        active_with_position = [s for s in active if s.current_position_qty and abs(Decimal(str(s.current_position_qty))) > 0]
        print(f"🟢 Active strategy   {len(active)}건 (포지션 보유 {len(active_with_position)}건)")

        # ---- 3. 거래소 포지션 ↔ DB 1:1 매칭 검증 ----
        accounts = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_active.is_(True))
        ).scalars().all()
        for acc in accounts:
            try:
                client = BinanceClient(
                    api_key=decrypt_text(acc.api_key_enc),
                    api_secret=decrypt_text(acc.api_secret_enc),
                    is_testnet=acc.is_testnet,
                )
                risk = client.get_position_risk()
                if isinstance(risk, dict):
                    risk = [risk]
                exchange_positions = [
                    p for p in risk
                    if Decimal(str(p.get("positionAmt", "0"))) != 0
                ]
                env = "testnet" if acc.is_testnet else "mainnet"
                print(f"🟢 거래소 #{acc.id} ({env})  포지션 {len(exchange_positions)}개")

                # mismatch 확인
                db_pairs = {(s.symbol, s.side): s for s in active_with_position if s.exchange_account_id == acc.id}
                ex_pairs = {(p.get("symbol"), p.get("positionSide")): p for p in exchange_positions}
                only_db = set(db_pairs.keys()) - set(ex_pairs.keys())
                only_ex = set(ex_pairs.keys()) - set(db_pairs.keys())
                if only_db:
                    print(f"  🟡 DB 만 있음:   {sorted(only_db)}")
                if only_ex:
                    print(f"  🔴 거래소 만:    {sorted(only_ex)}  ← orphan 후보!")
                if not only_db and not only_ex:
                    print(f"  ✅ DB ↔ 거래소  완벽 일치")
            except Exception as e:
                msg = str(e)[:80]
                if "418" in msg or "1003" in msg:
                    print(f"🔴 거래소 #{acc.id}    Binance API 차단 중 — {msg}")
                else:
                    print(f"🔴 거래소 #{acc.id}    조회 실패 — {msg}")

        # ---- 4. 최근 5분 CRITICAL/ERROR ----
        since_5m = datetime.now(timezone.utc) - timedelta(minutes=5)
        recent_severe = db.execute(
            select(RiskEvent)
            .where(RiskEvent.created_at >= since_5m)
            .where(RiskEvent.severity.in_(["CRITICAL", "ERROR"]))
            .where(RiskEvent.event_type.notin_(_BENIGN_EVENT_TYPES))
        ).scalars().all()
        if recent_severe:
            print(f"\n🚨 최근 5분 CRITICAL/ERROR ({len(recent_severe)}건)")
            for e in recent_severe[:5]:
                print(f"  {e.created_at.strftime('%H:%M:%S')}  {_emoji(e.severity)} {e.event_type}")
                print(f"          {e.title[:75]}")
        else:
            print(f"\n✅ 최근 5분 CRITICAL/ERROR  없음")

        # ---- 5. 오늘 누적 손익 ----
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        from sqlalchemy import and_
        # realized_pnl 변동된 strategy 만
        all_today = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.updated_at >= today_start)
        ).scalars().all()
        # realized 합 — 오늘 만든 strategy 의 전체 realized
        # (정확한 일일 손익은 daily_loss_aggregator 가 별도 추적; 여기선 간이값)
        unrealized_total = sum(Decimal(str(s.unrealized_pnl or 0)) for s in active_with_position)
        print(f"\n💰 손익 (current snapshot)")
        print(f"  • 미실현 (보유 {len(active_with_position)}건): {unrealized_total:.2f} USDT")
        all_realized = db.execute(
            select(func.sum(StrategyInstance.realized_pnl))
        ).scalar() or Decimal("0")
        print(f"  • 누적 실현 (전체):                {all_realized:.2f} USDT")

        print(f"\n{'=' * 60}\n")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="운영 점검 — 거래중 이벤트/오류 확인")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--hours", type=int, metavar="N",
        help="최근 N시간 요약 (예: --hours 24)",
    )
    group.add_argument(
        "--now", action="store_true",
        help="현재 시점 즉시 진단",
    )
    args = parser.parse_args()
    if args.now:
        cmd_now()
    elif args.hours:
        cmd_recent(args.hours)


if __name__ == "__main__":
    sys.exit(main())
