import logging
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.crypto import decrypt_text
from app.core.strategy_status import ACTIVE_LIKE
from app.integrations.binance.client import BinanceClient
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.repositories.position_repository import PositionRepository
from app.repositories.strategy_repository import StrategyRepository
from app.schemas.position import ExternalPositionResponse, PositionResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/positions", tags=["positions"])


@router.get("/by-strategy/{strategy_id}/latest", response_model=PositionResponse)
def get_latest_position(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> PositionResponse:
    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")
    position = PositionRepository(db).latest_by_strategy(strategy_id)
    if not position:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Position snapshot not found")
    return PositionResponse.model_validate(position)


@router.get("/external", response_model=list[ExternalPositionResponse])
def list_external_positions(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[ExternalPositionResponse]:
    """거래소에 있지만 도구가 추적 안 하는 포지션 (도구 밖 수동 진입 등) 목록.

    2026-05-21 사장님 요구 (PHB +157 / RONIN +26 사례 후속):
      도구 밖 수동 진입한 포지션이 대시보드에 표시되지 않아 사장님이 운영 시 인지 못 함.
      이제 active strategy 가 추적 안 하는 모든 거래소 포지션을 별도 목록으로 반환.

    제외:
      - 도구가 추적 중인 포지션 (ACTIVE_LIKE strategy 와 symbol+side 매칭)
      - positionAmt = 0 (flat)

    가시성 only — 자동 청산/관리 대상 아님. 사장님이 직접 처리.
    rate limit 부담 방지: 본인 active 계정 each 에 1회 bulk 호출.
    거래소 호출 실패한 계정은 응답에 포함 안 됨 (silent skip — 다른 계정 정상 반환 우선).
    """
    accounts = db.execute(
        select(ExchangeAccount)
        .where(ExchangeAccount.user_id == user_id)
        .where(ExchangeAccount.is_active.is_(True))
    ).scalars().all()

    if not accounts:
        return []

    result: list[ExternalPositionResponse] = []
    for acc in accounts:
        try:
            client = BinanceClient(
                api_key=decrypt_text(acc.api_key_enc),
                api_secret=decrypt_text(acc.api_secret_enc),
                is_testnet=acc.is_testnet,
            )
            risk = client.get_position_risk()  # bulk — 모든 심볼
            if isinstance(risk, dict):
                risk = [risk]
        except Exception as e:
            logger.warning(
                "list_external_positions: account=%s 거래소 호출 실패 (skip): %s",
                acc.id, e,
            )
            continue

        # 본 계정의 active strategies 한 번 조회 → 매칭 차감
        tracked = db.execute(
            select(StrategyInstance.symbol, StrategyInstance.side)
            .where(StrategyInstance.exchange_account_id == acc.id)
            .where(StrategyInstance.status.in_(ACTIVE_LIKE))
            .where(StrategyInstance.is_archived.is_(False))
        ).all()
        tracked_set: set[tuple[str, str]] = {(s, sd) for (s, sd) in tracked}

        account_label = (
            f"{'testnet' if acc.is_testnet else 'mainnet'} #{acc.id}"
        )
        for p in risk:
            symbol = p.get("symbol")
            position_side = p.get("positionSide")
            if not symbol or not position_side:
                continue
            try:
                amt = Decimal(str(p.get("positionAmt", "0")))
            except (InvalidOperation, TypeError):
                continue
            if amt == 0:
                continue
            if (symbol, position_side) in tracked_set:
                continue  # 도구가 추적 중 — 외부 X

            def _safe_decimal(v) -> Decimal | None:
                if v is None or v == "":
                    return None
                try:
                    d = Decimal(str(v))
                    return d if d != 0 else None
                except (InvalidOperation, TypeError):
                    return None

            result.append(ExternalPositionResponse(
                account_id=acc.id,
                account_label=account_label,
                symbol=symbol,
                side=position_side,
                position_amt=amt,
                entry_price=_safe_decimal(p.get("entryPrice")),
                mark_price=_safe_decimal(p.get("markPrice")),
                unrealized_pnl=_safe_decimal(p.get("unRealizedProfit")),
                leverage=int(p["leverage"]) if p.get("leverage") else None,
                liquidation_price=_safe_decimal(p.get("liquidationPrice")),
                margin_type=p.get("marginType"),
            ))

    return result
