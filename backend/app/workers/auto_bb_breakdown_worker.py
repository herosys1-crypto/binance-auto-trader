"""🤖 AutoBBBreakdownWorker = BB 이탈 SUSTAINED 자동 진입! (v174 사장님 완성!)

사장님 지시 (2026-08-18):
- 1일 5개 (조절 옵션!)
- 손실난 것 = 진입 수량에서 빼기 (카운트!)
- 익절 = 다시 수량 회복! (카운트 X!)
- BB 이탈 SUSTAINED 심볼 = 성공률 85%+ = 자동 진입!

로직 (매 4시간!):
- system_settings 「auto_bb_break_daily_limit」 확인!
- 0 = OFF (수동만!)
- 1+ = 하루 최대 N개 = 자동 진입!
- 카운터 = 활성+손절 (익절 제외!) = v163 로직!
- SUSTAINED (3봉+ 지속 이탈!) + 성공률 85%+ 만!
- 이미 활성 심볼 = 제외!
- 사장님 default profile = template + strategy 자동 생성!
- StrategySuggestion 저장 (자동 진입 표시!)
- 텔레그램 알림!
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_suggestion import StrategySuggestion
from app.models.strategy_template import StrategyTemplate
from app.models.symbol import Symbol
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

# 🎯 v179 사장님 (2026-08-19): 실패 확률 낮추기 = 다중 필터 강화!
# 사장님 지시: "실패확율을 더 낮춰야 해!"
# 이력:
#   v174 (2026-08-18): MIN_SUCCESS_PROBABILITY = 0.85 (BB 자동 진입 시작!)
#   v176 (2026-08-19): 손실 심볼 24h 블록 + 심볼 성공률 30% 필터!
#   v179 (2026-08-19): 모든 필터 강화! (사장님 「더 낮춰야」!)
MIN_SUCCESS_PROBABILITY = 0.80  # v179: 0.85→0.90 / v194: 0.90→0.80 (진입 증가!)
MIN_SYMBOL_SUCCESS_RATE = 0.40  # 0.30 → 0.40 (10%p 상향!)
LOSS_BLOCKLIST_HOURS = 48  # 24 → 48 (2배 확대!)
MIN_SUSTAINED_BARS = 5  # 3 → 5 (지속 확실!)
# v179 신: regime 필수!
REQUIRED_REGIMES = {
    "SHORT": {"DOWNTREND_STRONG"},  # SHORT = 확실한 하락만!
    "LONG": {"UPTREND"},  # LONG = 확실한 상승만!
}
# v179 신: RSI 안전 범위!
RSI_SAFE_RANGE = {
    "SHORT": (30, 70),  # SHORT: RSI 30~70 (과매도 반등 X, 과매수는 진입 시점!)
    "LONG": (30, 70),  # LONG: RSI 30~70 (과매수 조정 X, 과매도는 진입 시점!)
}


def run_auto_bb_breakdown() -> dict:
    """매 4시간 = SUSTAINED 심볼 자동 진입! (v174 완성!)"""
    db: Session = SessionLocal()
    entered = 0
    skipped = 0
    results: list[dict] = []
    try:
        # 1. daily_limit 확인!
        limit_row = db.get(SystemSetting, "auto_bb_break_daily_limit")
        daily_limit = int(limit_row.value) if limit_row and limit_row.value else 0
        if daily_limit <= 0:
            return {"note": "auto_bb_break_daily_limit=0 (OFF!)", "entered": 0}

        # 2. 카운터 (v163: 활성 + 손절 = 카운트, 익절 = 제외!)
        used = _count_used_slots(db)
        remaining = daily_limit - used
        if remaining <= 0:
            return {
                "note": f"오늘 사용 {used}/{daily_limit} (활성+손절, 익절 제외!)",
                "entered": 0,
            }

        # 3. SUSTAINED 스캔 (SHORT + LONG!)
        from app.api.v1.bb_middle_scan import scan_bb_breakdown
        try:
            scan_short = scan_bb_breakdown(
                interval="4h", direction="down", max_symbols=100,
                db=db, user_id=1,
            )
            scan_long = scan_bb_breakdown(
                interval="4h", direction="up", max_symbols=100,
                db=db, user_id=1,
            )
        except Exception as e:
            logger.warning("[auto_bb_breakdown] BB 스캔 실패: %s", e)
            scan_short = {"sustained": []}
            scan_long = {"sustained": []}

        all_sustained: list[dict] = []
        for it in (scan_short.get("sustained") or []):
            all_sustained.append({**it, "side": "SHORT", "source": "BB_SUSTAINED"})
        for it in (scan_long.get("sustained") or []):
            all_sustained.append({**it, "side": "LONG", "source": "BB_SUSTAINED"})

        # 🎯 v190 사장님: MTA (Multi-Timeframe) 소스 추가!
        # 사장님 지시: "MTA 잘 활용해서 자동매매 많이 + 수익 많이 + 포지션 늘리기!"
        try:
            from app.api.v1.multi_timeframe_scan import scan_multi_timeframe
            mta_result = scan_multi_timeframe(
                max_symbols=100, min_score=18,  # 18/24 = 매우 확실!
                db=db, user_id=1,
            )
            for it in (mta_result.get("long_signals") or []):
                # MTA 형식 → BB 형식 변환!
                all_sustained.append({
                    "symbol": it["symbol"],
                    "side": "LONG",
                    "source": "MTA",
                    "success_probability": min(0.99, it["total_score"] / 24.0 + 0.05),
                    "sustained_bars": 5,
                    "regime": "UPTREND",  # MTA LONG = 상승 반전!
                    "rsi": it["tf_15m"].get("rsi"),
                    "cci": it["tf_15m"].get("cci"),
                    "obv_slope_pct": it["tf_15m"].get("obv_slope_pct"),
                    "change_24h": it["change_24h"],
                    "mta_total": it["total_score"],
                    "mta_reason": it["reason"],
                })
            for it in (mta_result.get("short_signals") or []):
                all_sustained.append({
                    "symbol": it["symbol"],
                    "side": "SHORT",
                    "source": "MTA",
                    "success_probability": min(0.99, it["total_score"] / 24.0 + 0.05),
                    "sustained_bars": 5,
                    "regime": "DOWNTREND_STRONG",
                    "rsi": it["tf_15m"].get("rsi"),
                    "cci": it["tf_15m"].get("cci"),
                    "obv_slope_pct": it["tf_15m"].get("obv_slope_pct"),
                    "change_24h": it["change_24h"],
                    "mta_total": it["total_score"],
                    "mta_reason": it["reason"],
                })
            logger.info(
                "[auto_bb_breakdown] v190 MTA 소스: LONG %d + SHORT %d 추가!",
                len(mta_result.get("long_signals") or []),
                len(mta_result.get("short_signals") or []),
            )
        except Exception as e:
            logger.warning("[auto_bb_breakdown] v190 MTA 스캔 실패: %s", e)

        # 중복 제거 (같은 symbol:side!)
        seen_keys = set()
        deduped = []
        for it in all_sustained:
            k = f"{it['symbol']}:{it['side']}"
            if k not in seen_keys:
                seen_keys.add(k)
                deduped.append(it)
        all_sustained = deduped
        # 성공률 큰 순!
        all_sustained.sort(key=lambda x: -(x.get("success_probability") or 0))

        # 4. 이미 활성 심볼 = 제외!
        active_keys = _get_active_symbol_keys(db)
        # 🚨 v176: 최근 24h 손실 심볼 = 제외!
        recent_loss_keys = _get_recent_loss_symbol_keys(db)
        # 🎓 v188 사장님: 학습 인사이트 = WORST 심볼 자동 제외!
        worst_learning_keys = _get_worst_learning_keys(db)
        top_learning_keys = _get_top_learning_keys(db)

        # 5. 사장님 default profile 로드!
        from app.api.v1.suggestion_profiles import _load_profiles
        profiles, default_name = _load_profiles(db)
        default_profile = next(
            (p for p in profiles if p.get("name") == default_name), None,
        )
        if not default_profile:
            return {"error": "default profile 없음!", "entered": 0}
        cfg = default_profile.get("config", {})

        # 6. 각 SUSTAINED = 실 진입!
        for it in all_sustained:
            if entered >= remaining:
                break
            symbol = it["symbol"]
            side = it["side"]
            key = f"{symbol}:{side}"

            # 6a. 이미 활성 = skip!
            if key in active_keys:
                skipped += 1
                continue

            # 🎓 v188 사장님 (2026-08-20): 학습 인사이트 = WORST 심볼 자동 제외!
            # 사장님 인사이트: PAXG/XAUT/COIN/PLTR 등 주식/금 SHORT = 0%!
            if key in worst_learning_keys:
                skipped += 1
                logger.info(
                    "[auto_bb_breakdown] 🎓 v188 skip: %s (학습 실패 심볼 = 0%%!)", key,
                )
                continue

            # 🚨 v179: 최근 48h 손실 심볼 = skip! (24h → 48h!)
            if key in recent_loss_keys:
                skipped += 1
                logger.info(
                    "[auto_bb_breakdown] 🚨 v179 skip: %s (최근 48h 손실 심볼!)", key,
                )
                continue

            # 🚨 v179: 심볼 30일 성공률 < 40% = skip! (30% → 40%!)
            try:
                from app.workers.prediction_outcome_worker import get_symbol_success_rate
                sr = get_symbol_success_rate(db, symbol, side, days=30)
                if sr < MIN_SYMBOL_SUCCESS_RATE:
                    skipped += 1
                    logger.info(
                        "[auto_bb_breakdown] 🚨 v179 skip: %s (심볼 30일 성공률 %.0f%% < %d%%)",
                        key, sr * 100, int(MIN_SYMBOL_SUCCESS_RATE * 100),
                    )
                    continue
            except Exception:
                pass  # sr 조회 실패 = 계속 진행 (fail-open)

            # 6b. 성공률 필터! (85% → 90%!)
            # 🎓 v188: TOP 학습 심볼 = 완화된 필터! (0.75!)
            prob = float(it.get("success_probability") or 0)
            required_prob = 0.75 if key in top_learning_keys else MIN_SUCCESS_PROBABILITY
            if prob < required_prob:
                continue  # low prob = 나머지 다 낮음 (정렬됨!)
            if key in top_learning_keys:
                logger.info(
                    "[auto_bb_breakdown] 🎓 v188 TOP: %s (학습 성공률 우선 = 완화 필터!)",
                    key,
                )

            # 🌟 v179 신 필터 1: 지속 봉수 = 5봉+ 필수!
            sustained_bars = int(it.get("sustained_bars", 0) or 0)
            if sustained_bars < MIN_SUSTAINED_BARS:
                skipped += 1
                logger.info(
                    "[auto_bb_breakdown] 🌟 v179 skip: %s (지속 %d봉 < %d봉 필수!)",
                    key, sustained_bars, MIN_SUSTAINED_BARS,
                )
                continue

            # 🌟 v179 신 필터 2: regime 필수! (DOWNTREND_STRONG / UPTREND)
            regime = it.get("regime", "NEUTRAL")
            required_regimes = REQUIRED_REGIMES.get(side, set())
            if regime not in required_regimes:
                skipped += 1
                logger.info(
                    "[auto_bb_breakdown] 🌟 v179 skip: %s regime=%s (%s만 허용!)",
                    key, regime, "/".join(required_regimes),
                )
                continue

            # 🌟 v179 신 필터 3: RSI 안전 범위! (30~70)
            rsi = it.get("rsi")
            if rsi is not None:
                rsi_min, rsi_max = RSI_SAFE_RANGE.get(side, (0, 100))
                if rsi < rsi_min or rsi > rsi_max:
                    skipped += 1
                    logger.info(
                        "[auto_bb_breakdown] 🌟 v179 skip: %s RSI %.0f (안전 범위 %d~%d 밖!)",
                        key, rsi, rsi_min, rsi_max,
                    )
                    continue

            # 6c. 실 진입!
            try:
                new_strategy = _create_auto_bb_strategy(db, symbol, side, cfg)
                # StrategySuggestion 저장 (자동 진입 표시!)
                sugg = StrategySuggestion(
                    symbol=symbol, side=side,
                    suggestion_type="bb4h_auto_entry",
                    strategy_config={**cfg, "symbol": symbol, "side": side},
                    confidence_score=Decimal(str(round(prob, 4))),
                    reason=(
                        f"BB 4H SUSTAINED 자동 진입! "
                        f"성공률 {int(prob*100)}% / 지속 {it.get('sustained_bars', 0)}봉 / "
                        f"regime={it.get('regime', 'NEUTRAL')}"
                    ),
                    status="EXECUTED",
                    execution_mode="AUTO",
                    executed_at=datetime.now(timezone.utc),
                    executed_strategy_id=new_strategy.id,
                    outcome_status="PENDING",
                )
                db.add(sugg)
                db.commit()

                results.append({
                    "symbol": symbol,
                    "side": side,
                    "success_probability": prob,
                    "sustained_bars": it.get("sustained_bars"),
                    "regime": it.get("regime"),
                    "strategy_id": new_strategy.id,
                })
                entered += 1

                # 6d. 텔레그램 알림!
                _notify_auto_entry(new_strategy, prob, it)

                logger.info(
                    "[auto_bb_breakdown] ✅ 자동 진입: #%d %s %s (prob=%.0f%%)",
                    new_strategy.id, symbol, side, prob * 100,
                )
            except Exception as e:
                logger.warning(
                    "[auto_bb_breakdown] ❌ %s %s 진입 실패: %s", symbol, side, e,
                )
                skipped += 1
                db.rollback()
                continue

        return {
            "daily_limit": daily_limit,
            "used_before": used,
            "remaining_before": remaining,
            "sustained_total": len(all_sustained),
            "entered_now": entered,
            "skipped": skipped,
            "results": results,
        }
    except Exception as e:
        logger.exception("[auto_bb_breakdown] 예외: %s", e)
        return {"error": str(e), "entered": entered}
    finally:
        db.close()


def _count_used_slots(db: Session) -> int:
    """v163 로직: 활성 + 손절 = 카운트! (익절 = 제외!)

    오늘 EXECUTED (execution_mode='AUTO') + suggestion_type='bb4h_auto_entry'
    - 익절 (SUCCESS outcome) = 제외!
    - 활성 or 손절 (PENDING/FAIL outcome) = 카운트!
    """
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    rows = db.execute(
        select(StrategySuggestion)
        .where(StrategySuggestion.status == "EXECUTED")
        .where(StrategySuggestion.execution_mode == "AUTO")
        .where(StrategySuggestion.suggestion_type == "bb4h_auto_entry")
        .where(StrategySuggestion.executed_at >= today_start)
    ).scalars().all()
    # 익절 (SUCCESS) 제외!
    return sum(1 for r in rows if r.outcome_status != "SUCCESS")


def _get_active_symbol_keys(db: Session) -> set[str]:
    """현재 활성 심볼 keys = 'SYMBOL:SIDE' 집합!"""
    active_keys = set()
    from app.core.strategy_status import TERMINAL_STATUSES
    for a in db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.status.notin_(TERMINAL_STATUSES))
        .where(StrategyInstance.is_archived.is_(False))
    ).scalars().all():
        active_keys.add(f"{a.symbol}:{a.side}")
    return active_keys


def _get_worst_learning_keys(db: Session) -> set[str]:
    """🎓 v188+v194 사장님: 학습 인사이트 + 실제 손실 = WORST 심볼 자동 제외!

    v188: outcome_status 기반 (인사이트!)
    🚨 v194 (2026-08-20 사장님 실적 -798/24h 분석!):
    - 인사이트 outcome_status ≠ 실제 PnL! (CYSUSDT 88%인데 실제 -165!)
    - **실제 realized_pnl 기반 추가!**
    - 7일 -100 USDT+ 손실 심볼 = 자동 제외!
    """
    worst = set()
    # 1️⃣ v188: 학습 인사이트 기반!
    try:
        from app.workers.pattern_learning_worker import get_learning_insights
        insights = get_learning_insights(db) or {}
        for w in insights.get("worst_symbols_short", []):
            if w.get("total", 0) >= 5:
                worst.add(f"{w['symbol']}:SHORT")
        for w in insights.get("worst_symbols_long", []):
            if w.get("total", 0) >= 5:
                worst.add(f"{w['symbol']}:LONG")
    except Exception as e:
        logger.warning("[v188] worst 인사이트 로드 실패: %s", e)

    # 🚨 2️⃣ v194: 실제 realized_pnl 기반! (더 강력!)
    try:
        from datetime import timedelta as _td
        from app.core.strategy_status import TERMINAL_STATUSES as _TS
        cutoff = datetime.now(timezone.utc) - _td(days=7)
        rows = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.stopped_at >= cutoff)
            .where(StrategyInstance.status.in_(list(_TS)))
        ).scalars().all()
        sym_pnl: dict[str, dict] = {}
        for s in rows:
            key = f"{s.symbol}:{s.side}"
            pnl = float(s.realized_pnl or 0)
            if key not in sym_pnl:
                sym_pnl[key] = {"total": 0.0, "wins": 0, "losses": 0}
            sym_pnl[key]["total"] += pnl
            if pnl > 0:
                sym_pnl[key]["wins"] += 1
            elif pnl < 0:
                sym_pnl[key]["losses"] += 1
        # -100 USDT+ 손실 + 2건+ 손실 + 승률 <30% = worst!
        for key, s in sym_pnl.items():
            total_trades = s["wins"] + s["losses"]
            if total_trades < 2:
                continue
            win_rate = s["wins"] / total_trades if total_trades > 0 else 0
            if s["total"] <= -100 and win_rate < 0.30:
                worst.add(key)
                logger.info(
                    "[v194] worst 추가: %s (%.2f USDT, %d승/%d패)",
                    key, s["total"], s["wins"], s["losses"],
                )
    except Exception as e:
        logger.warning("[v194] realized_pnl worst 계산 실패: %s", e)
    return worst


def _get_top_learning_keys(db: Session) -> set[str]:
    """🎓 v188 + v195 사장님: TOP 심볼 (필터 완화!) + 실패 역이용!

    v188: 학습 인사이트 top 심볼!
    🌟 v195 (2026-08-20 사장님 지능!):
    "실패한 차트의 원인을 분석하고 학습해서 다음에 역으로 이용!"
    - CYSUSDT SHORT 실패 (-165!) → CYSUSDT LONG = **역 기회!**
    - USUSDT SHORT 실패 (-311!) → USUSDT LONG = **역 기회!**
    - 시장이 확실히 상승 → SHORT 실패 → LONG 진입!
    """
    top = set()
    # 1️⃣ v188: 학습 인사이트 top!
    try:
        from app.workers.pattern_learning_worker import get_learning_insights
        insights = get_learning_insights(db) or {}
        for t in insights.get("top_symbols_short", [])[:15]:
            if t.get("total", 0) >= 5 and t.get("success_rate", 0) >= 0.70:
                top.add(f"{t['symbol']}:SHORT")
        for t in insights.get("top_symbols_long", [])[:15]:
            if t.get("total", 0) >= 5 and t.get("success_rate", 0) >= 0.70:
                top.add(f"{t['symbol']}:LONG")
    except Exception as e:
        logger.warning("[v188] top 심볼 로드 실패: %s", e)

    # 🌟 2️⃣ v195: 실패 역이용! (반대 방향 = 기회!)
    try:
        inverse_opps = _get_inverse_opportunity_keys(db)
        top.update(inverse_opps)
        if inverse_opps:
            logger.info(
                "[v195] 실패 역이용 = %d개 (반대 방향 우대!): %s",
                len(inverse_opps), list(inverse_opps)[:5],
            )
    except Exception as e:
        logger.warning("[v195] 실패 역이용 실패: %s", e)
    return top


def _get_inverse_opportunity_keys(db: Session) -> set[str]:
    """🌟 v195 사장님 실패 역이용!

    사장님 사상 (2026-08-20):
    "실패한 차트의 원인을 분석하고 학습해서 다음에 역으로 이용할 수 있게!"

    로직:
    1. 7일 realized_pnl 심볼별 집계!
    2. SHORT 손실 심볼 → LONG 역기회!
    3. LONG 손실 심볼 → SHORT 역기회!
    4. -100 USDT+ 손실 + 2건+ 손실 + 승률 <30%
       = **반대 방향 = 시장이 확실히 그쪽으로 움직임 = 기회!**
    """
    inverse = set()
    try:
        from datetime import timedelta as _td
        from app.core.strategy_status import TERMINAL_STATUSES as _TS
        cutoff = datetime.now(timezone.utc) - _td(days=7)
        rows = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.stopped_at >= cutoff)
            .where(StrategyInstance.status.in_(list(_TS)))
        ).scalars().all()
        sym_pnl: dict[str, dict] = {}
        for s in rows:
            key = f"{s.symbol}:{s.side}"
            pnl = float(s.realized_pnl or 0)
            if key not in sym_pnl:
                sym_pnl[key] = {"total": 0.0, "wins": 0, "losses": 0}
            sym_pnl[key]["total"] += pnl
            if pnl > 0:
                sym_pnl[key]["wins"] += 1
            elif pnl < 0:
                sym_pnl[key]["losses"] += 1

        # 실패 심볼 = 반대 방향 = 역기회!
        for key, s in sym_pnl.items():
            total_trades = s["wins"] + s["losses"]
            if total_trades < 2:
                continue
            win_rate = s["wins"] / total_trades if total_trades > 0 else 0
            # -100 USDT+ 손실 + 승률 <30% = 확실한 실패!
            if s["total"] <= -100 and win_rate < 0.30:
                symbol, side = key.rsplit(":", 1)
                inverse_side = "LONG" if side == "SHORT" else "SHORT"
                inverse_key = f"{symbol}:{inverse_side}"
                # 반대 방향이 아직 손실 심볼이 아니면만 추가!
                inverse_stat = sym_pnl.get(inverse_key)
                if inverse_stat and inverse_stat["total"] < -50:
                    continue  # 반대도 이미 손실 = skip!
                inverse.add(inverse_key)
    except Exception as e:
        logger.warning("[v195] 역기회 계산 실패: %s", e)
    return inverse


def _get_recent_loss_symbol_keys(db: Session) -> set[str]:
    """🚨 v179: 최근 48h 손실 심볼 keys! (v176 24h → v179 48h!)

    사장님 CBRSUSDT #1013 = -10.97% 손실 → 3분 후 재진입 = 같은 심볼!
    = 손실 후 즉시 재진입 = 위험! 48h 쿨다운!
    """
    from datetime import timedelta
    loss_keys = set()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOSS_BLOCKLIST_HOURS)
    # STOPPED 이면서 = realized_pnl < 0 = 손실 심볼!
    for s in db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.status.in_([
            "STOPPED", "CLOSED", "CLOSED_BY_SL", "STOPPED_CAPITAL_EXHAUSTED",
        ]))
        .where(StrategyInstance.stopped_at >= cutoff)
    ).scalars().all():
        try:
            pnl = float(s.realized_pnl or 0)
            if pnl < 0:  # 손실!
                loss_keys.add(f"{s.symbol}:{s.side}")
        except Exception:
            pass
    return loss_keys


def _create_auto_bb_strategy(
    db: Session, symbol: str, side: str, cfg: dict[str, Any],
) -> StrategyInstance:
    """사장님 default profile 기반 = template + strategy 자동 생성!"""
    # symbol 검증!
    symbol_row = db.execute(
        select(Symbol).where(Symbol.symbol == symbol)
    ).scalar_one_or_none()
    if not symbol_row:
        raise ValueError(f"symbol {symbol} not in DB")

    # 🌟 v177 사장님 (2026-08-19): 자동 진입 = 1단계만 강제!
    # v161 spec: "단계는 1단계로만 할꺼야 진입만 하면
    #            우리 전략인스턴스 설정으로 진행할꺼야"
    # 사장님 지적: default profile 4단계 → 2단계 이후 자동 차단 알림 발생!
    # Fix: capitals = [첫 단계 자본만!] = 1단계 강제!
    capitals_full = cfg.get("capitals") or [500, 500, 500, 500]
    stage1_only = float(capitals_full[0]) if capitals_full else 500.0
    capitals = [stage1_only]  # 🌟 v177: 1단계만!
    total_capital = stage1_only

    stages_config = {
        "capitals": capitals,
        "trigger_percents": [None],  # 1단계 = 즉시 진입!
        "stages_count": 1,  # 🌟 v177: 1단계 확정!
    }

    # 신 template = 1단계만!
    now = datetime.now(timezone.utc)
    tpl = StrategyTemplate(
        name=f"AUTO_BB_{symbol}_{side}_{now.strftime('%Y%m%d_%H%M%S')}",
        strategy_type="auto_bb_break",
        side=side,
        leverage=int(cfg.get("leverage", 2)),
        total_capital=Decimal(str(total_capital)),
        stages_config=stages_config,
        stage1_capital=Decimal(str(stage1_only)),
        stage2_capital=None,  # 🌟 v177: 2단계 없음!
        stage3_capital=None,
        stage4_capital=None,
        stage2_trigger_percent=None,
        stage3_trigger_percent=None,
        stage4_trigger_percent=None,
        tp1_percent=Decimal(str(cfg.get("tp1_percent", 10))),
        tp2_percent=Decimal(str(cfg.get("tp2_percent", 15))),
        tp3_percent=Decimal(str(cfg.get("tp3_percent", 20))),
        tp4_percent=Decimal(str(cfg.get("tp4_percent", 25))),
        tp1_qty_ratio=Decimal(str(cfg.get("tp1_qty_ratio", 10))),
        tp2_qty_ratio=Decimal(str(cfg.get("tp2_qty_ratio", 15))),
        tp3_qty_ratio=Decimal(str(cfg.get("tp3_qty_ratio", 20))),
        tp4_qty_ratio=Decimal(str(cfg.get("tp4_qty_ratio", 25))),
        stop_loss_percent_of_capital=Decimal(str(cfg.get("stop_loss_percent_of_capital", 90))),
        is_active=True,
    )
    db.add(tpl)
    db.flush()

    # strategy_instance 생성 (start_price=None = MARKET!)!
    from app.services.strategy_service import StrategyService
    svc = StrategyService(db)

    # 현재가 조회 = start_price!
    start_price = _get_current_price(symbol)

    strategy = svc.create_strategy_instance(
        user_id=1,
        exchange_account_id=1,
        strategy_template_id=tpl.id,
        symbol=symbol,
        side=side,
        start_price=start_price,
        leverage_override=int(cfg.get("leverage", 2)),
        retry_after_liquidation_enabled=bool(cfg.get("retry_after_liquidation_enabled", False)),
        retry_trigger_pct=(
            Decimal(str(cfg.get("retry_trigger_pct", 10)))
            if cfg.get("retry_trigger_pct") else None
        ),
    )
    return strategy


def _get_current_price(symbol: str) -> Decimal:
    """현재가 조회 = start_price!"""
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        val = r.get(f"mark_price:{symbol}")
        if val:
            return Decimal(str(val.decode() if isinstance(val, bytes) else val))
    except Exception:
        pass
    # fallback = Binance API!
    try:
        from app.integrations.binance.client import BinanceClient
        from app.models.exchange_account import ExchangeAccount
        from app.core.crypto import decrypt_text
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            account = db.execute(
                select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
            ).scalar_one_or_none()
            if account:
                bc = BinanceClient(
                    api_key=decrypt_text(account.api_key_enc),
                    api_secret=decrypt_text(account.api_secret_enc),
                    is_testnet=False,
                )
                ticker = bc.get_24hr_ticker(symbol=symbol)
                if isinstance(ticker, dict):
                    return Decimal(str(ticker.get("lastPrice", 0)))
        finally:
            db.close()
    except Exception:
        pass
    raise ValueError(f"현재가 조회 실패: {symbol}")


def _notify_auto_entry(strategy: StrategyInstance, prob: float, scan_info: dict) -> None:
    """자동 진입 텔레그램 알림! (v193 fix: NotificationService(db) 직접 사용!)"""
    try:
        # 🌟 v193 fix: get_notification_service 함수 없음 → NotificationService(db) 직접!
        from app.services.notification_service import NotificationService
        db_notif = SessionLocal()
        ns = NotificationService(db_notif)
        emoji = "🐻" if strategy.side == "SHORT" else "🐂"
        source = scan_info.get("source", "BB_SUSTAINED")
        source_icon = "🎯" if source == "MTA" else "⚡"
        body_lines = [
            f"{source_icon} {source} 자동 진입!",
            f"📊 성공률: {int(prob * 100)}%",
            f"🎯 regime: {scan_info.get('regime', 'NEUTRAL')}",
            f"🔥 지속 봉수: {scan_info.get('sustained_bars', 0)}봉",
        ]
        # v190: MTA 정보!
        if source == "MTA" and scan_info.get("mta_total"):
            body_lines.append(f"🎯 MTA 종합점수: {scan_info['mta_total']}/24")
            body_lines.append(f"📈 {scan_info.get('mta_reason', '')}"[:100])
        body_lines.extend([
            f"💰 자본: {strategy.total_capital} USDT",
            f"⚖️ 레버리지: {strategy.leverage}x",
            "",
            f"= 사장님 default profile 자동 진입!",
            f"= 대시보드 확인!",
        ])
        ns.send_system_alert(
            title=f"🤖 [자동 진입] #{strategy.id} {strategy.symbol} {strategy.side} {emoji}",
            body="\n".join(body_lines),
        )
        try:
            db_notif.close()
        except Exception:
            pass
    except Exception as e:
        logger.warning("[auto_bb_breakdown] 알림 실패: %s", e)
