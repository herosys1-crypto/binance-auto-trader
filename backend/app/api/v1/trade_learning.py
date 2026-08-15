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
from app.core.risk_constants import ACTION_PNL_PCT_DEFAULT
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


@router.post("/prediction-outcome/recompute")
def recompute_outcomes(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """🚨 v156 사장님 지시: 「10%이상 수익만 성공」 = 전체 재계산!
    옛 1.5% 기준 판정 → 신 10% 기준으로 SUCCESS/FAIL 재판정!
    """
    from app.workers.prediction_outcome_worker import recompute_all_outcomes
    return recompute_all_outcomes()


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


@router.get("/setup-stats")
def setup_stats(
    days: int = 90,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """📐☁️🤝 셋업 등급별 실제 승률! (v137 → v138 확장!)

    사장님 사상 (2026-08-14):
      "남의 매매법도 우리 데이터로 검증해서 쓴다!"

    - 진입 시 저장된 entry_context의 등급을 종료된 거래의 실제 손익과 대조!
      · `grades`      = 📐 EMA/VCP (돌파형) 등급별
      · `sar_grades`  = ☁️ SAR/구름대 (추세추종형) 등급별
      · `confluence`  = 🤝 두 전략 합의 수준별  ← 「같이 적용」의 검증 지표!
      · `flags`       = 개별 조건별 (어떤 조건이 실제로 돈이 됐나?)

    등급 없는 옛 기록 = 집계 제외 (= no_context 개수로만 표시!)
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(TradeLearningRecord)
        .where(TradeLearningRecord.status == "CLOSED")
        .where(TradeLearningRecord.updated_at >= cutoff)
    ).scalars().all()

    def _bucket() -> dict[str, Any]:
        return {"count": 0, "wins": 0, "total_pnl": 0.0, "best": None, "worst": None}

    by_grade: dict[str, dict[str, Any]] = {}
    by_sar_grade: dict[str, dict[str, Any]] = {}
    by_confluence: dict[str, dict[str, Any]] = {}
    by_bb_top: dict[str, dict[str, Any]] = {}
    by_pump: dict[str, dict[str, Any]] = {}
    by_bb4h: dict[str, dict[str, Any]] = {}
    by_flag: dict[str, dict[str, Any]] = {}
    no_context = 0

    for r in rows:
        entry = r.entry_context or {}
        ctx = entry.get("ema_vcp") or {}
        sctx = entry.get("sar_ichimoku") or {}
        cctx = entry.get("confluence") or {}
        bctx = entry.get("bb_top") or {}

        has_ema = bool(ctx.get("available") and ctx.get("grade"))
        has_sar = bool(sctx.get("available") and sctx.get("grade"))
        has_bb = bool(bctx.get("available") and bctx.get("grade"))
        if not has_ema and not has_sar and not has_bb:
            no_context += 1
            continue

        pnl = float(r.pnl_pct or 0)

        def _add(target: dict[str, Any]) -> None:
            target["count"] += 1
            target["total_pnl"] += pnl
            if pnl > 0:
                target["wins"] += 1
            if target["best"] is None or pnl > target["best"]:
                target["best"] = pnl
            if target["worst"] is None or pnl < target["worst"]:
                target["worst"] = pnl

        if has_ema:
            _add(by_grade.setdefault(ctx["grade"], _bucket()))
            # 📐 조건별 = 어떤 조건이 실제로 돈이 됐나?
            for key, on in [
                ("trend_ok", ctx.get("trend_ok")),
                ("aligned_1h", ctx.get("aligned_1h")),
                ("vcp_contracting", ctx.get("vcp_contracting")),
                ("volume_dry", ctx.get("volume_dry")),
                ("breakout_closed", ctx.get("breakout_closed")),
                ("volume_spike", ctx.get("volume_spike")),
                ("first_rally_only", ctx.get("first_rally_only")),
            ]:
                _add(by_flag.setdefault(f"{key}={'Y' if on else 'N'}", _bucket()))

        if has_sar:
            _add(by_sar_grade.setdefault(sctx["grade"], _bucket()))
            # ☁️ 조건별!
            for key, on in [
                ("cloud_4h_ok", sctx.get("cloud_4h_ok")),
                ("cloud_1h_ok", sctx.get("cloud_1h_ok")),
                ("cloud_1h_ideal", sctx.get("cloud_1h_ideal")),
                ("cloud_15m_ok", sctx.get("cloud_15m_ok")),
                ("sar_aligned", sctx.get("sar_aligned")),
                ("sar_fresh_flip", sctx.get("sar_fresh_flip")),
            ]:
                _add(by_flag.setdefault(f"{key}={'Y' if on else 'N'}", _bucket()))

        if cctx.get("available") and cctx.get("level"):
            _add(by_confluence.setdefault(cctx["level"], _bucket()))

        # 📉 v143: 4H BB 중단 이탈 상태
        b4 = entry.get("bb_4h") or {}
        if b4.get("available") and b4.get("grade"):
            _add(by_bb4h.setdefault(f"{b4.get('cross','?')}_{b4['grade']}", _bucket()))

        # ⚡ v141: 급등락 실시간 진입 (진입 당시 급등 중이었나?)
        pctx = entry.get("pump_dump") or {}
        if pctx.get("available") and pctx.get("kind"):
            _add(by_pump.setdefault(
                f"{pctx['kind']}_{pctx.get('grade', '?')}", _bucket()))
            _add(by_flag.setdefault(
                f"pump_live={'Y' if pctx.get('side') else 'N'}", _bucket()))

        # 🔺 v140: 15m 천장/바닥 (사장님 주력 전략!)
        if has_bb:
            _add(by_bb_top.setdefault(bctx["grade"], _bucket()))
            for key, on in [
                ("div_rsi", bctx.get("div_rsi")),
                ("div_macd", bctx.get("div_macd")),
                ("div_obv", bctx.get("div_obv")),
                ("bb_touch", bctx.get("bb_touch")),
                ("wick", bctx.get("wick")),
            ]:
                _add(by_flag.setdefault(f"{key}={'Y' if on else 'N'}", _bucket()))
            nd = bctx.get("div_count")
            if nd is not None:
                _add(by_bb_top.setdefault(f"div{nd}", _bucket()))

    def _finish(bucket: dict[str, Any]) -> dict[str, Any]:
        cnt = bucket["count"]
        return {
            "count": cnt,
            "wins": bucket["wins"],
            "win_rate": round(bucket["wins"] / cnt * 100, 1) if cnt else 0,
            "avg_pnl_pct": round(bucket["total_pnl"] / cnt, 2) if cnt else 0,
            "best_pnl_pct": bucket["best"],
            "worst_pnl_pct": bucket["worst"],
        }

    grades = {g: _finish(by_grade[g]) for g in sorted(by_grade)}
    sar_grades = {g: _finish(by_sar_grade[g]) for g in sorted(by_sar_grade)}
    confluence = {k: _finish(by_confluence[k]) for k in sorted(by_confluence)}
    bb_top_grades = {k: _finish(by_bb_top[k]) for k in sorted(by_bb_top)}
    pump_stats = {k: _finish(by_pump[k]) for k in sorted(by_pump)}
    bb4h_stats = {k: _finish(by_bb4h[k]) for k in sorted(by_bb4h)}
    flags = {k: _finish(by_flag[k]) for k in sorted(by_flag)}

    # --- 사장님용 한 줄 결론들! (표본 10건 미만 = 판정 금지!) ---
    MIN_SAMPLE = 10
    verdicts: list[str] = []

    def _compare(label: str, table: dict, hi: str, lo: str) -> None:
        total = sum(v["count"] for v in table.values())
        if total < MIN_SAMPLE:
            return
        a = table.get(hi, {}).get("avg_pnl_pct")
        d = table.get(lo, {}).get("avg_pnl_pct")
        if a is not None and d is not None:
            verdicts.append(
                f"{label} {hi} 평균 {a:+.1f}% vs {lo} 평균 {d:+.1f}% "
                + ("= 유효! ✅" if a > d else "= 효과 불확실! ⚠️")
            )
        elif a is not None:
            verdicts.append(f"{label} {hi} 평균 {a:+.1f}% (비교군 {lo} 표본 없음!)")

    _compare("📐 EMA/VCP", grades, "A", "D")
    _compare("☁️ SAR/구름대", sar_grades, "A", "D")
    _compare("🔺 15m 천장(v140)", bb_top_grades, "S", "D")
    # 🤝 합의 검증 = 「같이 적용」이 실제로 이득이었나?
    conf_total = sum(v["count"] for v in confluence.values())
    if conf_total >= MIN_SAMPLE:
        agree = confluence.get("STRONG_AGREE") or confluence.get("AGREE")
        clash = confluence.get("CONFLICT")
        if agree and clash:
            verdicts.append(
                f"🤝 합의 평균 {agree['avg_pnl_pct']:+.1f}% vs 충돌 평균 {clash['avg_pnl_pct']:+.1f}% "
                + ("= **두 전략 같이 보는 게 이득!** ✅" if agree["avg_pnl_pct"] > clash["avg_pnl_pct"]
                   else "= 합의 효과 아직 불확실! ⚠️")
            )
        elif agree:
            verdicts.append(f"🤝 합의 평균 {agree['avg_pnl_pct']:+.1f}% (충돌 표본 없음!)")

    graded_total = sum(v["count"] for v in grades.values())
    sar_total = sum(v["count"] for v in sar_grades.values())
    if not verdicts:
        verdicts.append(
            f"📊 표본 부족 = 더 쌓아야 판정 가능! "
            f"(EMA/VCP {graded_total}건 / SAR {sar_total}건 / 합의 {conf_total}건, 최소 {MIN_SAMPLE}건 필요)"
        )

    return {
        "days": days,
        "min_sample": MIN_SAMPLE,
        "graded_total": graded_total,
        "sar_total": sar_total,
        "confluence_total": conf_total,
        "no_context": no_context,
        "grades": grades,
        "sar_grades": sar_grades,
        "confluence": confluence,
        "bb_top_grades": bb_top_grades,
        "pump_dump_stats": pump_stats,
        "bb_4h_stats": bb4h_stats,
        "flags": flags,
        "verdict": verdicts[0],
        "verdicts": verdicts,
    }


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
            # v147: 액션 기본 임계 = -5% (사장님 지시, 단일 상수)
            if pnl <= ACTION_PNL_PCT_DEFAULT:
                proposals.append({
                    "kind": "SL_REVIEW",
                    "reason": (f"🔔 손실 {pnl:.1f}% = 액션 기준"
                               f"({ACTION_PNL_PCT_DEFAULT:.0f}%) 도달!"),
                    "action": "청산 / 홀드 / 추가 진입 결정 필요!",
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
