"""Exchange Account 등록 / 조회 API.

운영자가 Swagger UI 또는 프론트엔드에서 거래소(Binance) API 키를 등록할 수 있는 엔드포인트.
api_key / api_secret 은 Fernet 으로 암호화되어 DB 에 저장된다.
삭제(DELETE)는 보안 사고 시 Kill-switch (`/admin/kill-switch/{id}/enable`) 로 대체.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.crypto import encrypt_text
from app.models.exchange_account import ExchangeAccount

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
