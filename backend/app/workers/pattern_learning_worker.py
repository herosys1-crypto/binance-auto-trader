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

        # 🎓 사장님 요구 (2026-08-21): entry_snapshot + exit_snapshot = lifecycle 학습!
        # = 진입 지표 → 청산 결과 = 성공/실패 패턴 분석!
        # = strategy_instance에서 executed_strategy_id로 조회!
        lifecycle_stats = _analyze_lifecycle_patterns(db, rows)

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
            # 🎓 사장님 요구 (2026-08-21): lifecycle 분석!
            "lifecycle_stats": lifecycle_stats,
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


def _analyze_lifecycle_patterns(db: Session, rows: list) -> dict:
    """🎓 사장님 요구 (2026-08-21): entry_snapshot + exit_snapshot = 완전한 lifecycle 학습!

    사장님 지시:
    "모든 거래 + 성공/실패 차트 변화 학습 → 메모리 → 매매 로직 활용!"

    로직:
    1. rows (StrategySuggestion) → executed_strategy_id로 StrategyInstance 조회!
    2. StrategyInstance.strategy_config = entry_snapshot + exit_snapshot!
    3. 성공 vs 실패 = 지표 변화 패턴 분석!
    4. exit_stage 분포 = 몇 단계에서 청산?
    5. pnl_pct 분포 = 익절/손절 폭!

    반환:
    - success_avg_pnl_pct: 성공 시 평균 % 익절!
    - fail_avg_pnl_pct: 실패 시 평균 % 손절!
    - success_avg_exit_stage: 성공 시 평균 청산 stage!
    - fail_avg_exit_stage: 실패 시 평균 청산 stage!
    - success_entry_indicators: 성공 진입 시 지표 평균 (RSI/CCI/OBV)!
    - fail_entry_indicators: 실패 진입 시 지표 평균!
    - stage_distribution: stage별 분포 (성공/실패!)
    - side_lifecycle: LONG/SHORT별 lifecycle 분석!
    """
    from app.models.strategy_instance import StrategyInstance

    success_pnls: list[float] = []
    fail_pnls: list[float] = []
    success_stages: list[int] = []
    fail_stages: list[int] = []
    success_indicators: dict[str, list[float]] = defaultdict(list)
    fail_indicators: dict[str, list[float]] = defaultdict(list)
    stage_dist_success: dict[int, int] = defaultdict(int)
    stage_dist_fail: dict[int, int] = defaultdict(int)
    side_lifecycle: dict[str, dict] = defaultdict(
        lambda: {"success": 0, "fail": 0, "success_pnl": 0.0, "fail_pnl": 0.0}
    )
    total_analyzed = 0

    for s in rows:
        if not s.executed_strategy_id:
            continue
        si = db.get(StrategyInstance, s.executed_strategy_id)
        if not si:
            continue
        cfg = si.strategy_config or {}
        if not isinstance(cfg, dict):
            continue
        entry_snap = cfg.get("entry_snapshot")
        exit_snap = cfg.get("exit_snapshot")
        if not entry_snap or not exit_snap:
            continue

        outcome = s.outcome_status
        if outcome not in ("SUCCESS", "FAIL"):
            continue

        total_analyzed += 1
        pnl_pct = float(exit_snap.get("pnl_pct", 0))
        exit_stage = int(exit_snap.get("exit_stage", 0))
        side = s.side or "?"

        if outcome == "SUCCESS":
            success_pnls.append(pnl_pct)
            success_stages.append(exit_stage)
            stage_dist_success[exit_stage] += 1
            side_lifecycle[side]["success"] += 1
            side_lifecycle[side]["success_pnl"] += pnl_pct
            for k in ("rsi", "cci", "obv_slope_pct"):
                v = entry_snap.get(k)
                if v is not None:
                    try:
                        success_indicators[k].append(float(v))
                    except (ValueError, TypeError):
                        pass
        else:  # FAIL
            fail_pnls.append(pnl_pct)
            fail_stages.append(exit_stage)
            stage_dist_fail[exit_stage] += 1
            side_lifecycle[side]["fail"] += 1
            side_lifecycle[side]["fail_pnl"] += pnl_pct
            for k in ("rsi", "cci", "obv_slope_pct"):
                v = entry_snap.get(k)
                if v is not None:
                    try:
                        fail_indicators[k].append(float(v))
                    except (ValueError, TypeError):
                        pass

    def _avg(lst: list[float]) -> float | None:
        return round(sum(lst) / len(lst), 2) if lst else None

    def _avg_dict(d: dict[str, list[float]]) -> dict[str, float | None]:
        return {k: _avg(v) for k, v in d.items()}

    return {
        "total_analyzed": total_analyzed,
        "success_count": len(success_pnls),
        "fail_count": len(fail_pnls),
        "success_avg_pnl_pct": _avg(success_pnls),
        "fail_avg_pnl_pct": _avg(fail_pnls),
        "success_avg_exit_stage": _avg(success_stages),
        "fail_avg_exit_stage": _avg(fail_stages),
        "success_entry_indicators_avg": _avg_dict(success_indicators),
        "fail_entry_indicators_avg": _avg_dict(fail_indicators),
        "stage_distribution_success": dict(stage_dist_success),
        "stage_distribution_fail": dict(stage_dist_fail),
        "side_lifecycle": {
            k: {**v, "success_pnl": round(v["success_pnl"], 2),
                     "fail_pnl": round(v["fail_pnl"], 2)}
            for k, v in side_lifecycle.items()
        },
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
