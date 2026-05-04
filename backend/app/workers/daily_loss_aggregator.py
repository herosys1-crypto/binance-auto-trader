"""Daily loss aggregator — unrealized PnL 합산 + kill-switch 자동 발동.

배경 (audit 2026-05-04 발견):
`AccountDailyLossLimiterService.update_pnl_and_check` 가 호출되는 곳이 0건이라
일일 손실 한도 안전장치가 무력 상태였음. 이 worker 가 그 missing piece —
주기적으로 active 계정의 PnL 을 집계해서 한도 초과 시 kill-switch 트리거.

v1 동작 (이번 PR):
- `settings.daily_loss_limit_usdt` 가 설정돼야 작동 (None / 0 이면 no-op).
- 매 1분마다 active ExchangeAccount 별로:
  * kill-switch 가 이미 enabled 면 skip
  * 활성 strategy 의 unrealized_pnl 합산 (현재 at-risk 금액)
  * realized_pnl 은 v1 에서는 기존 account_daily_risk_limit row 값 그대로 (snapshot
    메커니즘 아직 없음 — v2 작업)
  * AccountDailyLossLimiterService.update_pnl_and_check 호출
  * breach 시 자동 kill-switch + Sentry capture + 로그
- "안전장치" 의미상 신규 거래만 차단 — 기존 포지션은 자동 청산 안 함 (TP/SL 정상 작동).

v2 향후 (별도 작업):
- realized_pnl 의 일일 누적: stream_service 의 EXIT FILLED 핸들링 시 incrementally
  account_daily_risk_limit.realized_pnl 갱신. EOD snapshot 도 같이.
- 일별 한도를 ExchangeAccount.daily_loss_limit_usdt 컬럼으로 옮겨 계정별 다른 한도.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.sentry import capture_strategy_event
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.services.account_daily_loss_limiter import AccountDailyLossLimiterService
from app.services.account_kill_switch_service import AccountKillSwitchService

logger = logging.getLogger(__name__)

__all__ = ["run_daily_loss_check_once", "_ACTIVE_STATUSES_FOR_PNL"]


# 어느 status 의 strategy 가 PnL 집계 대상인가:
# 활성 포지션 있는 모든 status (1~10단계 OPEN + TP partial). PENDING (LIMIT 미체결) 은
# 포지션 없으므로 제외. STOPPING 은 포지션 잔재 가능 → 포함.
_ACTIVE_STATUSES_FOR_PNL = (
    {f"STAGE{n}_OPEN" for n in range(1, 11)}
    | {f"TP{n}_DONE_PARTIAL" for n in range(1, 6)}
    | {"STOPPING"}
)


def _resolve_account_limit(acc: ExchangeAccount) -> Decimal | None:
    """계정별 한도 우선 → global → None (비활성).

    - acc.daily_loss_limit_usdt > 0 → 그 값 사용 (계정 override)
    - 그 외 (NULL / 0 / 음수) → settings.daily_loss_limit_usdt (global)
    - global 도 None / 0 → None (비활성)
    """
    acc_limit = acc.daily_loss_limit_usdt
    if acc_limit is not None:
        try:
            v = Decimal(str(acc_limit))
            if v > 0:
                return v
        except Exception:
            pass
    global_limit = settings.daily_loss_limit_usdt
    if global_limit and global_limit > 0:
        return Decimal(str(global_limit))
    return None


def run_daily_loss_check_once() -> None:
    """1회 daily loss 체크 + 필요 시 kill-switch 발동.

    한도 해석 (2026-05-04 v3):
    - ExchangeAccount.daily_loss_limit_usdt 가 양수면 그것 우선
    - 아니면 settings.daily_loss_limit_usdt (global) 사용
    - 둘 다 None/0 이면 그 계정 skip (기능 비활성)
    """
    db = SessionLocal()
    try:
        kill_switch = AccountKillSwitchService(db)
        accounts = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_active.is_(True))
        ).scalars().all()
        for acc in accounts:
            try:
                # 계정별 한도 우선 → global → 비활성.
                limit = _resolve_account_limit(acc)
                if limit is None:
                    continue  # 이 계정 한도 비활성

                # kill-switch 가 이미 활성이면 재트리거 불필요 (idempotent 이지만 노이즈 ↓).
                if kill_switch.is_enabled(acc.id):
                    continue

                # 활성 strategy 의 unrealized_pnl 합산. 빈 집합이면 0.
                total_unrealized_raw = db.execute(
                    select(func.coalesce(func.sum(StrategyInstance.unrealized_pnl), 0))
                    .where(StrategyInstance.exchange_account_id == acc.id)
                    .where(StrategyInstance.status.in_(_ACTIVE_STATUSES_FOR_PNL))
                ).scalar()
                total_unrealized = Decimal(str(total_unrealized_raw or 0))

                # v1: realized 는 기존 row 값 그대로 (없으면 0). v2 에서 stream_service
                # EXIT FILLED 핸들링 시 account_daily_risk_limit.realized_pnl 누적 예정.
                limiter = AccountDailyLossLimiterService(db)
                existing = limiter.get_or_create_today_limit(
                    exchange_account_id=acc.id,
                    daily_loss_limit_amount=limit,
                )
                existing_realized = Decimal(str(existing.realized_pnl or 0))

                breached = limiter.update_pnl_and_check(
                    exchange_account_id=acc.id,
                    realized_pnl=existing_realized,
                    unrealized_pnl_snapshot=total_unrealized,
                    daily_loss_limit_amount=limit,
                )
                if breached:
                    logger.critical(
                        "Daily loss limit breached for account %s — total=%s, limit=%s. Kill-switch triggered.",
                        acc.id, existing_realized + total_unrealized, limit,
                    )
                    capture_strategy_event(
                        f"Daily loss limit breached for account {acc.id}",
                        level="fatal",
                        account_id=acc.id,
                        extras={
                            "total_pnl": str(existing_realized + total_unrealized),
                            "realized_pnl": str(existing_realized),
                            "unrealized_pnl": str(total_unrealized),
                            "limit": str(limit),
                        },
                        tags={"event_type": "DAILY_LOSS_LIMIT_BREACHED"},
                    )
            except Exception as e:
                logger.exception("daily_loss_check failed for account %s: %s", acc.id, e)
                capture_strategy_event(
                    f"daily_loss_check failed for account {acc.id}",
                    level="error", error=e, account_id=acc.id,
                    tags={"event_type": "DAILY_LOSS_CHECK_FAILED"},
                )
    finally:
        db.close()
