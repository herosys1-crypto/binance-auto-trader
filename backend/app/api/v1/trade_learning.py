"""🎓 Trade Learning API (v134 신!) - 거래 학습 기록 + TP/SL 조정 제안!

사장님 요구 (2026-08-13):
- 모든 거래 학습 저장!
- 심볼 흐름 분석 → TP/SL 조정 제안!
- 사장님이 선택해서 조정!
- 차후 = 자동 조정!
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.crypto import decrypt_text
from app.integrations.binance.client import BinanceClient
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_template import StrategyTemplate
from app.models.trade_learning_record import TradeLearningRecord

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/trade-learning", tags=["trade-learning"])


# --- 학습 기록 ---
@router.get("/records")
def list_records(
    limit: int = 50,
    status: str | None = None,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[dict]:
    """학습 기록 리스트 (최신 순!)"""
    q = select(TradeLearningRecord).order_by(TradeLearningRecord.updated_at.desc())
    if status:
        q = q.where(TradeLearningRecord.status == status.upper())
    rows = db.execute(q.limit(limit)).scalars().all()
    return [
        {
            "id": r.id,
            "strategy_instance_id": r.strategy_instance_id,
            "symbol": r.symbol,
            "side": r.side,
            "status": r.status,
            "entry_price": str(r.entry_price or 0),
            "exit_price": str(r.exit_price or 0),
            "pnl_pct": float(r.pnl_pct or 0),
            "max_profit_pct": float(r.max_profit_pct or 0),
            "max_loss_pct": float(r.max_loss_pct or 0),
            "close_reason": r.close_reason,
            "insights": r.insights,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


@router.get("/prediction-stats")
def prediction_stats(
    days: int = 30,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🎓 예측 학습 통계! (사장님 요구!)

    - 최근 N일 예측 성공률!
    - 심볼별 TOP 성공률!
    - side별 성공률!
    """
    from app.models.strategy_suggestion import StrategySuggestion
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(StrategySuggestion)
        .where(StrategySuggestion.created_at >= cutoff)
        .where(StrategySuggestion.outcome_status.in_(["SUCCESS", "FAIL", "PENDING", "EXPIRED"]))
    ).scalars().all()

    total = len(rows)
    pending = sum(1 for r in rows if r.outcome_status == "PENDING")
    success = sum(1 for r in rows if r.outcome_status == "SUCCESS")
    fail = sum(1 for r in rows if r.outcome_status == "FAIL")
    expired = sum(1 for r in rows if r.outcome_status == "EXPIRED")
    judged = success + fail

    # side별!
    long_success = sum(1 for r in rows if r.side == "LONG" and r.outcome_status == "SUCCESS")
    long_fail = sum(1 for r in rows if r.side == "LONG" and r.outcome_status == "FAIL")
    short_success = sum(1 for r in rows if r.side == "SHORT" and r.outcome_status == "SUCCESS")
    short_fail = sum(1 for r in rows if r.side == "SHORT" and r.outcome_status == "FAIL")

    # 심볼별 성공률!
    sym_stats: dict[str, dict] = {}
    for r in rows:
        if r.outcome_status not in ("SUCCESS", "FAIL"):
            continue
        s = sym_stats.setdefault(r.symbol, {"total": 0, "wins": 0})
        s["total"] += 1
        if r.outcome_status == "SUCCESS":
            s["wins"] += 1

    top_symbols = []
    bottom_symbols = []
    for sym, stats in sym_stats.items():
        if stats["total"] < 2:
            continue
        rate = round((stats["wins"] / stats["total"]) * 100, 1)
        entry = {"symbol": sym, "count": stats["total"], "wins": stats["wins"], "rate": rate}
        top_symbols.append(entry)
    top_symbols.sort(key=lambda x: x["rate"], reverse=True)
    bottom_symbols = list(reversed(top_symbols[-10:])) if len(top_symbols) > 10 else []
    top_symbols = top_symbols[:10]

    return {
        "days": days,
        "total": total,
        "pending": pending,
        "success": success,
        "fail": fail,
        "expired": expired,
        "judged": judged,
        "success_rate": round((success / judged * 100), 1) if judged else 0,
        "long_success": long_success,
        "long_fail": long_fail,
        "long_success_rate": round(long_success / (long_success + long_fail) * 100, 1) if (long_success + long_fail) else 0,
        "short_success": short_success,
        "short_fail": short_fail,
        "short_success_rate": round(short_success / (short_success + short_fail) * 100, 1) if (short_success + short_fail) else 0,
        "top_symbols": top_symbols,
        "bottom_symbols": bottom_symbols,
    }


