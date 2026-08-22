"""🎯 사장님 실 성공 로직 = 자본 관리 헬퍼 (v219 = 2026-08-22!).

사장님 verbatim:
"전체자산에 1-2% 진입 후 지속적인 손실이면 다시 처음 진입금액의 2배를
 하락 시작하는 보조지표가 나올때 포지션 진입"

사장님 신 요구 (2026-08-22):
"지금 300usdt로 변경해주고 운영하면서 초기값을 조정할수 있게 만들어줘"

= 1단계 = 300 USDT 고정 (default!) or 전체 자산 × 1~2% (percent 모드!)
= SystemSetting `sajangnim_default_capital` = 300 (조정 가능!)
= SystemSetting `sajangnim_capital_mode` = "fixed" (default!) or "percent"
= 2단계 = 1단계 × 2배 (외부에서 계산!)
= 3단계 = 2단계 × 2배
= 안전: available × 0.8 cap (여유 확보!)
"""
from __future__ import annotations

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

# 🎯 사장님 신 default (2026-08-22): 300 USDT 고정!
DEFAULT_STAGE1_CAPITAL = Decimal("300.0")
DEFAULT_ENTRY_PCT = 0.01              # percent 모드 시 = 1%
MAX_ENTRY_PCT = 0.02                   # percent 모드 시 = 2% max
DEFAULT_CAPITAL_MODE = "fixed"         # "fixed" (default!) or "percent"
FALLBACK_CAPITAL = Decimal("300.0")   # API 실패 시!
AVAILABLE_CAP_RATIO = Decimal("0.8")  # 여유 20% 확보!


def _get_default_capital(db) -> Decimal:
    """🎯 사장님 default 진입 자본 조회 (default 300 USDT, 운영 중 조정 가능!)"""
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


def _get_capital_mode(db) -> str:
    """자본 모드 조회 = 'fixed' or 'percent' (default 'fixed'!)"""
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, "sajangnim_capital_mode")
        if row and row.value:
            mode = str(row.value).lower().strip()
            if mode in ("fixed", "percent"):
                return mode
    except Exception:
        pass
    return DEFAULT_CAPITAL_MODE


def _get_entry_pct(db) -> float:
    """percent 모드 시 = entry_pct 조회 (default 0.01, max 0.02!)."""
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

    사장님 신 요구 (2026-08-22): 300 USDT 고정 (default!) + 운영 중 조정!

    모드:
      - "fixed" (default!): SystemSetting `sajangnim_default_capital` (default 300)
      - "percent": 전체 자산 × entry_pct (default 1%)

    안전:
      - available × 0.8 cap (여유 20% 확보!)
      - 실패 시 = 300 USDT fallback!

    Args:
        bc: BinanceClient (mainnet!)
        db: SQLAlchemy Session

    Returns:
        Decimal: 진입 자본 USDT
    """
    mode = _get_capital_mode(db)

    # 🎯 사장님 default = fixed 모드! (300 USDT!)
    if mode == "fixed":
        default_cap = _get_default_capital(db)
        # available 확인해서 안전하게!
        try:
            account = bc.get_account()
            if isinstance(account, dict):
                available = Decimal(str(account.get("availableBalance", 0)))
                if available > 0:
                    available_cap = available * AVAILABLE_CAP_RATIO
                    capital = min(default_cap, available_cap)
                    logger.info(
                        "[sajangnim_capital] 🎯 fixed 모드: default=%.2f × available_cap=%.2f → %.2f USDT",
                        float(default_cap), float(available_cap), float(capital),
                    )
                    return capital.quantize(Decimal("0.01"))
        except Exception as e:
            logger.warning("[sajangnim_capital] fixed 모드 available 조회 실패 = default 사용: %s", e)
        return default_cap.quantize(Decimal("0.01"))

    # percent 모드 (옵션!)
    try:
        account = bc.get_account()
        if not isinstance(account, dict):
            logger.warning("[sajangnim_capital] get_account 실패 = fallback!")
            return FALLBACK_CAPITAL

        total_wallet = Decimal(str(account.get("totalWalletBalance", 0)))
        available = Decimal(str(account.get("availableBalance", 0)))

        if total_wallet <= 0 or available <= 0:
            logger.warning(
                "[sajangnim_capital] 자산 0 or 마이너스! total=%s available=%s",
                total_wallet, available,
            )
            return FALLBACK_CAPITAL

        pct = _get_entry_pct(db)
        target = total_wallet * Decimal(str(pct))
        available_cap = available * AVAILABLE_CAP_RATIO
        capital = min(target, available_cap)

        if capital < FALLBACK_CAPITAL:
            logger.info(
                "[sajangnim_capital] percent 계산치 %.2f < 300 = fallback!",
                float(capital),
            )
            return FALLBACK_CAPITAL

        logger.info(
            "[sajangnim_capital] 🎯 percent 모드: total=%.2f × %.2f%% = %.2f (available cap=%.2f) → %.2f USDT",
            float(total_wallet), pct * 100, float(target),
            float(available_cap), float(capital),
        )
        return capital.quantize(Decimal("0.01"))

    except Exception as e:
        logger.warning("[sajangnim_capital] 실패 = fallback: %s", e)
        return FALLBACK_CAPITAL
