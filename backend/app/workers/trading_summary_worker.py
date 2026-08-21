"""📊 v210 사장님 (2026-08-21): 매일 KST 08:00 = 어제 자동 매매 요약!

사장님 요구: "학습이 잘되고 있는지도 검증!" + 관찰 자율화!

⚠️ daily_report_worker.py = 이미 존재 (Layer 3 = 운영 시스템 요약, KST 09:00!)
= 이 워커 = **매매 데이터 요약 전용!** (KST 08:00 = 별도!)

로직 (매일 KST 08:00 = UTC 23:00 전날!):
1. 어제 자동 진입 = 카운트!
2. 승률 (SUCCESS / SUCCESS+FAIL)!
3. 재진입 (1차/2차) 카운트 + 결과!
4. Success 재진입 카운트!
5. 학습 인사이트 = 신선도!
6. 오늘 TOP 심볼 (가장 성공률 높은!) + WORST!
7. 텔레그램 발송!

효과:
- 사장님 = 매일 아침 요약 = 완전 자율!
- 실 매매 결과 = 한 눈에!
- 관찰 시간 = 대폭 절약!
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


def run_trading_summary() -> dict:
    """매일 KST 08:00 = 어제 매매 요약 발송!"""
    db: Session = SessionLocal()
    try:
        # 어제 = KST 자정 → UTC 전전날 15:00 ~ 전날 15:00 (KST 00:00 ~ 24:00)
        now_utc = datetime.now(timezone.utc)
        # 오늘 KST 00:00 = UTC 어제 15:00
        today_kst_start_utc = (now_utc.replace(hour=15, minute=0, second=0, microsecond=0)
                               - timedelta(days=1))
        yesterday_kst_start_utc = today_kst_start_utc - timedelta(days=1)

        report = _build_report(db, yesterday_kst_start_utc, today_kst_start_utc)
        _send_report(db, report)
        return report
    except Exception as e:
        logger.exception("[v210 trading_summary] 실패: %s", e)
        return {"error": str(e)}
    finally:
        db.close()


def _build_report(db: Session, since_utc: datetime, until_utc: datetime) -> dict:
    """어제 매매 요약 데이터 빌드!"""
    # 어제 자동 진입 = bb4h_auto_entry!
    yesterday_entries = db.execute(
        select(StrategySuggestion)
        .where(StrategySuggestion.created_at >= since_utc)
        .where(StrategySuggestion.created_at < until_utc)
        .where(StrategySuggestion.suggestion_type == "bb4h_auto_entry")
    ).scalars().all()

    total = len(yesterday_entries)
    success = sum(1 for s in yesterday_entries if s.outcome_status == "SUCCESS")
    fail = sum(1 for s in yesterday_entries if s.outcome_status == "FAIL")
    pending = sum(1 for s in yesterday_entries if s.outcome_status in (None, "PENDING"))
    settled = success + fail
    win_rate = round(success / settled * 100, 1) if settled > 0 else 0.0

    # LONG/SHORT 분포!
    long_count = sum(1 for s in yesterday_entries if s.side == "LONG")
    short_count = sum(1 for s in yesterday_entries if s.side == "SHORT")

    # 재진입 카운트! (reason에서 감지!)
    reentry_1st = sum(1 for s in yesterday_entries if s.reason and "1차 재진입" in s.reason)
    reentry_2nd = sum(1 for s in yesterday_entries if s.reason and "2차 재진입" in s.reason)
    success_reentry = sum(1 for s in yesterday_entries if s.reason and "성공 재진입" in s.reason)

    # 어제 청산된 실 전략 = 실현 PnL!
    closed_yesterday = db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.stopped_at >= since_utc)
        .where(StrategyInstance.stopped_at < until_utc)
        .where(StrategyInstance.status.in_(list(TERMINAL_STATUSES)))
    ).scalars().all()

    total_pnl = sum(float(s.realized_pnl or 0) for s in closed_yesterday)
    pnl_wins = sum(1 for s in closed_yesterday if float(s.realized_pnl or 0) > 0)
    pnl_losses = sum(1 for s in closed_yesterday if float(s.realized_pnl or 0) < 0)

    # 학습 인사이트!
    from app.workers.pattern_learning_worker import get_learning_insights, get_learning_health_check
    insights = get_learning_insights(db)
    health = get_learning_health_check(db)

    top_long = (insights.get("top_symbols_long", [])[:3]) if insights else []
    top_short = (insights.get("top_symbols_short", [])[:3]) if insights else []
    worst_long = (insights.get("worst_symbols_long", [])[:3]) if insights else []
    worst_short = (insights.get("worst_symbols_short", [])[:3]) if insights else []

    return {
        "since_kst": (since_utc + timedelta(hours=9)).strftime("%Y-%m-%d"),
        "until_kst": (until_utc + timedelta(hours=9)).strftime("%Y-%m-%d"),
        "auto_entries": {
            "total": total,
            "success": success, "fail": fail, "pending": pending,
            "settled": settled, "win_rate_pct": win_rate,
            "long": long_count, "short": short_count,
            "reentry_1st": reentry_1st, "reentry_2nd": reentry_2nd,
            "success_reentry": success_reentry,
        },
        "realized_pnl": {
            "total_usdt": round(total_pnl, 2),
            "wins": pnl_wins, "losses": pnl_losses,
            "total_closed": len(closed_yesterday),
        },
        "learning": {
            "insights_samples": (insights or {}).get("total_samples", 0),
            "insights_age_h": (health or {}).get("insights_state", {}).get("age_hours"),
            "learnable_samples_30d": (health or {}).get("totals", {}).get("learnable_samples", 0),
        },
        "top": {"long": top_long, "short": top_short},
        "worst": {"long": worst_long, "short": worst_short},
    }


def _send_report(db: Session, report: dict) -> None:
    """텔레그램 발송!"""
    e = report.get("auto_entries", {})
    p = report.get("realized_pnl", {})
    lrn = report.get("learning", {})
    top = report.get("top", {})
    worst = report.get("worst", {})

    pnl_emoji = "🟢" if p.get("total_usdt", 0) >= 0 else "🔴"
    win_emoji = "🏆" if e.get("win_rate_pct", 0) >= 60 else ("⚖️" if e.get("win_rate_pct", 0) >= 40 else "⚠️")

    def _fmt_syms(items):
        if not items:
            return "없음"
        return " / ".join(
            f"{it.get('symbol','?')}({int((it.get('success_rate',0))*100)}%,{it.get('total',0)}건)"
            for it in items[:3]
        )

    body = (
        f"📅 어제 ({report.get('since_kst')} KST) 매매 요약!\n"
        f"\n"
        f"🎯 자동 진입: {e.get('total',0)}건 (LONG {e.get('long',0)} / SHORT {e.get('short',0)})\n"
        f"{win_emoji} 승률: {e.get('win_rate_pct',0)}% ({e.get('success',0)}승 / {e.get('fail',0)}패 / {e.get('pending',0)}대기)\n"
        f"\n"
        f"🔁 재진입: 1차 {e.get('reentry_1st',0)}건 / 2차 {e.get('reentry_2nd',0)}건\n"
        f"🚀 Success 재진입: {e.get('success_reentry',0)}건\n"
        f"\n"
        f"{pnl_emoji} 실 청산: {p.get('total_usdt',0)} USDT ({p.get('wins',0)}승 / {p.get('losses',0)}패 / {p.get('total_closed',0)}건)\n"
        f"\n"
        f"🎓 학습 (30일):\n"
        f"  - 표본 {lrn.get('insights_samples',0)}건 / 유효 {lrn.get('learnable_samples_30d',0)}건\n"
        f"  - insights 신선도: {lrn.get('insights_age_h','X')}h\n"
        f"\n"
        f"🏆 TOP LONG: {_fmt_syms(top.get('long', []))}\n"
        f"🏆 TOP SHORT: {_fmt_syms(top.get('short', []))}\n"
        f"🚨 WORST LONG (skip!): {_fmt_syms(worst.get('long', []))}\n"
        f"🚨 WORST SHORT (skip!): {_fmt_syms(worst.get('short', []))}\n"
    )
    try:
        from app.services.notification_service import NotificationService
        ns = NotificationService(db)
        ns.send_system_alert(title="📊 [v210] 어제 매매 요약!", body=body)
        logger.info("[v210 trading_summary] 발송 완료!")
    except Exception as e:
        logger.warning("[v210 trading_summary] 발송 실패: %s", e)
