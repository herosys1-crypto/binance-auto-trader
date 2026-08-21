"""🎓 PatternLearningWorker = 성공/실패 패턴 학습! (v187 사장님!)

사장님 지시 (2026-08-20):
"성공과 실패에서 포지션 진입해야 할곳을 분석해서 학습해주고
 그런 시점에 롱과 숏을 할수 있게 학습하고 실행해줘!"

로직 (매 1시간!):
1. 최근 30일 예측 = 조회! (StrategySuggestion)
2. 성공 (SUCCESS) vs 실패 (FAIL) 분류!
3. 각 조건 (suggestion_type + side + change_pct 범위) = 성공률 계산!
4. system_settings에 = 최적 조건 저장! (JSON!)
5. UI에서 = /api/v1/pattern-learning/insights로 조회!

Phase 1 (지금!) = 통계 수집 + 저장!
Phase 2 (다음!) = 자동 진입 시 = 학습 조건 반영!
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.strategy_suggestion import StrategySuggestion
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

SETTING_KEY = "pattern_learning_insights_v187"


def run_pattern_learning() -> dict:
    """매 1시간 = 성공/실패 패턴 분석!"""
    db: Session = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        rows = db.execute(
            select(StrategySuggestion)
            .where(StrategySuggestion.created_at >= cutoff)
            .where(StrategySuggestion.outcome_status.in_(["SUCCESS", "FAIL"]))
        ).scalars().all()

        if not rows:
            return {"note": "no data", "insights": {}}

        # 1. suggestion_type + side 별 성공률!
        type_side_stats: dict[str, dict[str, int]] = defaultdict(
            lambda: {"success": 0, "fail": 0}
        )
        for s in rows:
            key = f"{s.suggestion_type}:{s.side}"
            if s.outcome_status == "SUCCESS":
                type_side_stats[key]["success"] += 1
            elif s.outcome_status == "FAIL":
                type_side_stats[key]["fail"] += 1

        # 2. 심볼별 성공률!
        symbol_side_stats: dict[str, dict[str, int]] = defaultdict(
            lambda: {"success": 0, "fail": 0}
        )
        for s in rows:
            key = f"{s.symbol}:{s.side}"
            if s.outcome_status == "SUCCESS":
                symbol_side_stats[key]["success"] += 1
            elif s.outcome_status == "FAIL":
                symbol_side_stats[key]["fail"] += 1

        # 3. change_pct 범위 성공률! (strategy_config에서 24h 변동 추정!)
        change_bucket_stats: dict[str, dict[str, dict[str, int]]] = defaultdict(
            lambda: defaultdict(lambda: {"success": 0, "fail": 0})
        )
        for s in rows:
            # reason에서 24h % 추출!
            reason = (s.reason or "")
            change_pct = _extract_change_pct(reason)
            if change_pct is None:
                continue
            bucket = _classify_change_bucket(change_pct)
            side_bucket = f"{s.side}:{bucket}"
            if s.outcome_status == "SUCCESS":
                change_bucket_stats[s.suggestion_type][side_bucket]["success"] += 1
            elif s.outcome_status == "FAIL":
                change_bucket_stats[s.suggestion_type][side_bucket]["fail"] += 1

        # 🎓 v198 사장님: 진입 스냅샷 조건 학습!
        # 사장님 지시: "실패한 차트 분석해서 다음에 대처하는 학습!"
        snapshot_condition_stats = _analyze_entry_snapshots(rows)

        # 4. 결과 정리 = 성공률 계산!
        insights = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_samples": len(rows),
            "type_side_rankings": _rank_by_success_rate(type_side_stats),
            "top_symbols_long": _top_symbols(symbol_side_stats, "LONG", top=20),
            "top_symbols_short": _top_symbols(symbol_side_stats, "SHORT", top=20),
            "worst_symbols_long": _worst_symbols(symbol_side_stats, "LONG", top=10),
            "worst_symbols_short": _worst_symbols(symbol_side_stats, "SHORT", top=10),
            "change_bucket_insights": _change_bucket_summary(change_bucket_stats),
            # 🎓 v198: 조건별 성공률!
            "snapshot_conditions": snapshot_condition_stats,
        }

        # 5. system_settings 저장!
        row = db.get(SystemSetting, SETTING_KEY)
        val = json.dumps(insights, ensure_ascii=False)
        if row:
            row.value = val
        else:
            db.add(SystemSetting(
                key=SETTING_KEY, value=val,
                description="v187 사장님: 성공/실패 패턴 학습 인사이트 (매 1h 갱신!)",
            ))
        db.commit()

        logger.info(
            "[pattern_learning] v187 학습 완료: %d 샘플, %d 타입/방향 조합",
            len(rows), len(type_side_stats),
        )

        # 🎼 v206 사장님: 오케스트라 통합 = EventBus 발신!
        try:
            from app.agents.orchestrator.event_bus import get_event_bus
            from app.agents.orchestrator.event_types import EventType
            get_event_bus().publish(EventType.PATTERN_LEARNING_DONE, {
                "samples": len(rows),
                "types_analyzed": len(type_side_stats),
                "symbols_analyzed": len(symbol_side_stats),
                "generated_at": insights.get("generated_at"),
            })
        except Exception as e:
            logger.debug("[v206] EventBus publish 실패 (fail-open): %s", e)

        return {
            "samples": len(rows),
            "types_analyzed": len(type_side_stats),
            "symbols_analyzed": len(symbol_side_stats),
            "insights_saved": True,
        }
    except Exception as e:
        logger.exception("[pattern_learning] 실패: %s", e)
        return {"error": str(e)}
    finally:
        db.close()


def _extract_change_pct(reason: str) -> float | None:
    """reason 문자열에서 24h % 추출."""
    import re
    m = re.search(r"([+-]?\d+\.?\d*)%", reason)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _classify_change_bucket(change_pct: float) -> str:
    """24h 변동 % → 버킷 분류!"""
    if change_pct >= 40:
        return "very_high (40%+)"
    elif change_pct >= 25:
        return "high (25~40%)"
    elif change_pct >= 15:
        return "medium (15~25%)"
    elif change_pct >= 5:
        return "low (5~15%)"
    elif change_pct <= -40:
        return "very_low (-40% 이상 급락)"
    elif change_pct <= -25:
        return "dump_high (-25~-40%)"
    elif change_pct <= -15:
        return "dump_medium (-15~-25%)"
    elif change_pct <= -5:
        return "dump_low (-5~-15%)"
    else:
        return "neutral (-5~+5%)"


def _rank_by_success_rate(stats: dict) -> list[dict]:
    """성공률 순 랭킹!"""
    ranked = []
    for key, s in stats.items():
        total = s["success"] + s["fail"]
        if total < 3:  # 표본 너무 작으면 skip
            continue
        rate = s["success"] / total
        ranked.append({
            "key": key,
            "success": s["success"],
            "fail": s["fail"],
            "total": total,
            "success_rate": round(rate, 4),
        })
    ranked.sort(key=lambda x: -x["success_rate"])
    return ranked


def _top_symbols(stats: dict, side: str, top: int = 20) -> list[dict]:
    """성공률 top N 심볼!"""
    filtered = []
    for key, s in stats.items():
        sym, side_val = key.split(":")
        if side_val != side:
            continue
        total = s["success"] + s["fail"]
        if total < 2:
            continue
        rate = s["success"] / total
        if rate < 0.5:  # 50% 미만 = 제외!
            continue
        filtered.append({
            "symbol": sym,
            "success": s["success"],
            "fail": s["fail"],
            "total": total,
            "success_rate": round(rate, 4),
        })
    filtered.sort(key=lambda x: (-x["success_rate"], -x["total"]))
    return filtered[:top]


def _worst_symbols(stats: dict, side: str, top: int = 10) -> list[dict]:
    """실패율 top N 심볼! (진입 X 심볼!)"""
    filtered = []
    for key, s in stats.items():
        sym, side_val = key.split(":")
        if side_val != side:
            continue
        total = s["success"] + s["fail"]
        if total < 2:
            continue
        rate = s["success"] / total
        if rate > 0.3:  # 30% 초과 = 나쁘지 않음 = 제외!
            continue
        filtered.append({
            "symbol": sym,
            "success": s["success"],
            "fail": s["fail"],
            "total": total,
            "success_rate": round(rate, 4),
        })
    filtered.sort(key=lambda x: (x["success_rate"], -x["total"]))
    return filtered[:top]


def _change_bucket_summary(stats: dict) -> dict:
    """suggestion_type별 change 버킷 성공률!"""
    summary = {}
    for stype, bucket_stats in stats.items():
        summary[stype] = _rank_by_success_rate(bucket_stats)
    return summary


def _analyze_entry_snapshots(rows: list) -> dict:
    """🎓 v198 사장님 (2026-08-21): 진입 시점 스냅샷 조건별 성공률!

    사장님 지시: "실패한 차트 분석해서 다음에 대처하는 학습!
                 보조지표 (RSI/CCI/OBV/MACD)를 잘 활용!"

    분석:
    - RSI 범위별 성공률!
    - CCI 범위별 성공률!
    - OBV slope 방향별!
    - regime별!
    - KST 시간대별!
    - source별 (BB_SUSTAINED vs MTA!)
    """
    rsi_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"success": 0, "fail": 0})
    cci_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"success": 0, "fail": 0})
    obv_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"success": 0, "fail": 0})
    regime_side_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"success": 0, "fail": 0})
    hour_side_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"success": 0, "fail": 0})
    source_side_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"success": 0, "fail": 0})

    for s in rows:
        snap = None
        if s.strategy_config and isinstance(s.strategy_config, dict):
            snap = s.strategy_config.get("entry_snapshot")
        if not snap:
            continue
        outcome = s.outcome_status
        if outcome not in ("SUCCESS", "FAIL"):
            continue
        result_key = "success" if outcome == "SUCCESS" else "fail"

        # RSI 버킷!
        rsi = snap.get("rsi")
        if rsi is not None:
            rsi_bucket = _bucket_rsi(rsi)
            rsi_stats[f"{rsi_bucket}:{s.side}"][result_key] += 1

        # CCI 버킷!
        cci = snap.get("cci")
        if cci is not None:
            cci_bucket = _bucket_cci(cci)
            cci_stats[f"{cci_bucket}:{s.side}"][result_key] += 1

        # OBV slope!
        obv = snap.get("obv_slope_pct")
        if obv is not None:
            obv_bucket = _bucket_obv(obv)
            obv_stats[f"{obv_bucket}:{s.side}"][result_key] += 1

        # regime!
        regime = snap.get("regime", "NEUTRAL")
        regime_side_stats[f"{regime}:{s.side}"][result_key] += 1

        # KST 시간대!
        kst_h = snap.get("kst_hour")
        if kst_h is not None:
            hour_side_stats[f"KST{kst_h:02d}:{s.side}"][result_key] += 1

        # source (BB_SUSTAINED / MTA!)
        source = snap.get("source", "BB_SUSTAINED")
        source_side_stats[f"{source}:{s.side}"][result_key] += 1

    return {
        "rsi_conditions": _rank_by_success_rate(rsi_stats),
        "cci_conditions": _rank_by_success_rate(cci_stats),
        "obv_conditions": _rank_by_success_rate(obv_stats),
        "regime_conditions": _rank_by_success_rate(regime_side_stats),
        "hour_conditions": _rank_by_success_rate(hour_side_stats),
        "source_conditions": _rank_by_success_rate(source_side_stats),
    }


def _bucket_rsi(rsi: float) -> str:
    """RSI 버킷!"""
    if rsi < 20: return "very_low (<20 극과매도)"
    if rsi < 30: return "low (20~30 과매도)"
    if rsi < 45: return "mid_low (30~45)"
    if rsi < 55: return "neutral (45~55)"
    if rsi < 70: return "mid_high (55~70)"
    if rsi < 80: return "high (70~80 과매수)"
    return "very_high (>80 극과매수)"


def _bucket_cci(cci: float) -> str:
    """CCI 버킷!"""
    if cci < -200: return "extreme_low (<-200)"
    if cci < -100: return "low (-200~-100)"
    if cci < 0: return "mid_low (-100~0)"
    if cci < 100: return "mid_high (0~100)"
    if cci < 200: return "high (100~200)"
    return "extreme_high (>200)"


def _bucket_obv(obv: float) -> str:
    """OBV slope % 버킷!"""
    if obv < -10: return "strong_down (<-10%)"
    if obv < -3: return "down (-10~-3%)"
    if obv < 3: return "neutral (-3~+3%)"
    if obv < 10: return "up (+3~+10%)"
    return "strong_up (>+10%)"


def get_learning_insights(db: Session) -> dict | None:
    """저장된 학습 인사이트 조회!"""
    row = db.get(SystemSetting, SETTING_KEY)
    if not row or not row.value:
        return None
    try:
        return json.loads(row.value)
    except Exception:
        return None
