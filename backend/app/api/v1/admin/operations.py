"""Admin — write actions (Kill-Switch + Whitelist + Telegram test + Symbol sync).

운영자 수동 액션 endpoint 모음.
2026-05-14 Phase 4 split: 기존 admin.py 에서 분리.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.crypto import decrypt_text
from app.integrations.binance.client import BinanceClient
from app.repositories.exchange_account_repository import ExchangeAccountRepository
from app.schemas.common import MessageResponse
from app.services.account_kill_switch_service import AccountKillSwitchService
from app.services.notification_service import NotificationService
from app.services.symbol_sync_service import SymbolSyncService

router = APIRouter(prefix="/admin", tags=["admin"])


# =====================================================================
# Telegram / Symbol sync
# =====================================================================
@router.post("/test-telegram", response_model=MessageResponse)
def test_telegram(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> MessageResponse:
    """Telegram 연결 테스트 — 한국어 + 이모지 포함된 시스템 알림 1건 발송.

    실제 발송 성공 여부를 검증해 운영자에게 정확한 결과를 알려준다.
    NotificationService.send() 가 silent-fail 하므로 send_status / body 를 직접 검사.
    """
    notification = NotificationService(db).send_system_alert(
        title="🤖 [관리 테스트] 텔레그램 연결 확인",
        body=(
            "✅ 백엔드 → 텔레그램 알림 라인이 정상 동작합니다.\n"
            "📡 채널         : TELEGRAM\n"
            "🔧 발송 경로    : admin API (/admin/test-telegram)\n"
            "📦 메시지 포맷  : HTML (parse_mode=HTML)\n"
            "👤 운영자       : herosys1@gmail.com\n"
            "\n"
            "이제 단계 진입 / 익절 / 손절 / Kill-Switch / 청산 임박 알림이\n"
            "자동으로 이 채널로 발송됩니다."
        ),
    )
    if (notification.send_status or "").upper() == "FAILED":
        # body 끝의 [send_error] ... 부분 추출
        body = notification.body or ""
        err = "unknown"
        if "[send_error]" in body:
            err = body.split("[send_error]", 1)[1].strip()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Telegram 발송 실패 — {err}",
        )
    return MessageResponse(message=f"Telegram 발송 완료 (notification id={notification.id}, ext_id={notification.external_message_id})")


@router.post("/symbol-sync", response_model=MessageResponse)
def symbol_sync(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> MessageResponse:
    # 2026-05-04 audit fix: user_id 전달 — 다른 user 의 API key 로 symbol-sync 하던 결함 차단.
    account = ExchangeAccountRepository(db).get_first_active_binance(user_id=user_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No active Binance account for current user")
    client = BinanceClient(
        api_key=decrypt_text(account.api_key_enc),
        api_secret=decrypt_text(account.api_secret_enc),
        is_testnet=account.is_testnet,
    )
    count = SymbolSyncService(db, client).sync()
    return MessageResponse(message=f"Synced {count} symbols")


# =====================================================================
# Helper — account ownership 검증 (보안)
# =====================================================================
def _verify_account_ownership(db: Session, exchange_account_id: int, user_id: int) -> None:
    """2026-05-04 audit fix: 인증된 user 라도 자기 계정만 조작 가능하도록.

    이전엔 admin endpoint 라고 user_id 검증 없이 모든 계정의 kill-switch 조작 가능.
    multi-user 시 다른 user 의 계정을 임의로 enable/disable 할 수 있는 보안 결함.
    """
    from app.models.exchange_account import ExchangeAccount
    from sqlalchemy import select
    acc = db.execute(
        select(ExchangeAccount)
        .where(ExchangeAccount.id == exchange_account_id)
        .where(ExchangeAccount.user_id == user_id)
    ).scalar_one_or_none()
    if not acc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exchange account #{exchange_account_id} not found (또는 본인 소유 아님)",
        )


# ============================================================================
# System Settings — 운영자 런타임 토글 (2026-05-07 사용자 요청)
# ============================================================================
class WhitelistSettingResponse(BaseModel):
    """화이트리스트 운영 상태."""
    enabled: bool
    allowed_symbols: list[str]
    env_configured: bool  # env 에 ALLOWED_SYMBOLS_CSV 값이 있는지 (없으면 toggle 켜도 무의미)


class WhitelistSettingUpdate(BaseModel):
    enabled: bool


@router.get("/settings/whitelist", response_model=WhitelistSettingResponse)
def get_whitelist_setting(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> WhitelistSettingResponse:
    """현재 화이트리스트 토글 상태 + env 의 허용 심볼 목록."""
    from app.core.config import settings
    from app.services.system_settings_service import SystemSettingsService

    allowed = settings.allowed_symbols_set
    env_configured = allowed is not None
    enabled = SystemSettingsService(db).is_whitelist_enabled(default_from_env=env_configured)
    return WhitelistSettingResponse(
        enabled=enabled,
        allowed_symbols=sorted(allowed) if allowed else [],
        env_configured=env_configured,
    )


@router.patch("/settings/whitelist", response_model=WhitelistSettingResponse)
def update_whitelist_setting(
    payload: WhitelistSettingUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> WhitelistSettingResponse:
    """화이트리스트 토글 변경 (DB 영속). 즉시 적용 — strategy 생성 시점에 반영."""
    from app.core.config import settings
    from app.services.system_settings_service import SystemSettingsService

    SystemSettingsService(db).set(
        "whitelist_enabled",
        payload.enabled,
        updated_by=user_id,
        description="화이트리스트 적용 여부 (운영자 UI 토글)",
    )
    allowed = settings.allowed_symbols_set
    return WhitelistSettingResponse(
        enabled=payload.enabled,
        allowed_symbols=sorted(allowed) if allowed else [],
        env_configured=allowed is not None,
    )


# =====================================================================
# Kill-Switch — 수동 enable / disable
# =====================================================================
@router.post("/kill-switch/{exchange_account_id}/enable", response_model=MessageResponse)
def enable_kill_switch(
    exchange_account_id: int,
    reason_code: str = "MANUAL",
    reason_message: str = "Manually triggered by admin",
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> MessageResponse:
    _verify_account_ownership(db, exchange_account_id, user_id)
    AccountKillSwitchService(db).trigger(
        exchange_account_id=exchange_account_id,
        reason_code=reason_code,
        reason_message=reason_message,
    )
    return MessageResponse(message=f"Kill switch enabled on account {exchange_account_id}")


@router.post("/kill-switch/{exchange_account_id}/disable", response_model=MessageResponse)
def disable_kill_switch(
    exchange_account_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> MessageResponse:
    """Kill-Switch 해제 + 오늘의 daily_risk_limit row TRIGGERED → ACTIVE 리셋.

    배경 (2026-05-07 사용자 운영 발견): KS 만 clear 하고 row.status 가 TRIGGERED 로
    남아있으면 update_pnl_and_check 가 'breached and status != TRIGGERED' 가드로
    재발동 안 함. → KS 가 해제된 채 손실이 더 커져도 자동 차단 실패.

    이 fix: KS clear 시 row 도 함께 ACTIVE 로 리셋해서 다음 사이클부터 다시
    임계 검사 가능. (PR #15 의 실 운영 검증에서 발견된 latent 버그)
    """
    from datetime import date
    from app.models.account_daily_risk_limit import AccountDailyRiskLimit
    from sqlalchemy import select as _s

    _verify_account_ownership(db, exchange_account_id, user_id)
    AccountKillSwitchService(db).clear(exchange_account_id)

    # 오늘의 daily_risk_limit row 가 TRIGGERED 면 ACTIVE 로 리셋 (재검사 가능 상태로).
    row = db.execute(
        _s(AccountDailyRiskLimit)
        .where(AccountDailyRiskLimit.exchange_account_id == exchange_account_id)
        .where(AccountDailyRiskLimit.trading_date == date.today())
    ).scalar_one_or_none()
    if row and row.status == "TRIGGERED":
        row.status = "ACTIVE"
        db.commit()
    return MessageResponse(message=f"Kill switch cleared on account {exchange_account_id}")
