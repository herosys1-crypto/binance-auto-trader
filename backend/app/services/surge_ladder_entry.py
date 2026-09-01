"""🎯 급등 정점 사다리 — 전용 진입 경로 (Fix 268).

## 왜 공용 관문(`_create_auto_bb_strategy`)을 쓰지 않는가

검증에서 **구조적 차단 5건**이 나왔다. 그 관문을 타면 이 전략은 한 건도 못 들어간다:

  ① **합의 게이트(Fix 247)가 모집단 자체를 차단한다.**
     SHORT 이 D등급을 면하려면 4H EMA50 **DOWN**(ema_vcp_analyzer.py:181-186) +
     이치모쿠 구름 **아래**(sar_ichimoku_analyzer.py:264-269) 여야 하는데,
     이 전략의 대상은 **24h +15% 이상 급등 종목** = 정의상 그 반대다.
  ② `sajangnim_capital_ladder` 는 **전 시스템 공유** — 이 전략 자본을 그 키로 두면
     auto_short_at_top / auto_long_at_bottom / unified_15m_entry 의 1단계 자본이 함께 바뀐다.
  ③ `sajangnim_top_short_daily_limit` 은 **계정 전체 동시보유 상한**이고
     `count_active_positions` 는 side·전략 무관 전체를 센다. 활성이 상한을 넘으면
     이 로직이 한 줄도 돌기 전에 None 이 반환된다.
  ④ `STAGE3_24H_ABS_LIMIT_PCT = 15.0` — 24h ±15% 초과 SHORT 은 3단계 차단(헌법 64).
  ⑤ 템플릿 suffix 는 `_success`/`_reentry*` 만 매핑되고 그 외는 조용히 버려진다.

## 🚨 그래도 **반드시 지키는** 안전장치

우회하는 것은 위 5건뿐이다. 아래는 전부 통과해야 한다:

  - **킬스위치** (AccountKillSwitchService) — 계정 차원의 정지
  - **IP ban 가드** (is_account_banned) — 2026-08-26 418 사고
  - **중복 진입 방지** — 같은 심볼·방향에 이미 활성 전략이 있으면 만들지 않는다
  - **잔액 가드** (Fix 264) — 잔액 부족은 예외가 아니라 상태로 다룬다
  - **전용 동시 상한** — 계정 전체 상한을 무시하는 대신, 이 전략만의 슬롯을 센다
    (Fix 263 재진입 전용 슬롯과 같은 방식. 최악의 경우 총 활성 = 전체상한 + 전용슬롯)

기획서: docs/spec/SURGE_TOP10_PEAK_LADDER_SPEC_2026-09-01.md
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.strategy_status import ACTIVE_LIKE
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_template import StrategyTemplate
from app.models.surge_ladder_state import SurgeLadderState
from app.models.symbol import Symbol
from app.services.surge_peak_ladder import sl_roi_for_price_pct

logger = logging.getLogger(__name__)

__all__ = [
    "create_surge_position",
    "add_to_surge_position",
    "count_surge_active",
    "get_surge_max_concurrent",
    "STRATEGY_TYPE",
    "TEMPLATE_PREFIX",
]

STRATEGY_TYPE = "surge_peak_ladder"
TEMPLATE_PREFIX = "SURGE_LADDER"
MAX_CONCURRENT_KEY = "surge_ladder_max_concurrent"
MAX_CONCURRENT_DEFAULT = 5          # 표본 없음 — 보수적 초기값. 실적 보고 조정.


def get_surge_max_concurrent(db: Session, key: str = MAX_CONCURRENT_KEY,
                             default: int = MAX_CONCURRENT_DEFAULT) -> int:
    """이 전략 **전용** 동시 슬롯. 0 이하 = 진입 OFF (명시 존중).

    🚨 Fix 278: key/default 를 인자로 뺐다 — 중단선 전략이 같은 진입 경로를
       **자기 상한**으로 쓰기 위해서다. 기본값은 그대로라 급등 사다리는 무변경.
    """
    MAX_CONCURRENT_DEFAULT_ = default
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, key)
        if row is not None and row.value is not None and str(row.value).strip():
            return int(str(row.value).strip())
    except Exception as e:
        logger.warning("[surge_entry] %s 조회 실패 = default %d: %s",
                       key, MAX_CONCURRENT_DEFAULT_, e)
    return MAX_CONCURRENT_DEFAULT_


def count_surge_active(db: Session, prefix: str = TEMPLATE_PREFIX,
                       fallback: int = MAX_CONCURRENT_DEFAULT) -> int:
    """지금 살아 있는 이 전략의 포지션 수.

    🚨 집계 실패는 **상한으로 간주**한다 (fail-closed) — 자본이 나가는 판정이다.
    ⚠️ 템플릿 이름 매칭은 반드시 **ilike** — 이름이 대문자로 저장된다 (Fix 265 사고).
    """
    try:
        rows = db.execute(
            select(StrategyInstance.id)
            .join(StrategyTemplate,
                  StrategyTemplate.id == StrategyInstance.strategy_template_id)
            .where(StrategyInstance.status.in_(tuple(ACTIVE_LIKE)))
            .where(StrategyTemplate.name.ilike(f"{prefix}%"))
        ).scalars().all()
        return len(rows)
    except Exception as e:
        logger.warning("[surge_entry] 활성 수 조회 실패 = 상한으로 간주: %s", e)
        return fallback


def _has_active_same_symbol(db: Session, symbol: str, side: str) -> bool:
    """같은 심볼·방향에 이미 활성 전략이 있는가 (전략 종류 무관)."""
    try:
        return db.execute(
            select(StrategyInstance.id)
            .where(StrategyInstance.symbol == symbol)
            .where(StrategyInstance.side == side)
            .where(StrategyInstance.status.in_(tuple(ACTIVE_LIKE)))
            .limit(1)
        ).scalar_one_or_none() is not None
    except Exception as e:
        logger.warning("[surge_entry] 중복 검사 실패 = 있다고 간주: %s", e)
        return True                       # fail-closed


def _guards_ok(db: Session, acc: ExchangeAccount, symbol: str, side: str,
               *, prefix: str = TEMPLATE_PREFIX,
               cap_key: str = MAX_CONCURRENT_KEY,
               cap_default: int = MAX_CONCURRENT_DEFAULT) -> tuple[bool, str]:
    """우회하지 **않는** 안전장치들. 하나라도 실패하면 진입하지 않는다."""
    try:
        from app.services.account_kill_switch_service import AccountKillSwitchService
        if AccountKillSwitchService(db).is_enabled(acc.id):
            return False, "킬스위치 ON"
    except Exception as e:
        return False, f"킬스위치 확인 실패: {e}"     # fail-closed

    try:
        from app.core.api_backoff import is_account_banned
        if is_account_banned(acc.id):
            return False, "API ban 중"
    except Exception as e:
        logger.debug("[surge_entry] ban 확인 실패 (계속): %s", e)

    try:
        from app.core.redis_client import get_redis_client
        from app.services.balance_guard import check_balance_block
        blocked, d = check_balance_block(get_redis_client())
        if blocked:
            return False, (f"잔액 부족 (필요 {d.get('required')} / 가용 {d.get('available')})")
    except Exception as e:
        logger.debug("[surge_entry] 잔액 가드 확인 실패 (계속): %s", e)

    if _has_active_same_symbol(db, symbol, side):
        return False, "같은 심볼·방향 활성 전략 존재"

    _act = count_surge_active(db, prefix, cap_default)
    _cap = get_surge_max_concurrent(db, cap_key, cap_default)
    if _act >= _cap:
        return False, f"전용 동시 슬롯 소진 {_act}/{_cap}"

    return True, f"통과 (전용 슬롯 {_act}/{_cap})"


def create_surge_position(
    db: Session,
    *,
    symbol: str,
    capital: float,
    sl_price_pct: float,
    attempt_no: int,
    leverage: int = 2,
    side: str = "SHORT",
    template_prefix: str = TEMPLATE_PREFIX,
    strategy_type: str = STRATEGY_TYPE,
    cap_key: str = MAX_CONCURRENT_KEY,
    cap_default: int = MAX_CONCURRENT_DEFAULT,
) -> StrategyInstance | None:
    """급등 정점 사다리 1회분 진입. 실패하면 None (예외를 밖으로 안 던진다).

    Args:
        capital: 증거금 (USDT). CAPITAL_LADDER 에서 온다.
        sl_price_pct: **가격** 기준 손절 % (사장님 -5%/-10%). ROI 로는 여기서 역산한다.
    """
    acc = db.execute(
        select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
    ).scalar_one_or_none()
    if acc is None:
        logger.warning("[surge_entry] mainnet 계정 없음")
        return None

    ok, why = _guards_ok(db, acc, symbol, side, prefix=template_prefix,
                         cap_key=cap_key, cap_default=cap_default)
    if not ok:
        logger.info("[surge_entry] ⛔ %s %s %d시도 차단: %s", symbol, side, attempt_no, why)
        return None

    sym_row = db.execute(select(Symbol).where(Symbol.symbol == symbol)).scalar_one_or_none()
    if sym_row is None:
        logger.warning("[surge_entry] %s 심볼 미등록", symbol)
        return None

    sl_roi = sl_roi_for_price_pct(sl_price_pct, leverage)
    if sl_roi is None or sl_roi <= 0:
        logger.warning("[surge_entry] %s 손절 환산 실패 (가격%%=%s 레버=%s)",
                       symbol, sl_price_pct, leverage)
        return None

    now = datetime.now(timezone.utc)
    cap = Decimal(str(capital))
    tpl = StrategyTemplate(
        name=f"{template_prefix}_{symbol}_{side}_{now.strftime('%Y%m%d_%H%M%S')}_A{attempt_no}",
        strategy_type=strategy_type,
        side=side,
        leverage=int(leverage),
        total_capital=cap,
        # 🚨 **1단계 템플릿**이어야 한다. 다단계로 두면 risk_service 의 v130 가드
        #   (current_stage < total_stages 이면 강제손절 보류)에 걸려 손절이 안 나간다.
        #   매 시도는 독립 포지션이므로 1단계가 맞다.
        stages_config={"capitals": [float(cap)], "trigger_percents": [None], "stages_count": 1},
        stage1_capital=cap,
        tp1_percent=Decimal("15"), tp2_percent=Decimal("20"),
        tp3_percent=Decimal("25"), tp4_percent=Decimal("30"),
        tp1_qty_ratio=Decimal("25"), tp2_qty_ratio=Decimal("25"),
        tp3_qty_ratio=Decimal("25"), tp4_qty_ratio=Decimal("25"),
        stop_loss_percent_of_capital=Decimal("90"),
        is_active=True,
    )
    db.add(tpl)
    db.flush()

    try:
        from app.services.strategy_service import StrategyService
        from app.workers.auto_bb_breakdown_worker import _get_current_price
        px = _get_current_price(symbol)
        if not px or px <= 0:
            logger.warning("[surge_entry] %s 현재가 없음", symbol)
            db.rollback()
            return None
        strategy = StrategyService(db).create_strategy_instance(
            user_id=1, exchange_account_id=acc.id,
            strategy_template_id=tpl.id, symbol=symbol, side=side,
            start_price=px, leverage_override=int(leverage),
        )
    except ValueError as e:
        # 💰 Fix 264 — 잔액 부족은 예외가 아니라 상태로 다룬다
        from app.services.balance_guard import (
            is_insufficient_balance_error, mark_insufficient_balance,
        )
        if is_insufficient_balance_error(e):
            try:
                from app.core.redis_client import get_redis_client
                mark_insufficient_balance(
                    get_redis_client(), e, source=f"surge_entry {symbol}", db=db)
            except Exception:
                pass
            db.rollback()
            return None
        logger.warning("[surge_entry] %s 생성 실패: %s", symbol, e)
        db.rollback()
        return None
    except Exception as e:
        logger.warning("[surge_entry] %s 생성 예외: %s", symbol, e)
        db.rollback()
        return None

    # ── 손절: 사장님 「가격 -5%」를 ROI 로 역산해 넣는다 ──
    try:
        strategy.force_sl_enabled_override = True
        strategy.force_sl_roi_override = Decimal(str(round(sl_roi, 4)))
        db.commit()
    except Exception as e:
        logger.warning("[surge_entry] 손절 설정 실패: %s", e)
        db.rollback()

    # ── MARKET 진입 ──
    try:
        from app.models.strategy_stage_plan import StrategyStagePlan
        p1 = db.execute(
            select(StrategyStagePlan)
            .where(StrategyStagePlan.strategy_instance_id == strategy.id)
            .where(StrategyStagePlan.stage_no == 1)
        ).scalar_one_or_none()
        if p1:
            p1.trigger_price = None        # v130 MARKET 경로
            db.commit()
    except Exception as e:
        logger.warning("[surge_entry] MARKET 전환 실패: %s", e)

    try:
        from app.core.crypto import decrypt_text
        from app.services.execution_service import ExecutionService
        ExecutionService(
            db, api_key=decrypt_text(acc.api_key_enc),
            api_secret=decrypt_text(acc.api_secret_enc), is_testnet=acc.is_testnet,
        ).start_stage1(strategy.id)
    except Exception as e:
        logger.warning("[surge_entry] ❌ %s 실 진입 실패 (좀비 정리): %s", symbol, e)
        try:
            strategy.status = "STOPPED"
            strategy.last_error_message = str(e)[:500]
            db.commit()
        except Exception:
            db.rollback()
        return None

    logger.warning(
        "[surge_entry] 🎯 진입! #%s %s %s %d시도 자본 %.0f "
        "손절 가격%.1f%% (ROI %.2f%%) — 예상 최대손실 %.0f USDT",
        strategy.id, symbol, side, attempt_no, capital,
        sl_price_pct, sl_roi, capital * leverage * sl_price_pct / 100,
    )
    return strategy


def add_to_surge_position(
    db: Session, strategy: StrategyInstance, *, add_capital: float, new_sl_roi: float,
) -> bool:
    """🌟 승리 경로 — 이익 중인 포지션에 추가하고 손절 ROI 를 다시 잡는다.

    C 안: 추가 자본은 절반, **손절 금액은 고정**한다.
    그래서 추가 직후 반드시 force_sl_roi_override 를 낮춰야 한다 —
    안 하면 자본이 커진 만큼 손실도 커져 사장님 250 전제가 깨진다.
    """
    acc = db.get(ExchangeAccount, strategy.exchange_account_id)
    if acc is None:
        return False
    ok, why = _guards_ok(db, acc, strategy.symbol, strategy.side)
    # ⚠️ 중복·슬롯 검사는 **기존 포지션 추가**에는 해당하지 않는다.
    #    킬스위치·ban·잔액만 본다.
    if not ok and ("킬스위치" in why or "ban" in why or "잔액" in why):
        logger.info("[surge_entry] ⛔ #%s 추가 차단: %s", strategy.id, why)
        return False
    try:
        from app.core.crypto import decrypt_text
        from app.services.execution_service import ExecutionService
        order = ExecutionService(
            db, api_key=decrypt_text(acc.api_key_enc),
            api_secret=decrypt_text(acc.api_secret_enc), is_testnet=acc.is_testnet,
        ).add_position_now(
            strategy.id, amount_usdt=Decimal(str(add_capital)),
            order_type="MARKET", mode="reset",
        )
        if not order:
            return False
    except Exception as e:
        logger.warning("[surge_entry] #%s 추가 실패: %s", strategy.id, e)
        return False

    try:
        strategy.force_sl_roi_override = Decimal(str(round(new_sl_roi, 4)))
        db.commit()
    except Exception as e:
        # 🚨 여기서 실패하면 손실 상한이 깨진다 — 반드시 로그를 남긴다.
        logger.error(
            "[surge_entry] 🚨 #%s 추가는 됐는데 손절 재설정 실패 — 손실 상한이 깨졌다: %s",
            strategy.id, e,
        )
        db.rollback()
        return False

    logger.warning(
        "[surge_entry] ➕ #%s %s 이익구간 추가 %.0f USDT — 손절 ROI %.2f%% 로 재설정 "
        "(손실 금액 고정)", strategy.id, strategy.symbol, add_capital, new_sl_roi,
    )
    return True
