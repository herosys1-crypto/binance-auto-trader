"""🎓 v209 사장님 (2026-08-21): 자동 진입 실 outcome 자동 확정 워커!

사장님 요구: "학습이 잘되고 있는지도 검증!"

배경:
- prediction_outcome_worker = 4h 후 가격 변동으로 판정 (예측 outcome!)
- 문제: bb4h_auto_entry = 실제 진입 = TP/SL 청산 결과가 진짜 outcome!
- 4h 가격 변동 ≠ 실제 실 매매 결과!

로직 (매 15분!):
1. bb4h_auto_entry StrategySuggestion 조회 (outcome_status = PENDING or NULL!)
2. executed_strategy_id로 StrategyInstance 매핑!
3. StrategyInstance가 TERMINAL_STATUSES (청산됨!)
4. realized_pnl > 0 → SUCCESS! (익절!)
5. realized_pnl <= 0 → FAIL! (손절!)
6. outcome_status 자동 업데이트!

효과:
- 학습 표본 = 대폭 증가! (설정 40% → 90%+ 예상!)
- 실제 매매 기반 학습 = 진짜 데이터!
- pattern_learning_worker = 유효 학습!
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.strategy_status import TERMINAL_STATUSES
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_suggestion import StrategySuggestion

logger = logging.getLogger(__name__)


def run_entry_outcome() -> dict:
    """매 15분 = 자동 진입 실 outcome 자동 확정!"""
    db: Session = SessionLocal()
    updated = 0
    to_success = 0
    to_fail = 0
    still_pending = 0
    try:
        # 최근 30일 자동 진입 = PENDING or NULL!
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        candidates = db.execute(
            select(StrategySuggestion)
            .where(StrategySuggestion.created_at >= cutoff)
            .where(StrategySuggestion.suggestion_type == "bb4h_auto_entry")
            .where(
                (StrategySuggestion.outcome_status.is_(None))
                | (StrategySuggestion.outcome_status == "PENDING")
            )
            .where(StrategySuggestion.executed_strategy_id.isnot(None))
        ).scalars().all()

        for s in candidates:
            try:
                si = db.get(StrategyInstance, s.executed_strategy_id)
                if not si:
                    continue
                # 아직 청산 X = still pending
                if si.status not in TERMINAL_STATUSES:
                    still_pending += 1
                    continue
                # 실제 realized_pnl 기반 판정!
                pnl = float(si.realized_pnl or 0)
                if pnl > 0:
                    s.outcome_status = "SUCCESS"
                    to_success += 1
                else:
                    s.outcome_status = "FAIL"
                    to_fail += 1
                s.outcome_checked_at = datetime.now(timezone.utc)
                updated += 1
                logger.info(
                    "[v209] outcome 확정 %s %s: PnL=%.2f → %s",
                    s.symbol, s.side, pnl, s.outcome_status,
                )
            except Exception as e:
                logger.warning("[v209] %s outcome 확정 실패: %s", s.symbol, e)
                continue

        db.commit()
        logger.info(
            "[v209 entry_outcome] updated=%d success=%d fail=%d pending=%d",
            updated, to_success, to_fail, still_pending,
        )
        return {
            "updated": updated,
            "to_success": to_success,
            "to_fail": to_fail,
            "still_pending": still_pending,
        }
    except Exception as e:
        logger.warning("[v209 entry_outcome] 실행 실패: %s", e)
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()