@router.post("/prediction-outcome/run-now")
def run_outcome_now(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🎓 예측 outcome = 지금 즉시 실행! (사장님 편의!)"""
    from app.workers.prediction_outcome_worker import run_prediction_outcome
    return run_prediction_outcome()


@router.get("/insights")
def learning_insights(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🧠 학습 인사이트 (Learning Team 결과 조회!)"""
    import json
    from app.models.system_setting import SystemSetting
    row = db.get(SystemSetting, "learning_agent_insights")
    if not row or not row.value:
        return {
            "generated_at": None,
            "insights": [],
            "top_trade_symbols": [],
            "top_pred_symbols": [],
            "big_moves_missed": [],
            "trail_late_count": 0,
        }
    try:
        return json.loads(row.value)
    except Exception:
        return {"error": "parse failed"}


@router.post("/learning-cycle/run-now")
def run_learning_cycle_now(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🎓 Learning Team = 지금 즉시 실행!"""
    from app.agents.learning_team.team_lead import LearningTeamLead
    return LearningTeamLead().run_learning_cycle(db, days=30)


@router.get("/summary")
def learning_summary(
    days: int = 30,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """학습 통계 (최근 N일!)"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(TradeLearningRecord)
        .where(TradeLearningRecord.status == "CLOSED")
        .where(TradeLearningRecord.updated_at >= cutoff)
    ).scalars().all()

    total = len(rows)
    wins = sum(1 for r in rows if (r.pnl_pct or 0) > 0)
    losses = sum(1 for r in rows if (r.pnl_pct or 0) < 0)
    breakeven = total - wins - losses
    total_pnl = sum(float(r.pnl_pct or 0) for r in rows)
    avg_pnl = total_pnl / total if total else 0

    # 심볼별 통계!
    symbol_stats: dict[str, dict[str, float]] = {}
    for r in rows:
        s = symbol_stats.setdefault(r.symbol, {"count": 0, "wins": 0, "total_pnl": 0})
        s["count"] += 1
        if (r.pnl_pct or 0) > 0:
            s["wins"] += 1
        s["total_pnl"] += float(r.pnl_pct or 0)

    top_symbols = sorted(
        symbol_stats.items(),
        key=lambda x: x[1]["total_pnl"],
        reverse=True,
    )[:10]

    return {
        "days": days,
        "total": total,
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "win_rate": round((wins / total * 100), 2) if total else 0,
        "total_pnl_pct": round(total_pnl, 2),
        "avg_pnl_pct": round(avg_pnl, 2),
        "top_symbols": [
            {
                "symbol": sym,
                "count": stats["count"],
                "win_rate": round((stats["wins"] / stats["count"] * 100), 2),
                "total_pnl_pct": round(stats["total_pnl"], 2),
            }
            for sym, stats in top_symbols
        ],
    }


# --- TP/SL 조정 제안 ---
@router.get("/tp-sl-advisor/scan")
def tp_sl_advisor(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🎯 활성 전략 = TP/SL 조정 제안!

    - 심볼 흐름 분석 (RSI, BB, 변동!)
    - TP/SL 조정 제안 = 사장님 선택!
    """
    # Binance client!
    account = db.execute(
        select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
    ).scalar_one_or_none()
    if not account:
        return {"suggestions": [], "error": "no mainnet account"}

    bc = BinanceClient(
        api_key=decrypt_text(account.api_key_enc),
        api_secret=decrypt_text(account.api_secret_enc),
        is_testnet=False,
    )

    # 활성 전략 조회!
    open_statuses = [
        "STAGE_1_OPEN", "STAGE_2_OPEN", "STAGE_3_OPEN",
        "STAGE_4_OPEN", "STAGE_5_OPEN", "STAGE_6_OPEN",
        "STAGE_7_OPEN", "STAGE_8_OPEN", "STAGE_9_OPEN",
        "STAGE_10_OPEN",
    ]
    active = db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.status.in_(open_statuses))
        .where(StrategyInstance.current_position_qty != 0)
    ).scalars().all()

    suggestions = []
    for s in active:
        try:
            # 심볼 5분 klines!
            k5 = bc.get_klines(symbol=s.symbol, interval="5m", limit=3)
            change_5m = None
            if isinstance(k5, list) and len(k5) >= 2:
                o = float(k5[-2][1])
                c = float(k5[-2][4])
                if o > 0:
                    change_5m = round(((c - o) / o) * 100, 2)

            # 5분 = 이번 트레이드 방향과 반대? = 조정 고려!
            pnl = float(s.unrealized_pnl_pct or 0)
            max_profit = float(s.max_profit_pct or 0) if s.max_profit_pct is not None else 0

            proposals = []

            # LONG + 5분 -3% = TP 하향 (빨리 청산!)
            if s.side == "LONG" and change_5m is not None and change_5m < -2:
                proposals.append({
                    "kind": "TP_DOWN",
                    "reason": f"⚠️ 5분 {change_5m}% 하락 감지! TP1을 낮춰서 = 빠른 익절 검토!",
                    "action": "TP1 임계값 낮추기 (예: 25% → 20%)",
                })
            # SHORT + 5분 +3% = TP 상향 = SHORT 청산 앞당김!
            if s.side == "SHORT" and change_5m is not None and change_5m > 2:
                proposals.append({
                    "kind": "TP_UP",
                    "reason": f"⚠️ 5분 +{change_5m}% 반등 감지! TP1을 낮춰서 = 빠른 익절 검토!",
                    "action": "TP1 임계값 낮추기 (예: 25% → 20%)",
                })

            # 최대 수익 > 20% + 현재 손실 = 트레일링 SL 강화!
            if max_profit >= 20 and pnl < max_profit - 10:
                proposals.append({
                    "kind": "TRAIL_STRENGTHEN",
                    "reason": f"📉 피크 +{max_profit:.1f}%에서 하락! 트레일링 강화 검토!",
                    "action": "Trailing SL 좁히기 (예: -15% → -10%)",
                })

            # 손실 > -20% = SL 완화 or 청산!
            if pnl < -20:
                proposals.append({
                    "kind": "SL_REVIEW",
                    "reason": f"🚨 손실 {pnl:.1f}% = 청산 or 홀드 결정 필요!",
                    "action": "긴급 청산 or 추가 진입 검토!",
                })

            if not proposals:
                continue

            suggestions.append({
                "strategy_id": s.id,
                "symbol": s.symbol,
                "side": s.side,
                "status": s.status,
                "pnl_pct": pnl,
                "max_profit_pct": max_profit,
                "change_5m": change_5m,
                "proposals": proposals,
            })
        except Exception as e:
            logger.warning("[tp_sl_advisor] %s 실패: %s", s.symbol, e)
            continue

    return {"suggestions": suggestions, "total": len(suggestions)}
