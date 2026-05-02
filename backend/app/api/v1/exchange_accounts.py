"""Exchange Account 등록 / 조회 API.

운영자가 Swagger UI 또는 프론트엔드에서 거래소(Binance) API 키를 등록할 수 있는 엔드포인트.
api_key / api_secret 은 Fernet 으로 암호화되어 DB 에 저장된다.
삭제(DELETE)는 보안 사고 시 Kill-switch (`/admin/kill-switch/{id}/enable`) 로 대체.
"""
import logging
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.crypto import encrypt_text, decrypt_text
from app.integrations.binance.client import BinanceClient
from app.models.exchange_account import ExchangeAccount

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/exchange-accounts", tags=["exchange-accounts"])


class ExchangeAccountCreate(BaseModel):
    exchange_name: Literal["binance"] = Field(default="binance")
    market_type: Literal["usds_m_futures"] = Field(default="usds_m_futures")
    api_key: str = Field(..., min_length=10, max_length=200, description="거래소 API key (평문). 저장 시 자동 암호화됨")
    api_secret: str = Field(..., min_length=10, max_length=200, description="거래소 API secret (평문). 저장 시 자동 암호화됨")
    passphrase: str | None = Field(default=None, max_length=200, description="OKX 등 일부 거래소가 요구하는 추가 비밀번호. Binance 는 None")
    is_testnet: bool = Field(default=False, description="True 이면 testnet, False 이면 mainnet")
    hedge_mode_enabled: bool = Field(default=True, description="헤지모드 사용 여부 (Binance Futures 양방향 포지션)")


class ExchangeAccountResponse(BaseModel):
    """API key/secret 은 절대 응답에 포함하지 않는다."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    exchange_name: str
    market_type: str
    is_testnet: bool
    hedge_mode_enabled: bool
    is_active: bool


@router.post("", response_model=ExchangeAccountResponse, status_code=status.HTTP_201_CREATED)
def create_exchange_account(
    payload: ExchangeAccountCreate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> ExchangeAccountResponse:
    """거래소 API 키를 등록한다. api_key / api_secret 은 자동으로 암호화되어 저장된다."""
    try:
        api_key_enc = encrypt_text(payload.api_key)
        api_secret_enc = encrypt_text(payload.api_secret)
        passphrase_enc = encrypt_text(payload.passphrase) if payload.passphrase else None
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to encrypt credentials: {e}",
        ) from e

    account = ExchangeAccount(
        user_id=user_id,
        exchange_name=payload.exchange_name,
        market_type=payload.market_type,
        api_key_enc=api_key_enc,
        api_secret_enc=api_secret_enc,
        passphrase_enc=passphrase_enc,
        is_testnet=payload.is_testnet,
        hedge_mode_enabled=payload.hedge_mode_enabled,
        is_active=True,
    )
    db.add(account)
    try:
        db.commit()
        db.refresh(account)
    except Exception as e:  # pragma: no cover
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    return ExchangeAccountResponse.model_validate(account)


@router.get("", response_model=list[ExchangeAccountResponse])
def list_exchange_accounts(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> list[ExchangeAccountResponse]:
    """본인이 등록한 거래소 계정 목록을 조회한다 (api_key/secret 미포함)."""
    rows = db.execute(
        select(ExchangeAccount)
        .where(ExchangeAccount.user_id == user_id)
        .order_by(ExchangeAccount.id.desc())
    ).scalars().all()
    return [ExchangeAccountResponse.model_validate(r) for r in rows]


class BalanceResponse(BaseModel):
    """거래소 잔액 + 마진 사용 현황 (Binance /fapi/v2/account 기반)."""

    exchange_account_id: int
    is_testnet: bool
    asset: str = "USDT"
    # 지갑 잔액 (실현 손익 누적)
    total_wallet_balance: Decimal
    # 미실현 손익 (모든 활성 포지션)
    total_unrealized_pnl: Decimal
    # 마진 잔액 (wallet + unrealized)
    total_margin_balance: Decimal
    # 사용 가능한 잔액 (새 포지션 진입 가능 액수)
    available_balance: Decimal
    # 활성 포지션의 초기 마진
    total_position_initial_margin: Decimal
    # 미체결 주문의 초기 마진
    total_open_order_initial_margin: Decimal
    # 유지 마진 (강제 청산 임계)
    total_maint_margin: Decimal
    # 마진 비율 (margin_balance 대비 maint_margin) — 1.0 이상이면 청산 위험
    margin_ratio_pct: Decimal
    # 활성 포지션 수
    open_positions_count: int


@router.get("/{exchange_account_id}/balance", response_model=BalanceResponse)
def get_balance(
    exchange_account_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> BalanceResponse:
    """거래소 잔액 + 마진 사용 현황 실시간 조회.

    UI 의 잔액 카드 + 새 전략 진입 시 사전 체크용. mainnet/testnet 모두 지원.
    """
    account = db.execute(
        select(ExchangeAccount)
        .where(ExchangeAccount.id == exchange_account_id)
        .where(ExchangeAccount.user_id == user_id)
    ).scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exchange account not found")

    try:
        client = BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=account.is_testnet,
        )
        info = client.get_account()
    except Exception as e:
        logger.error("get_balance Binance call failed: account_id=%s error=%s", exchange_account_id, e)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Binance API 호출 실패: {e}") from e

    def _d(v) -> Decimal:
        return Decimal(str(v)) if v is not None else Decimal("0")

    total_wallet = _d(info.get("totalWalletBalance"))
    total_unrealized = _d(info.get("totalUnrealizedProfit"))
    total_margin = _d(info.get("totalMarginBalance"))
    total_init_margin = _d(info.get("totalPositionInitialMargin"))
    total_open_order_margin = _d(info.get("totalOpenOrderInitialMargin"))
    total_maint = _d(info.get("totalMaintMargin"))
    available = _d(info.get("availableBalance"))
    margin_ratio = (total_maint / total_margin * 100).quantize(Decimal("0.01")) if total_margin > 0 else Decimal("0")
    positions = info.get("positions") or []
    open_count = sum(1 for p in positions if _d(p.get("positionAmt")) != 0)

    return BalanceResponse(
        exchange_account_id=exchange_account_id,
        is_testnet=account.is_testnet,
        total_wallet_balance=total_wallet,
        total_unrealized_pnl=total_unrealized,
        total_margin_balance=total_margin,
        available_balance=available,
        total_position_initial_margin=total_init_margin,
        total_open_order_initial_margin=total_open_order_margin,
        total_maint_margin=total_maint,
        margin_ratio_pct=margin_ratio,
        open_positions_count=open_count,
    )
