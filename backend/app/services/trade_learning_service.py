"""🎓 TradeLearningService = 모든 거래 자동 학습! (v134 → v139 대수술!)

배경:
- 진입 시 = record 생성!
- 종료 시 = update + insights!
- 진행 중 = 스냅샷 (5분 단위!)

🚨 v139 CRITICAL FIX (2026-08-14 사장님 「지금까지 매매 분석」 중 발견):
  v134 이후 이 서비스는 **단 한 건도 제대로 저장하지 못하고 있었습니다.**
  StrategyInstance 에 없는 속성 5개를 참조 → 매번 AttributeError →
  넓은 except 가 삼켜서 warning 한 줄만 남고 조용히 실패했습니다.

    first_entry_at / planned_capital / unrealized_pnl_pct / close_reason / current_price
    (전부 모델에 존재하지 않음 = hasattr False)

  실제 프로덕션 증거:
    - 학습 record 37건 전부 status='OPEN' (CLOSED 0건)
    - entry_time / entry_config / entry_context / progression = **전부 0건**
    - scheduler 로그: "on_exit 실패: no attribute 'unrealized_pnl_pct'" 5분마다 27건
    - 그런데 워커는 "closed=27 완료" 라고 보고 = 전형적 silent bug!

  fix:
    1. 모든 속성 접근을 getattr + 실제 존재하는 컬럼으로 대체
    2. 실패를 **숨기지 않음** — bool 반환 + logger.error (헌법 3번!)
    3. 손익률은 realized_pnl / total_capital 로 직접 계산

헌법 v139:
  '학습 저장 실패는 warning 이 아니라 error 다. 실패한 저장을 성공으로 세지 마라!'

사용:
    tls = TradeLearningService(db)
    tls.on_entry(strategy, market_context={...})   # → bool
    tls.on_exit(strategy, close_reason='TP1')      # → bool
    tls.snapshot(strategy)                         # → bool
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.strategy_instance import StrategyInstance
from app.models.trade_learning_record import TradeLearningRecord

logger = logging.getLogger(__name__)

# 스냅샷 최대 개수 (JSONB 크기 제한!)
MAX_SNAPSHOTS = 100


def _dec(value: Any) -> Decimal | None:
    """안전한 Decimal 변환 (None/빈값/이상값 = None)."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


