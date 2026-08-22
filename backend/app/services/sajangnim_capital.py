"""🎯 사장님 실 성공 로직 = 자본 관리 헬퍼 (v219 = 2026-08-22!).

사장님 verbatim (초기 사상, 2026-08-22):
"전체자산에 1-2% 진입 후 지속적인 손실이면 다시 처음 진입금액의 2배를
 하락 시작하는 보조지표가 나올때 포지션 진입"

🌟 사장님 신 명확 규정 (2026-08-22 저녁!):
"전체자산에 대해서는 시스템에서 고려 대상이 아니야
 초기 금액과 다음 2배 그리고 다음은 투자금 전체의 2배야"
"300 600 이거네"

🚨 사장님 최종 결정 (2026-08-22 저녁 v219 최종!):
"2단계에서 끝이나야하고 3단계는 가지 않아야 합니다."

= 시스템 = 전체 자산 무관! (사장님 판단!)
= 마틴게일 (STRICT!):
  - 1단계 = 초기 금액 (default 300 USDT, 사장님 조정!)
  - 2단계 = 이전 진입금액 × 2 (예: 300 × 2 = 600)
  - **3단계 = 금지!** (2단계에서 STOP!) ⭐ 손실 폭발 방지!

= MAX_REENTRY_COUNT = 1! (v202 = 2에서 → 1로!)
= 사장님 자본 보호 최우선!
"""
from __future__ import annotations

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

# 🎯 사장님 default (2026-08-22): 300 USDT 초기 금액!
DEFAULT_STAGE1_CAPITAL = Decimal("300.0")
FALLBACK_CAPITAL = Decimal("300.0")   # 실패 시!


def _get_default_capital(db) -> Decimal:
    """🎯 사장님 초기 금액 조회 (default 300 USDT, 운영 중 조정 가능!)"""
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, "sajangnim_default_capital")
        if row and row.value:
            val = Decimal(str(row.value))
            if val > 0:
                return val
    except Exception:
        pass
    return DEFAULT_STAGE1_CAPITAL


def compute_stage1_capital(bc, db) -> Decimal:
    """🎯 사장님 1단계 = 초기 금액 (300 USDT default!)

    사장님 규정: 전체 자산 = 시스템 고려 X! 초기 금액만!

    Args:
        bc: BinanceClient (호환성 유지, 미사용!)
        db: SQLAlchemy Session

    Returns:
        Decimal: 초기 진입 자본 USDT
    """
    default_cap = _get_default_capital(db)
    logger.info(
        "[sajangnim_capital] 🎯 1단계 초기 자본: %.2f USDT",
        float(default_cap),
    )
    return default_cap.quantize(Decimal("0.01"))


MAX_REENTRY_STAGE = 2  # 🚨 사장님 최종 (2026-08-22): 2단계에서 STOP! (3단계 X!)


def compute_reentry_capital(stage: int, previous_capitals: list[Decimal] | list[float]) -> Decimal | None:
    """🎯 사장님 신 마틴게일 (v219 최종 확정!)

    사장님 최종 규정 (2026-08-22 저녁!):
    "2단계에서 끝이나야하고 3단계는 가지 않아야 합니다."

    - stage=1 (초기!): 이 함수 호출 X = compute_stage1_capital 사용!
    - stage=2: 이전 진입 × 2 (예: 300 × 2 = 600!)
    - stage>=3: **None 반환!** (사장님 STOP!)

    Args:
        stage: 다음 진입 단계 번호 (2만 유효!)
        previous_capitals: 이전까지 실 진입한 자본 리스트 (1단계!)

    Returns:
        Decimal: stage=2 시 자본 (600 USDT!)
        None: stage>=3 = STOP! (사장님 규정!)
    """
    if stage <= 1:
        raise ValueError(f"compute_reentry_capital = stage >= 2! (got {stage})")
    if not previous_capitals:
        raise ValueError("compute_reentry_capital = previous_capitals 필수!")

    if stage > MAX_REENTRY_STAGE:
        logger.info(
            "[sajangnim_capital] 🚨 사장님 STOP! stage=%d > MAX=%d (2단계에서 끝!)",
            stage, MAX_REENTRY_STAGE,
        )
        return None

    _prev = [Decimal(str(c)) for c in previous_capitals]

    # stage=2 = 이전 진입 × 2!
    result = _prev[-1] * Decimal("2")
    logger.info(
        "[sajangnim_capital] 🎯 2단계 (마지막!): 이전 %.2f × 2 = %.2f USDT",
        float(_prev[-1]), float(result),
    )

    return result.quantize(Decimal("0.01"))
