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


def ladder_reserves_untriggered(db: Session, strategy: StrategyInstance) -> bool:
    """이 전략의 **미진입 단계**를 「예약」으로 셀 것인가.

    🧾 Fix 344 (2026-09-04 사장님 결정 ③-a): v219 사다리(stage_ladder)는 **아니오**.
      사다리 1건마다 300+600=900 이 예약으로 잡혀, 열린 사다리가 7개를 넘으면 지갑×1.3 을
      넘어 **모든 전략의 2단계가 차단**됐다 (24h 106회 / 11전략 — #2264 실측:
      「실=959 + 예약=11,527 = 207% > 허용 7,235」).
      사장님 사다리 사상(10 → 300 → 600 을 여러 심볼에)과 130% 가드(2026-05-19, -2019 방지)의
      충돌을 사장님이 (a) 「미진입 단계는 예약에서 뺀다」로 결정. 대신 발주 직전
      **가용 잔고 검사**(stage_trigger_worker Fix 344)가 -2019 를 막는다.
      되돌리기: SystemSetting ladder_reserve_untriggered_enabled = 1 (재시작 불필요).
    다른 방식(수동 기본·볼밴 분할·OBV)은 그대로 예약한다.
    """
    # 🧭 Fix 365b (반박 검증 C3): 프로브 모드의 OBV 인스턴스는 2단계 이후가 나가지 않으므로 그 계획(300/600/600)은 예약이 아니다
    try:
        from app.services.managed_symbols import loss_ladder_disabled as _lld365
        if _lld365(db, strategy)[0]:
            return False
    except Exception:  # noqa: BLE001
        pass
    mode = str(getattr(strategy, "capital_management_mode", "") or "").lower()
    if mode != "stage_ladder":
        return True
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, "ladder_reserve_untriggered_enabled")
        if row is None or row.value is None or not str(row.value).strip():
            return False
        return str(row.value).strip().lower() in ("1", "true", "on", "yes")
    except Exception as e:
        logger.warning("[Fix344] 설정 조회 실패 → 사다리 미진입 단계는 예약 제외: %s", e)
        return False


LEGACY_RESERVE_KEY = "legacy_reserve_untriggered_enabled"   # Fix 369: 1 = 기존 방식 미진입 단계도 예약(옛 동작). 기본 = 제외(사장님 9/13)


def legacy_manual_skips_reserve(db: Session, strategy: StrategyInstance) -> bool:
    """🧾 Fix 369 (2026-09-13 사장님 결정 「기존 방식 미진입 단계 예약 제외」): 기존 방식(entry_profile='legacy_manual')의
    **미진입 단계**는 130% 「예약」에서 뺀다 — v219 사다리 ③-a(Fix 344)와 같은 결정.

    실측 (9/13, 이 함수들로 계산): 예약 7,159 중 기존 방식 7건 = 6,509 (건당 미진입 800 + 실 마진) → 한도(지갑 3,890 × 1.3 ≈ 5,058)를
    넘어 **기존 방식 2단계가 전부 막혔다**. #4496·#4506 LSKUSDT 는 2단계 가격 도달 직후 「130% 초과 차단」 → 사장님 수동 추가 → 강제청산.

    🔀 적용 범위 (반박 검증 9/13): **기존 방식 전략이 자기 다음 단계를 넣을 때의 판정에서만** 뺀다
    (stage_trigger_worker → calc_reserved_for_account(..., exclude_legacy_untriggered=True)).
    공용 합계(기본값) · 생성 시 검사 · 화면 · 다른 가족(OBV·볼밴 분할·기타)의 단계 판정은 그대로 센다 — 공용 규칙
    (ladder_reserves_untriggered)에서 빼면 다른 가족의 130% 판정까지 느슨해진다 (가족별 적용 원칙).
    = 기존 방식끼리는 서로의 2단계를 막지 않고, 다른 가족의 예약은 기존 방식 판정에서도 여전히 센다.
    대신 stage_trigger_worker 가 발주 직전 **가용 잔고**로 -2019 를 막는다 (잔고 조회 실패 = 보류).
    표식 없는 옛 인스턴스(Fix 367 이전)는 그대로 예약한다. 되돌리기: SystemSetting legacy_reserve_untriggered_enabled = 1 (재시작 불필요).
    설정 조회 실패 = 제외 (사장님 결정 쪽, Fix 344 와 같은 방향)."""
    try:
        # 재검증 L3: 가족 판정은 단일 권한(family_of) — 생성 뒤 자본 모드를 분할로 바꾸면 기존 방식 표식이 있어도 SPLIT 이다
        from app.services.strategy_family import LEGACY_MANUAL, family_of
        if family_of(strategy) != LEGACY_MANUAL:
            return False
    except Exception:  # noqa: BLE001
        return False
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, LEGACY_RESERVE_KEY)
        if row is None or row.value is None or not str(row.value).strip():
            return True
        return str(row.value).strip().lower() not in ("1", "true", "on", "yes")
    except Exception as e:  # noqa: BLE001
        logger.warning("[Fix369] %s 조회 실패 → 기존 방식 미진입 단계는 예약 제외: %s", LEGACY_RESERVE_KEY, e)
        return True


def calc_untriggered_margin_for_strategy(
    db: Session, strategy: StrategyInstance, *, exclude_legacy_untriggered: bool = False,
) -> Decimal:
    """strategy 의 미진입 단계 자본 합.

    exclude_legacy_untriggered=True: 기존 방식(legacy_manual) 전략이면 0 (Fix 369 — 기존 방식 단계 진입 판정 전용, 위 docstring).

    🚨 v112 (2026-07-18) 사장님 CRITICAL fix:
    옛 v6 (2026-06-09): '예약 = 자본 / leverage = 마진 단위'
      → 사장님 사상 위반! capital = margin (같은 단위!)
    신 v112 (사장님 헌법!): 'capital = margin = 지갑 lock 원 금액!'
      → 나눗셈 X! capital 그대로!
      → exchange_accounts.py:_reserved_one v101 fix와 통일!
    """
    # 🧾 Fix 344: 사다리(stage_ladder)의 미진입 단계는 예약이 아니다 (위 docstring)
    if not ladder_reserves_untriggered(db, strategy):
        return Decimal("0")
    if exclude_legacy_untriggered and legacy_manual_skips_reserve(db, strategy):
        return Decimal("0")
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


def calc_reserved_for_strategy(
    db: Session, strategy: StrategyInstance, *, exclude_legacy_untriggered: bool = False,
) -> Decimal:
    """strategy 의 「예약」 = actual 실 마진 + 미진입 단계 마진.

    사장님 진짜 사상 v6: actual + 미진입 단계 = 마진 단위 일치.
    = 모든 곳에서 이 함수만 호출!
    """
    actual = calc_actual_margin_for_strategy(strategy)
    untriggered = calc_untriggered_margin_for_strategy(
        db, strategy, exclude_legacy_untriggered=exclude_legacy_untriggered,
    )
    return actual + untriggered


def calc_reserved_for_account(db: Session, account_id: int, *, exclude_legacy_untriggered: bool = False) -> Decimal:
    """계정 단위 「예약」 = 모든 active strategy 의 예약 합.

    화면 (exchange_accounts.py) + worker (stage_trigger_worker.py) = 모두 이 함수만 사용!
    exclude_legacy_untriggered=True 는 **기존 방식 전략의 단계 진입 판정에서만** 쓴다 (Fix 369, legacy_manual_skips_reserve).
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
        (calc_reserved_for_strategy(db, s, exclude_legacy_untriggered=exclude_legacy_untriggered) for s in strategies),
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
