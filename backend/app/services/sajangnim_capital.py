"""🎯 사장님 실 성공 로직 = 자본 관리 헬퍼 (v219 = 2026-08-22!).

사장님 verbatim:
"전체자산에 1-2% 진입 후 지속적인 손실이면 다시 처음 진입금액의 2배를
 하락 시작하는 보조지표가 나올때 포지션 진입"

= 1단계 = 전체 자산 × 1~2%
= 2단계 = 1단계 × 2배
= 3단계 = 2단계 × 2배
= 안전: available × 0.8 cap (여유 확보!)
"""
from __future__ import annotations

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

DEFAULT_ENTRY_PCT = 0.01  # 1% default (안전!)
MAX_ENTRY_PCT = 0.02       # 2% max (사장님 상한!)
DEFAULT_FALLBACK = Decimal("500.0")  # API 실패 시 최소!
AVAILABLE_CAP_RATIO = Decimal("0.8")  # 여유 20% 확보!


def _get_entry_pct(db) -> float:
    """SystemSetting에서 entry_pct 조회 (default 0.01, max 0.02!)."""
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, "sajangnim_entry_pct")
        if row and row.value:
            pct = float(row.value)
            return max(0.001, min(MAX_ENTRY_PCT, pct))
    except Exception:
        pass
    return DEFAULT_ENTRY_PCT


def compute_stage1_capital(bc, db) -> Decimal:
    """🎯 사장님 1단계 진입 자본 계산!

    1. Binance API에서 전체 자산 조회!
    2. entry_pct (default 1%) 계산!
    3. available × 0.8 cap (여유 확보!)
    4. min = 500 USDT (Binance 최소 주문!)

    Args:
        bc: BinanceClient (mainnet!)
        db: SQLAlchemy Session

    Returns:
        Decimal: 진입 자본 USDT
    """
    try:
        # 1. Binance API 자산 조회!
        account = bc.get_account()
        if not isinstance(account, dict):
            logger.warning("[sajangnim_capital] get_account 실패 = fallback!")
            return DEFAULT_FALLBACK

        total_wallet = Decimal(str(account.get("totalWalletBalance", 0)))
        available = Decimal(str(account.get("availableBalance", 0)))

        if total_wallet <= 0 or available <= 0:
            logger.warning(
                "[sajangnim_capital] 자산 0 or 마이너스! total=%s available=%s",
                total_wallet, available,
            )
            return DEFAULT_FALLBACK

        # 2. entry_pct 계산!
        pct = _get_entry_pct(db)
        target = total_wallet * Decimal(str(pct))

        # 3. available × 0.8 cap!
        available_cap = available * AVAILABLE_CAP_RATIO
        capital = min(target, available_cap)

        # 4. 최소 500 USDT!
        if capital < DEFAULT_FALLBACK:
            logger.info(
                "[sajangnim_capital] 계산치 %.2f < 500 = fallback!",
                float(capital),
            )
            return DEFAULT_FALLBACK

        logger.info(
            "[sajangnim_capital] 🎯 사장님 자본: total=%.2f × %.2f%% = %.2f (available cap=%.2f) → %.2f USDT",
            float(total_wallet), pct * 100, float(target),
            float(available_cap), float(capital),
        )
        return capital.quantize(Decimal("0.01"))

    except Exception as e:
        logger.warning("[sajangnim_capital] 실패 = fallback: %s", e)
        return DEFAULT_FALLBACK
