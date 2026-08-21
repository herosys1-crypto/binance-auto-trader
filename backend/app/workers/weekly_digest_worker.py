"""📆 v213 사장님 (2026-08-21): 매주 월요일 KST 08:00 = 주간 요약!

사장님 요구: 장기 추세 관찰 자율화!

= 일일 요약(v210) + 주간 요약(v213) = 완전 시각화!

로직 (매주 월요일 KST 08:00 = UTC 일요일 23:00!):
1. 지난 7일 자동 진입 합계!
2. 승률/평균 PnL/최고/최악 심볼!
3. 재진입 성공률!
4. Success 재진입 성과!
5. 학습 축적 진행!
6. 청산 원인 분포!
7. 텔레그램 발송!

효과:
- 사장님 = 주간 추세 = 한 눈에!
- 파라미터 조정 근거 데이터!
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.strategy_status import TERMINAL_STATUSES
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_suggestion import StrategySuggestion

logger = logging.getLogger(__name__)


def run_weekly_digest() -> dict:
    """매주 월요일 KST 08:00 = 지난주 요약 발송!"""
    db: Session = SessionLocal()
    try:
        now_utc = datetime.now(timezone.utc)
        # 오늘 KST 00:00 = UTC 어제 15:00
        today_kst_start_utc = (now_utc.replace(hour=15, minute=0, second=0, microsecond=0)
                               - timedelta(days=1))
        # 지난 7일!
        since_utc = today_kst_start_utc - timedelta(days=7)

        report = _build_weekly(db, since_utc, today_kst_start_utc)
        _send_report(db, report)
        return report
    except Exception as e:
        logger.exception("[v213 weekly_digest] 실패: %s", e)
        return {"error": str(e)}
    finally:
        db.close()


def _build_weekly(db: Session, since_utc: datetime, until_utc: datetime) -> dict:
    """지난주 데이터!"""
    # 지난 7일 자동 진입!
    entries = db.execute(
        select(StrategySuggestion)
        .where(StrategySuggestion.created_at >= since_utc)
        .where(StrategySuggestion.created_at < until_utc)
        .where(StrategySuggestion.suggestion_type == "bb4h_auto_entry")
    ).scalars().all()

    total = len(entries)
    success = sum(1 for s in entries if s.outcome_status == "SUCCESS")
    fail = sum(1 for s in entries if s.outcome_status == "FAIL")
    settled = success + fail
    win_rate = round(success / settled * 100, 1) if settled > 0 else 0.0

    # 재진입 통계!
    reentry_1st = [s for s in entries if s.reason and "1차 재진입" in s.reason]
    reentry_2nd = [s for s in entries if s.reason and "2차 재진입" in s.reason]
    success_reentry = [s for s in entries if s.reason and "성공 재진입" in s.reason]

    def _win_rate(rows: list) -> float:
        settled_r = [r for r in rows if r.outcome_status in ("SUCCESS", "FAIL")]
        if not settled_r:
            return 0.0
        wins = sum(1 for r in settled_r if r.outcome_status == "SUCCESS")
        return round(wins / len(settled_r) * 100, 1)

    reentry_1st_win = _win_rate(reentry_1st)
    reentry_2nd_win = _win_rate(reentry_2nd)
    success_reentry_win = _win_rate(success_reentry)

    # 지난 7일 청산!
    closed = db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.stopped_at >= since_utc)
        .where(StrategyInstance.stopped_at < until_utc)
        .where(StrategyInstance.status.in_(list(TERMINAL_STATUSES)))
    ).scalars().all()

    total_pnl = sum(float(s.realized_pnl or 0) for s in closed)
    wins_count = sum(1 for s in closed if float(s.realized_pnl or 0) > 0)
    losses_count = sum(1 for s in closed if float(s.realized_pnl or 0) < 0)
    avg_pnl = total_pnl / len(closed) if closed else 0

    # 심볼별 PnL!
    symbol_pnl: dict[str, float] = {}
    for s in closed:
        pnl = float(s.realized_pnl or 0)
        symbol_pnl[s.symbol] = symbol_pnl.get(s.symbol, 0) + pnl
    top_gainers = sorted(symbol_pnl.items(), key=lambda x: -x[1])[:3]
    top_losers = sorted(symbol_pnl.items(), key=lambda x: x[1])[:3]

    # 청산 원인!
    from app.workers.post_liquidation_analysis_worker import get_post_liquidation_analysis
    post_analysis = get_post_liquidation_analysis(db) or {}

    # 학습 축적!
    from app.workers.pattern_learning_worker import get_learning_insights, get_learning_health_check
    insights = get_learning_insights(db)
    health = get_learning_health_check(db)

    return {
        "since_kst": (since_utc + timedelta(hours=9)).strftime("%Y-%m-%d"),
        "until_kst": (until_utc + timedelta(hours=9)).strftime("%Y-%m-%d"),
        "entries": {
            "total": total, "success": success, "fail": fail,
            "settled": settled, "win_rate_pct": win_rate,
        },
        "reentry": {
            "1st_count": len(reentry_1st), "1st_win_pct": reentry_1st_win,
            "2nd_count": len(reentry_2nd), "2nd_win_pct": reentry_2nd_win,
            "success_reentry_count": len(success_reentry),
            "success_reentry_win_pct": success_reentry_win,
        },
        "pnl": {
            "total_usdt": round(total_pnl, 2),
            "wins": wins_count, "losses": losses_count,
            "total_closed": len(closed),
            "avg_pnl_usdt": round(avg_pnl, 2),
        },
        "top_gainers": [{"symbol": s, "pnl": round(p, 2)} for s, p in top_gainers],
        "top_losers": [{"symbol": s, "pnl": round(p, 2)} for s, p in top_losers],
        "close_reasons_24h": (post_analysis or {}).get("close_reason_counts", {}),
        "learning": {
            "insights_samples": (insights or {}).get("total_samples", 0),
            "learnable_samples_30d": (health or {}).get("totals", {}).get("learnable_samples", 0),
        },
    }


def _send_report(db: Session, report: dict) -> None:
    """텔레그램 발송!"""
    e = report.get("entries", {})
    r = report.get("reentry", {})
    p = report.get("pnl", {})
    lrn = report.get("learning", {})

    pnl_emoji = "🟢" if p.get("total_usdt", 0) >= 0 else "🔴"

    def _fmt_syms(items):
        if not items:
            return "없음"
        return " / ".join(f"{it['symbol']}({it['pnl']:+.1f})" for it in items[:3])

    reason_lines = ""
    reasons = report.get("close_reasons_24h") or {}
    if reasons:
        reason_lines = "\n📊 청산 원인 (24h):\n" + "\n".join(
            f"  - {k}: {v}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])
        )

    body = (
        f"📆 지난주 ({report.get('since_kst')} ~ {report.get('until_kst')}) 매매!\n"
        f"\n"
        f"🎯 자동 진입: {e.get('total',0)}건 ({e.get('win_rate_pct',0)}% 승률)\n"
        f"  성공 {e.get('success',0)} / 실패 {e.get('fail',0)} / 확정 {e.get('settled',0)}\n"
        f"\n"
        f"🔁 재진입:\n"
        f"  1차: {r.get('1st_count',0)}건 ({r.get('1st_win_pct',0)}% 승률)\n"
        f"  2차: {r.get('2nd_count',0)}건 ({r.get('2nd_win_pct',0)}% 승률)\n"
        f"  🚀 Success 재진입: {r.get('success_reentry_count',0)}건 ({r.get('success_reentry_win_pct',0)}% 승률)\n"
        f"\n"
        f"{pnl_emoji} 실 청산 (7일): {p.get('total_usdt',0)} USDT\n"
        f"  {p.get('wins',0)}승 / {p.get('losses',0)}패 / {p.get('total_closed',0)}건\n"
        f"  평균: {p.get('avg_pnl_usdt',0)} USDT/건\n"
        f"\n"
        f"🏆 TOP GAIN: {_fmt_syms(report.get('top_gainers', []))}\n"
        f"💸 TOP LOSS: {_fmt_syms(report.get('top_losers', []))}\n"
        f"{reason_lines}\n"
        f"\n"
        f"🎓 학습: 표본 {lrn.get('insights_samples',0)}건 / 유효 {lrn.get('learnable_samples_30d',0)}건 (30일!)"
    )

    try:
        from app.services.notification_service import NotificationService
        NotificationService(db).send_system_alert(
            title="📆 [v213] 지난주 매매 요약!", body=body,
        )
        logger.info("[v213 weekly_digest] 발송 완료!")
    except Exception as e:
        logger.warning("[v213 weekly_digest] 발송 실패: %s", e)
