"""🎓 TradeLearningService = 모든 거래 자동 학습! (v134 사장님!)

배경:
- 진입 시 = record 생성!
- 종료 시 = update + insights!
- 진행 중 = 스냅샷 (5분 단위!)

사용:
    from app.services.trade_learning_service import TradeLearningService
    tls = TradeLearningService(db)

    # 진입!
    tls.on_entry(strategy)

    # 종료!
    tls.on_exit(strategy, close_reason='TP1')

    # 스냅샷 (worker에서!)
    tls.snapshot(strategy)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.strategy_instance import StrategyInstance
from app.models.trade_learning_record import TradeLearningRecord

logger = logging.getLogger(__name__)

# 스냅샷 최대 개수 (JSONB 크기 제한!)
MAX_SNAPSHOTS = 100


class TradeLearningService:
    def __init__(self, db: Session):
        self.db = db

    def _get_or_create(self, strategy: StrategyInstance) -> TradeLearningRecord:
        """record 조회 or 생성!"""
        record = self.db.execute(
            select(TradeLearningRecord)
            .where(TradeLearningRecord.strategy_instance_id == strategy.id)
        ).scalar_one_or_none()
        if record:
            return record
        record = TradeLearningRecord(
            strategy_instance_id=strategy.id,
            symbol=strategy.symbol,
            side=strategy.side,
            status="OPEN",
        )
        self.db.add(record)
        self.db.flush()
        return record

    def on_entry(self, strategy: StrategyInstance, market_context: dict | None = None) -> None:
        """진입 시 학습 record 생성!"""
        try:
            record = self._get_or_create(strategy)
            record.entry_price = strategy.avg_entry_price
            record.entry_time = strategy.first_entry_at or datetime.now(timezone.utc)
            record.entry_config = self._extract_config(strategy)
            record.entry_context = market_context or {}
            record.status = "OPEN"
            self.db.flush()
            logger.info("[TradeLearning] 진입 기록: strategy_id=%d", strategy.id)
        except Exception as e:
            logger.warning("[TradeLearning] on_entry 실패: %s", e)

    def on_exit(
        self,
        strategy: StrategyInstance,
        close_reason: str | None = None,
        market_context: dict | None = None,
    ) -> None:
        """종료 시 update + insights!"""
        try:
            record = self._get_or_create(strategy)
            record.exit_price = strategy.avg_entry_price  # 최종 평단!
            record.exit_time = datetime.now(timezone.utc)
            record.pnl_pct = strategy.unrealized_pnl_pct or Decimal("0")
            record.max_profit_pct = strategy.max_profit_pct
            record.max_loss_pct = strategy.max_loss_pct
            record.close_reason = close_reason or strategy.close_reason
            record.exit_context = market_context or {}
            record.status = "CLOSED"

            # 자동 인사이트!
            record.insights = self._generate_insights(strategy, record)
            self.db.flush()
            logger.info(
                "[TradeLearning] 종료 기록: strategy_id=%d / reason=%s / pnl=%s",
                strategy.id, close_reason, record.pnl_pct,
            )
        except Exception as e:
            logger.warning("[TradeLearning] on_exit 실패: %s", e)

    def snapshot(
        self,
        strategy: StrategyInstance,
        market_context: dict | None = None,
    ) -> None:
        """진행 중 스냅샷!"""
        try:
            record = self._get_or_create(strategy)
            if record.status != "OPEN":
                return
            snap = {
                "time": datetime.now(timezone.utc).isoformat(),
                "price": str(strategy.current_price or 0),
                "pnl_pct": float(strategy.unrealized_pnl_pct or 0),
                "position_qty": str(strategy.current_position_qty or 0),
            }
            if market_context:
                snap.update(market_context)

            progression = list(record.progression or {}).__class__() if isinstance(record.progression, dict) else []
            # progression = list!
            existing = record.progression
            if not isinstance(existing, list):
                existing = []
            existing.append(snap)
            # 최대 개수 유지 (앞에서 삭제!)
            if len(existing) > MAX_SNAPSHOTS:
                existing = existing[-MAX_SNAPSHOTS:]
            record.progression = existing
            self.db.flush()
        except Exception as e:
            logger.warning("[TradeLearning] snapshot 실패: %s", e)

    def _extract_config(self, strategy: StrategyInstance) -> dict[str, Any]:
        """진입 시 세팅 추출!"""
        return {
            "leverage": float(strategy.leverage or 0),
            "planned_capital": float(strategy.planned_capital or 0),
            "trigger_mode": getattr(strategy, "trigger_mode", None),
            "tp1_pct_override": float(strategy.tp1_pct_override or 0) if strategy.tp1_pct_override else None,
            "force_sl_enabled_override": bool(strategy.force_sl_enabled_override),
            "force_sl_roi_override": float(strategy.force_sl_roi_override or 0) if strategy.force_sl_roi_override else None,
            "retry_after_liquidation_enabled": bool(
                getattr(strategy, "retry_after_liquidation_enabled", False)
            ),
        }

    def _generate_insights(
        self,
        strategy: StrategyInstance,
        record: TradeLearningRecord,
    ) -> dict[str, Any]:
        """자동 인사이트 생성!"""
        pnl = float(record.pnl_pct or 0)
        max_profit = float(record.max_profit_pct or 0)
        max_loss = float(record.max_loss_pct or 0)

        win_lose = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "BREAKEVEN")

        # 보유 기간!
        hold_min = None
        if record.entry_time and record.exit_time:
            delta = record.exit_time - record.entry_time
            hold_min = round(delta.total_seconds() / 60, 1)

        lessons = []

        # 교훈 자동 생성!
        if max_profit > 20 and pnl < 5:
            lessons.append(
                f"⚠️ 최대 수익 +{max_profit:.1f}% 도달했으나 최종 +{pnl:.1f}% = 트레일링 늦음!"
            )
        if max_loss < -30 and pnl > 0:
            lessons.append(
                f"🎉 최대 손실 {max_loss:.1f}% 겪었으나 반등해서 +{pnl:.1f}% = 인내 성공!"
            )
        if max_loss < -50:
            lessons.append(
                f"🚨 최대 손실 {max_loss:.1f}% = 진입 시점 재검토 필요!"
            )
        if record.close_reason and "FORCE_SL" in record.close_reason:
            lessons.append(
                f"📉 강제 SL 발동 = 손실 한도 도달! 진입 신호 or SL threshold 조정 검토!"
            )
        if pnl > 30:
            lessons.append(
                f"🎉 큰 수익 +{pnl:.1f}%! 같은 심볼/방향/시간대 = 재활용 가능!"
            )

        return {
            "win_lose": win_lose,
            "pnl_pct": pnl,
            "max_profit_pct": max_profit,
            "max_loss_pct": max_loss,
            "hold_duration_min": hold_min,
            "close_reason": record.close_reason,
            "lessons": lessons,
        }
