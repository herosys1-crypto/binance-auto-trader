"""🎓 LearningSyncWorker = 매 5분 자동 학습 저장! (v134 사장님!)

배경 (사장님 요청 2026-08-13):
"모든 거래 학습해서 저장하고 [...] 자동화했을때도 항상 진행과정과
 종료된거래를 학습해서 다음에 더 잘 활용할수 있게 저장해줘"

로직:
- 활성 전략 조회!
- record 없으면 = on_entry (진입!)
- record 있고 OPEN = snapshot (진행!)
- STOPPED = on_exit (종료 인사이트!)

= 실시간 훅 없이도 = 자동 커버!
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.strategy_instance import StrategyInstance
from app.models.trade_learning_record import TradeLearningRecord
from app.services.trade_learning_service import TradeLearningService

logger = logging.getLogger(__name__)


# 종료된지 24시간 이내 = on_exit 대상!
CLOSED_LOOKBACK_HOURS = 24


def run_learning_sync() -> dict:
    """5분마다 실행 = 학습 자동 sync!"""
    db: Session = SessionLocal()
    entered = 0
    snapped = 0
    closed = 0
    try:
        tls = TradeLearningService(db)

        # 1. 활성 전략 = on_entry or snapshot!
        open_statuses = [
            "STAGE_1_OPEN", "STAGE_2_OPEN", "STAGE_3_OPEN",
            "STAGE_4_OPEN", "STAGE_5_OPEN", "STAGE_6_OPEN",
            "STAGE_7_OPEN", "STAGE_8_OPEN", "STAGE_9_OPEN",
            "STAGE_10_OPEN",
        ]
        active_strategies = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.status.in_(open_statuses))
            .where(StrategyInstance.current_position_qty != 0)
        ).scalars().all()

        for s in active_strategies:
            try:
                # record 존재 여부!
                record = db.execute(
                    select(TradeLearningRecord)
                    .where(TradeLearningRecord.strategy_instance_id == s.id)
                ).scalar_one_or_none()

                if record is None:
                    # 신규 = on_entry!
                    tls.on_entry(s)
                    entered += 1
                elif record.status == "OPEN":
                    # 진행 중 = snapshot!
                    tls.snapshot(s)
                    snapped += 1
            except Exception as e:
                logger.warning("[learning_sync] entry/snapshot 실패 sid=%d: %s", s.id, e)

        db.commit()

        # 2. 최근 STOPPED 전략 = on_exit (누락 방지!)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=CLOSED_LOOKBACK_HOURS)
        stopped = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.status == "STOPPED")
            .where(StrategyInstance.stopped_at >= cutoff)
        ).scalars().all()

        for s in stopped:
            try:
                record = db.execute(
                    select(TradeLearningRecord)
                    .where(TradeLearningRecord.strategy_instance_id == s.id)
                ).scalar_one_or_none()

                if record is None:
                    # 신규 = 진입 + 종료 동시!
                    tls.on_entry(s)
                    tls.on_exit(s, close_reason=getattr(s, "close_reason", "UNKNOWN"))
                    closed += 1
                elif record.status == "OPEN":
                    # 진행 중 → 종료 mark!
                    tls.on_exit(s, close_reason=getattr(s, "close_reason", "UNKNOWN"))
                    closed += 1
            except Exception as e:
                logger.warning("[learning_sync] exit 실패 sid=%d: %s", s.id, e)

        db.commit()

        logger.info(
            "[learning_sync] 완료: entered=%d snapped=%d closed=%d",
            entered, snapped, closed,
        )
        return {"entered": entered, "snapped": snapped, "closed": closed}
    except Exception as e:
        logger.warning("[learning_sync] 실행 실패: %s", e)
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()
