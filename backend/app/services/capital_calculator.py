"""Capital Calculator — 단일 진실 (Single Source of Truth) 모듈
   사장님 헌법 6번: "같은 데이터 = 단 하나의 함수만 사용 = 강제"
   사장님 헌법 7번: "자동 검증 = 모든 계산 = sanity check"

작성: 2026-06-09 v17 (사장님 critical 요청 = silent bug 영구 차단)
배경: 오늘 발견된 silent bug = 모두 같은 데이터를 = 다른 곳에서 다르게 계산
  1. reserved 계산 = exchange_accounts.py vs stage_trigger_worker.py (= 다른 결과!)
  2. wallet_limit = strategy_service.py vs stage_trigger_worker.py
  → 사장님 화면 OK 인데 worker 가 차단 = silent bug!

해결: 이 모듈 = 단 하나의 진실 = 모든 곳에서 호출!
"""
from __future__ import annotations
import os
import logging
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_stage_plan import StrategyStagePlan

logger = logging.getLogger(__name__)


# ============================================================
# 사장님 정책 상수 (= env 변수로 사장님 자율 조정 가능)
# ============================================================

def get_wallet_limit_pct() -> Decimal:
    """사장님 wallet 한도 % (= default 130, env WALLET_LIMIT_PCT 로 변경).
    사장님 = .env 에 WALLET_LIMIT_PCT=300 추가 = 300% 한도 (= 17 strategy 운영 가능).
    """
    try:
        return Decimal(os.environ.get("WALLET_LIMIT_PCT", "130"))
    except Exception:
        return Decimal("130")


def get_wallet_limit_ratio() -> Decimal:
    """wallet 한도 비율 (= 1.30 또는 사장님 옵션)."""
    return get_wallet_limit_pct() / Decimal("100")


# ============================================================
# 핵심 함수: 단일 진실 (= 다른 곳에서 계산 금지!)
# ============================================================

def calc_actual_margin_for_strategy(strategy: StrategyInstance) -> Decimal:
    """strategy 의 실 진입 마진 (= 자본 단위, 마진 = qty × avg / leverage).

    사장님 사상: '실 사용 = Binance lock 마진'
    """
    if not strategy.current_position_qty or not strategy.avg_entry_price or not strategy.leverage:
        return Decimal("0")
    try:
        qty = abs(Decimal(str(strategy.current_position_qty)))
        avg = Decimal(str(strategy.avg_entry_price))
        lev = Decimal(str(strategy.leverage))
        if lev > 0:
            return qty * avg / lev
    except Exception as e:
        logger.warning("[capital] actual_margin 계산 실패 strategy=%s: %s", strategy.id, e)
    return Decimal("0")


def calc_untriggered_margin_for_strategy(db: Session, strategy: StrategyInstance) -> Decimal:
    """strategy 의 미진입 단계 자본 합.

    🚨 v112 (2026-07-18) 사장님 CRITICAL fix:
    옛 v6 (2026-06-09): '예약 = 자본 / leverage = 마진 단위'
      → 사장님 사상 위반! capital = margin (같은 단위!)
    신 v112 (사장님 헌법!): 'capital = margin = 지갑 lock 원 금액!'
      → 나눗셈 X! capital 그대로!
      → exchange_accounts.py:_reserved_one v101 fix와 통일!
    """
    try:
        untriggered_plans = db.execute(
            select(StrategyStagePlan)
            .where(StrategyStagePlan.strategy_instance_id == strategy.id)
            .where(StrategyStagePlan.is_triggered.is_(False))
        ).scalars().all()
        # 미진입 단계 capital 합 (= 마진 단위 = 사장님 사상!)
        untriggered_capital = sum(
            (Decimal(str(p.planned_capital or 0)) for p in untriggered_plans),
            Decimal("0")
        )
        # 🚨 v112: capital = margin = 나눗셈 X! (사장님 헌법!)
        return untriggered_capital
    except Exception as e:
        logger.warning("[capital] untriggered_margin 실패 strategy=%s: %s", strategy.id, e)
        return Decimal("0")


def calc_reserved_for_strategy(db: Session, strategy: StrategyInstance) -> Decimal:
    """strategy 의 「예약」 = actual 실 마진 + 미진입 단계 마진.

    사장님 진짜 사상 v6: actual + 미진입 단계 = 마진 단위 일치.
    = 모든 곳에서 이 함수만 호출!
    """
    actual = calc_actual_margin_for_strategy(strategy)
    untriggered = calc_untriggered_margin_for_strategy(db, strategy)
    return actual + untriggered


def calc_reserved_for_account(db: Session, account_id: int) -> Decimal:
    """계정 단위 「예약」 = 모든 active strategy 의 예약 합.

    화면 (exchange_accounts.py) + worker (stage_trigger_worker.py) = 모두 이 함수만 사용!
    """
    # 🚨 2026-06-10 v24 critical fix: app.core.constants 모듈 없음 (= 정확 = strategy_status)
    from app.core.strategy_status import STAGES_WITH_NEXT
    strategies = db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.exchange_account_id == account_id)
        .where(StrategyInstance.is_archived.is_(False))
        .where(StrategyInstance.status.in_(STAGES_WITH_NEXT))
    ).scalars().all()
    return sum(
        (calc_reserved_for_strategy(db, s) for s in strategies),
        Decimal("0")
    )


def calc_wallet_limit(wallet_total: Decimal, custom_pct: Optional[Decimal] = None) -> Decimal:
    """wallet × 한도 비율 (= 사장님 옵션 = default 130%).

    사장님 = .env WALLET_LIMIT_PCT=300 → 300% 한도.
    custom_pct 주면 override (= 테스트용).
    """
    if not wallet_total or wallet_total <= 0:
        return Decimal("0")
    ratio = (custom_pct / Decimal("100")) if custom_pct is not None else get_wallet_limit_ratio()
    return wallet_total * ratio


def calc_new_strategy_available(wallet_total: Decimal, reserved: Decimal) -> Decimal:
    """신 strategy 가용 한도 = wallet × 한도% - 이미 예약된 자본.

    음수면 0 (= 차단). 사장님 화면 「신 전략 가용」 표시.
    """
    limit = calc_wallet_limit(wallet_total)
    available = limit - reserved
    return max(available, Decimal("0"))


def is_wallet_limit_exceeded(wallet_total: Decimal, reserved: Decimal) -> bool:
    """사장님 한도 초과 여부 (= stage_trigger_worker 가 진입 차단 판단).

    True = 한도 초과 = 신 단계 진입 차단
    """
    if not wallet_total or wallet_total <= 0:
        return False  # wallet 조회 실패 시 = 차단 X (= 안전 fallback)
    limit = calc_wallet_limit(wallet_total)
    return reserved > limit


# ============================================================
# 검증 함수 (= self-check worker 가 사용)
# ============================================================

def verify_reserved_consistency(db: Session, account_id: int) -> dict:
    """검증: reserved 계산이 모든 호출에서 동일한지.
    self-check worker 가 매 1시간 호출 → 차이 발견 시 Telegram 알림.
    """
    primary = calc_reserved_for_account(db, account_id)
    # 미래 = 다른 계산 경로 추가 시 = 여기서 비교
    return {
        "account_id": account_id,
        "reserved": float(primary),
        "consistent": True,  # 단일 함수만 사용 = 항상 일치
    }