class TradeLearningService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # 모델 속성 안전 접근 (v139: 없는 컬럼 참조로 죽던 것 방지!)
    # ------------------------------------------------------------------
    @staticmethod
    def _entry_time(strategy: StrategyInstance) -> datetime:
        """진입 시각. 모델에 first_entry_at 이 없으므로 실존 컬럼으로 대체."""
        for attr in ("first_entry_at", "started_at", "created_at"):
            v = getattr(strategy, attr, None)
            if v:
                return v
        return datetime.now(timezone.utc)

    @staticmethod
    def _capital(strategy: StrategyInstance) -> Decimal | None:
        """자본 = margin (헌법 v107). planned_capital 은 모델에 없음 → total_capital."""
        for attr in ("planned_capital", "total_capital", "invested_capital"):
            v = _dec(getattr(strategy, attr, None))
            if v and v > 0:
                return v
        return None

    @classmethod
    def _pnl_pct(cls, strategy: StrategyInstance, realized: bool) -> Decimal | None:
        """손익률 %. unrealized_pnl_pct 컬럼이 없으므로 USDT / 자본 으로 계산.

        realized=True  → realized_pnl 기준 (종료 시)
        realized=False → unrealized_pnl 기준 (진행 중)
        """
        # 혹시 나중에 컬럼이 생기면 그걸 우선 사용!
        direct = _dec(getattr(strategy, "unrealized_pnl_pct", None))
        if not realized and direct is not None:
            return direct

        pnl = _dec(getattr(strategy, "realized_pnl" if realized else "unrealized_pnl", None))
        cap = cls._capital(strategy)
        if pnl is None or cap is None or cap <= 0:
            return None
        return (pnl / cap * Decimal("100")).quantize(Decimal("0.0001"))

    @staticmethod
    def _current_price(strategy: StrategyInstance) -> Decimal | None:
        """현재가. 모델 컬럼이 없으므로 Redis mark price 캐시 사용 (헌법 v127)."""
        v = _dec(getattr(strategy, "current_price", None))
        if v:
            return v
        try:
            from app.services.mark_price_cache import get_mark_price
            return get_mark_price(strategy.symbol)
        except Exception:
            return None

    # ------------------------------------------------------------------
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

    def on_entry(
        self,
        strategy: StrategyInstance,
        market_context: dict | None = None,
    ) -> bool:
        """진입 시 학습 record 생성. 성공 여부를 반환 (v139!)."""
        try:
            record = self._get_or_create(strategy)
            record.entry_price = _dec(getattr(strategy, "avg_entry_price", None))
            record.entry_time = self._entry_time(strategy)
            record.entry_config = self._extract_config(strategy)
            record.entry_context = market_context or {}
            record.status = "OPEN"
            self.db.flush()
            logger.info("[TradeLearning] 진입 기록: strategy_id=%d", strategy.id)
            return True
        except Exception as e:
            # v139: warning 아님! 학습 누락 = 조용히 넘어가면 안 됨!
            logger.error(
                "[TradeLearning] on_entry 실패 sid=%s: %s", strategy.id, e, exc_info=True,
            )
            return False

    def on_exit(
        self,
        strategy: StrategyInstance,
        close_reason: str | None = None,
        market_context: dict | None = None,
    ) -> bool:
        """종료 시 update + insights. 성공 여부를 반환 (v139!)."""
        try:
            record = self._get_or_create(strategy)
            record.exit_price = _dec(getattr(strategy, "avg_entry_price", None))
            record.exit_time = datetime.now(timezone.utc)
            record.pnl_usdt = _dec(getattr(strategy, "realized_pnl", None))
            record.pnl_pct = self._pnl_pct(strategy, realized=True) or Decimal("0")
            record.max_profit_pct = _dec(getattr(strategy, "max_profit_pct", None))
            record.max_loss_pct = _dec(getattr(strategy, "max_loss_pct", None))
            record.close_reason = close_reason or getattr(strategy, "close_reason", None)
            record.exit_context = market_context or {}
            record.status = "CLOSED"

            # 자동 인사이트!
            record.insights = self._generate_insights(strategy, record)
            self.db.flush()
            logger.info(
                "[TradeLearning] 종료 기록: strategy_id=%d / reason=%s / pnl=%s USDT (%s%%)",
                strategy.id, record.close_reason, record.pnl_usdt, record.pnl_pct,
            )
            return True
        except Exception as e:
            logger.error(
                "[TradeLearning] on_exit 실패 sid=%s: %s", strategy.id, e, exc_info=True,
            )
            return False

    def snapshot(
        self,
        strategy: StrategyInstance,
        market_context: dict | None = None,
    ) -> bool:
        """진행 중 스냅샷. 성공 여부를 반환 (v139!)."""
        try:
            record = self._get_or_create(strategy)
            if record.status != "OPEN":
                return False
            price = self._current_price(strategy)
            pnl_pct = self._pnl_pct(strategy, realized=False)
            snap = {
                "time": datetime.now(timezone.utc).isoformat(),
                "price": str(price) if price is not None else None,
                "pnl_pct": float(pnl_pct) if pnl_pct is not None else None,
                "pnl_usdt": float(_dec(getattr(strategy, "unrealized_pnl", None)) or 0),
                "position_qty": str(getattr(strategy, "current_position_qty", None) or 0),
                "stage": getattr(strategy, "current_stage", None),
            }
            if market_context:
                snap.update(market_context)

            existing = record.progression
            if not isinstance(existing, list):
                existing = []
            existing.append(snap)
            if len(existing) > MAX_SNAPSHOTS:
                existing = existing[-MAX_SNAPSHOTS:]
            record.progression = existing
            self.db.flush()
            return True
        except Exception as e:
            logger.error(
                "[TradeLearning] snapshot 실패 sid=%s: %s", strategy.id, e, exc_info=True,
            )
            return False

    def _extract_config(self, strategy: StrategyInstance) -> dict[str, Any]:
        """진입 시 세팅 추출 (v139: 전부 getattr = 컬럼 없어도 안 죽음!)."""
        def _f(attr: str) -> float | None:
            v = _dec(getattr(strategy, attr, None))
            return float(v) if v is not None else None

        cap = self._capital(strategy)
        return {
            "leverage": _f("leverage"),
            "capital": float(cap) if cap is not None else None,
            "total_capital": _f("total_capital"),
            "trigger_mode": getattr(strategy, "trigger_mode", None),
            "capital_management_mode": getattr(strategy, "capital_management_mode", None),
            "entry_stage": getattr(strategy, "current_stage", None),
            "tp1_pct_override": _f("tp1_pct_override"),
            "trailing_retrace_pct": _f("trailing_retrace_pct"),
            "force_sl_enabled_override": bool(
                getattr(strategy, "force_sl_enabled_override", False)
            ),
            "force_sl_roi_override": _f("force_sl_roi_override"),
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
        pnl_usdt = float(record.pnl_usdt or 0)
        max_profit = float(record.max_profit_pct or 0)
        max_loss = float(record.max_loss_pct or 0)

        win_lose = "WIN" if pnl_usdt > 0 else ("LOSS" if pnl_usdt < 0 else "BREAKEVEN")

        # 보유 기간!
        hold_min = None
        if record.entry_time and record.exit_time:
            delta = record.exit_time - record.entry_time
            hold_min = round(delta.total_seconds() / 60, 1)

        stage = getattr(strategy, "current_stage", None) or 0
        lessons = []

        if max_profit > 20 and pnl < 5:
            lessons.append(
                f"⚠️ 최대 수익 +{max_profit:.1f}% 도달했으나 최종 {pnl:+.1f}% = 트레일링 늦음!"
            )
        if max_loss < -30 and pnl_usdt > 0:
            lessons.append(
                f"🎉 최대 손실 {max_loss:.1f}% 겪었으나 반등해서 {pnl:+.1f}% = 인내 성공!"
            )
        if max_loss < -50:
            lessons.append(f"🚨 최대 손실 {max_loss:.1f}% = 진입 시점 재검토 필요!")
        if record.close_reason and "FORCE_SL" in str(record.close_reason):
            lessons.append("📉 강제 SL 발동 = 손실 한도 도달! 진입 신호 or SL threshold 조정 검토!")
        if pnl > 30:
            lessons.append(f"🎉 큰 수익 +{pnl:.1f}%! 같은 심볼/방향/시간대 = 재활용 가능!")

        # v139 백테스트 발견: 진입 단계가 깊을수록 손실이 급증!
        # (실측: 1단계 평균 -5.6 / 4단계 -105 / 9단계 이상 -562 ~ -4372 USDT)
        if stage and stage >= 5 and pnl_usdt < 0:
            lessons.append(
                f"🚨 {stage}단계까지 물타기 후 {pnl_usdt:+.0f} USDT 손실 "
                "= 깊은 단계 진입은 손실을 키움 (v139 백테스트 확인!)"
            )

        return {
            "win_lose": win_lose,
            "pnl_pct": pnl,
            "pnl_usdt": pnl_usdt,
            "max_profit_pct": max_profit,
            "max_loss_pct": max_loss,
            "hold_duration_min": hold_min,
            "final_stage": stage,
            "close_reason": record.close_reason,
            "lessons": lessons,
        }
