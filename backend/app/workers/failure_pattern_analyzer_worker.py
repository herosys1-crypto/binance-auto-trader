"""Fix 64 P2: 실패 패턴 분석 워커

사장님 verbatim:
    "실패가 너무많아 진입시점 차트와 보조지표들의 움직임을 분석해서
     다음 매매에 활용해줘"

목적:
- 최근 24h 실패 진입 조회
- entry_snapshot 지표 값 분석
- 공통 패턴 감지 (예: RSI > 65 SHORT 진입 = X% 실패)
- Redis에 저장 → 진입 워커가 skip에 활용
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.strategy_status import TERMINAL_STATUSES
from app.models.strategy_instance import StrategyInstance

logger = logging.getLogger(__name__)

SPEC_VERSION = "failure_pattern_analyzer_v1_fix64_2026-08-25"
LOOKBACK_HOURS = 24
MIN_SAMPLES = 3  # 최소 3건 이상 = 패턴!
FAILURE_RATE_THRESHOLD = 0.7  # 70%+ 실패 = 위험 패턴!


def _categorize_indicator(name: str, value: float) -> str:
    """지표 값 = 구간 카테고리로!"""
    if value is None:
        return "unknown"
    if name == "rsi":
        if value < 30:
            return "rsi_extreme_low"
        if value < 45:
            return "rsi_low"
        if value < 55:
            return "rsi_mid"
        if value < 70:
            return "rsi_high"
        return "rsi_extreme_high"
    if name == "cci":
        if value < -150:
            return "cci_extreme_low"
        if value < -50:
            return "cci_low"
        if value < 50:
            return "cci_mid"
        if value < 150:
            return "cci_high"
        return "cci_extreme_high"
    if name == "macd_hist":
        return "macd_positive" if value > 0 else "macd_negative"
    return "other"


def _analyze_failures(db):
    """실패 진입 분석 = 지표 패턴!"""
    from sqlalchemy import func as _sa_func
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    # 🚨 Fix 197: COMPLETED/REENTRY_READY 는 stopped_at 이 NULL 이라 **성공 표본이 전멸**했다.
    #   TERMINAL_STATUSES 로 넓게 잡아놓고 두 번째 조건이 그걸 다 잘라냈다 (헌법 106).
    #   → 종료 시각은 coalesce(stopped_at, updated_at) 로 보정한다.
    #     (stopped_at 을 새로 채우지 않으므로 재진입 게이트는 그대로다.)
    _closed_at = _sa_func.coalesce(StrategyInstance.stopped_at, StrategyInstance.updated_at)
    rows = db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.status.in_(TERMINAL_STATUSES))
        .where(_closed_at >= cutoff)
    ).scalars().all()

    # 통계
    total = len(rows)
    fail_rows = [r for r in rows if r.realized_pnl and float(r.realized_pnl) < 0]
    succ_rows = [r for r in rows if r.realized_pnl and float(r.realized_pnl) > 0]
    # Fix 197 (헌법 105): 표본 쏠림을 스스로 감시한다. succ=0 이면 필터 결함을 의심하라.
    logger.info("[failure_pattern] 표본 total=%d fail=%d succ=%d (succ==0 이면 필터 결함 의심)",
                total, len(fail_rows), len(succ_rows))

    # 지표 패턴 카운트
    pattern_stats = defaultdict(lambda: {"total": 0, "fail": 0})
    symbol_stats = defaultdict(lambda: {"total": 0, "fail": 0, "side": None})
    side_stats = defaultdict(lambda: {"total": 0, "fail": 0})

    for r in rows:
        side = r.side or "UNKNOWN"
        side_stats[side]["total"] += 1
        symbol_stats[f"{r.symbol}:{side}"]["total"] += 1
        symbol_stats[f"{r.symbol}:{side}"]["side"] = side

        is_fail = r.realized_pnl and float(r.realized_pnl) < 0
        if is_fail:
            side_stats[side]["fail"] += 1
            symbol_stats[f"{r.symbol}:{side}"]["fail"] += 1

        # entry_snapshot 지표 분석 (JSON 필드!)
        snap = getattr(r, "entry_snapshot", None) or {}
        if isinstance(snap, dict):
            for key in ["rsi", "cci", "macd_hist"]:
                val = snap.get(key)
                if val is not None:
                    try:
                        cat = _categorize_indicator(key, float(val))
                        pattern_key = f"{side}:{cat}"
                        pattern_stats[pattern_key]["total"] += 1
                        if is_fail:
                            pattern_stats[pattern_key]["fail"] += 1
                    except (TypeError, ValueError):
                        pass

    # 위험 패턴 필터 (>= MIN_SAMPLES + 실패율 >= THRESHOLD)
    danger_patterns = []
    for key, stats in pattern_stats.items():
        if stats["total"] >= MIN_SAMPLES:
            fail_rate = stats["fail"] / stats["total"]
            if fail_rate >= FAILURE_RATE_THRESHOLD:
                danger_patterns.append({
                    "pattern": key,
                    "total": stats["total"],
                    "fail": stats["fail"],
                    "fail_rate": round(fail_rate, 3),
                })

    # 반복 실패 심볼 (>= 2회 실패!)
    worst_symbols = []
    for key, stats in symbol_stats.items():
        if stats["fail"] >= 2:
            worst_symbols.append({
                "symbol_side": key,
                "fail": stats["fail"],
                "total": stats["total"],
            })

    return {
        "total_closed": total,
        "succ": len(succ_rows),
        "fail": len(fail_rows),
        "win_rate": round(len(succ_rows) / max(total, 1), 3),
        "side_stats": {k: dict(v) for k, v in side_stats.items()},
        "danger_patterns": sorted(danger_patterns, key=lambda x: -x["fail_rate"])[:20],
        "worst_symbols": sorted(worst_symbols, key=lambda x: -x["fail"])[:20],
    }


def _save_to_redis(analysis):
    """Redis에 저장 = 진입 워커가 활용!"""
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()

        # 위험 패턴 저장 (진입 워커가 참조!)
        r.setex("failure_analyzer:danger_patterns", 3600, json.dumps(analysis["danger_patterns"]))
        r.setex("failure_analyzer:worst_symbols", 3600, json.dumps(analysis["worst_symbols"]))
        r.setex("failure_analyzer:stats", 3600, json.dumps({
            "total_closed": analysis["total_closed"],
            "succ": analysis["succ"],
            "fail": analysis["fail"],
            "win_rate": analysis["win_rate"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }))
        return True
    except Exception as e:
        logger.warning("[Fix64/save_redis] %s", e)
        return False


def run_failure_pattern_analyzer() -> dict:
    """Fix 64: 실패 패턴 분석 (30분 주기!)"""
    db = SessionLocal()
    try:
        analysis = _analyze_failures(db)
        saved = _save_to_redis(analysis)

        logger.warning(
            "[Fix64/analyzer] 완료: total=%d succ=%d fail=%d win_rate=%.1f%% danger=%d worst=%d spec=%s",
            analysis["total_closed"],
            analysis["succ"],
            analysis["fail"],
            analysis["win_rate"] * 100,
            len(analysis["danger_patterns"]),
            len(analysis["worst_symbols"]),
            SPEC_VERSION,
        )

        # 위험 패턴 텔레그램 알림 (매우 위험 시!)
        if analysis["win_rate"] < 0.3 and analysis["total_closed"] >= 10:
            try:
                from app.services.notification_service import NotificationService
                db_n = SessionLocal()
                try:
                    NotificationService(db_n).send_system_alert(
                        title="🚨 Fix 64 학습 경고 = 승률 매우 낮음!",
                        body=(
                            f"승률 {analysis['win_rate']*100:.1f}% "
                            f"({analysis['succ']}/{analysis['total_closed']}). "
                            f"위험 패턴 {len(analysis['danger_patterns'])}건!"
                        ),
                        severity="CRITICAL",
                    )
                finally:
                    db_n.close()
            except Exception:
                pass

        return {
            "saved": saved,
            "total_closed": analysis["total_closed"],
            "win_rate": analysis["win_rate"],
            "danger_patterns_count": len(analysis["danger_patterns"]),
            "worst_symbols_count": len(analysis["worst_symbols"]),
            "spec_version": SPEC_VERSION,
        }
    finally:
        db.close()
