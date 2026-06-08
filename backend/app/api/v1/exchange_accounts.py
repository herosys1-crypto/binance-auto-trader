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
    daily_loss_limit_usdt: Decimal | None = Field(
        default=None, ge=0,
        description=(
            "이 계정 전용 일일 손실 한도 (USDT). 양수면 daily_loss_aggregator 가 발동 시 "
            "kill-switch 자동 활성. NULL/0 이면 settings.daily_loss_limit_usdt (global) "
            "폴백, global 도 없으면 기능 비활성."
        ),
    )


class ExchangeAccountResponse(BaseModel):
    """API key/secret 은 절대 응답에 포함하지 않는다."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    exchange_name: str
    market_type: str
    is_testnet: bool
    hedge_mode_enabled: bool
    is_active: bool
    daily_loss_limit_usdt: Decimal | None = None


class ExchangeAccountDailyLimitUpdate(BaseModel):
    """daily_loss_limit_usdt 만 부분 수정. NULL 보내면 global 폴백 모드로 전환."""

    daily_loss_limit_usdt: Decimal | None = Field(
        default=None, ge=0,
        description="None 이면 global 폴백, 양수면 계정 override, 0 이면 비활성.",
    )


class ExchangeAccountCredentialsUpdate(BaseModel):
    """API 키 회전 (testnet ↔ mainnet 전환 포함). 2026-05-07 신규.

    사용 사례:
    - testnet 운영 후 mainnet 전환 — 새 mainnet 키 + is_testnet=False 동시 변경
    - 노출된 mainnet 키 정기 회전 — 새 키만 변경 (is_testnet 미지정)
    - 키 갱신 (Binance 만료 등)

    안전 가드 (서버측):
    1. 새 키로 Binance 호출 검증 (`get_account`) 후 저장 — 실패 시 DB 변경 0
    2. is_testnet 변경 시 이 계정의 활성 strategy 존재하면 거부
       (testnet 포지션 + mainnet 키 조합은 좀비/혼란 발생)
    """
    api_key: str = Field(..., min_length=10, max_length=200, description="새 거래소 API key (평문)")
    api_secret: str = Field(..., min_length=10, max_length=200, description="새 거래소 API secret (평문)")
    passphrase: str | None = Field(
        default=None, max_length=200,
        description="OKX 등 일부 거래소가 요구. 명시적으로 공백 보내면 NULL 처리. 미지정 시 기존 값 보존.",
    )
    is_testnet: bool | None = Field(
        default=None,
        description="None 이면 기존 값 유지. True/False 명시 시 환경 전환 (활성 strategy 가드 적용).",
    )
    hedge_mode_enabled: bool | None = Field(
        default=None,
        description="None 이면 기존 값 유지. 거래소 헤지모드 설정과 일치해야 함.",
    )


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
        daily_loss_limit_usdt=payload.daily_loss_limit_usdt,
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


@router.patch("/{exchange_account_id}/credentials", response_model=ExchangeAccountResponse)
def update_credentials(
    exchange_account_id: int,
    payload: ExchangeAccountCredentialsUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> ExchangeAccountResponse:
    """거래소 API 키 회전 + 옵션으로 testnet ↔ mainnet 전환 (2026-05-07).

    검증 흐름:
    1. 계정 소유 확인
    2. is_testnet 변경 의도면: 이 계정의 활성 strategy 가 0건이어야 함 (가드)
    3. 새 키로 Binance get_account 호출 — 인증 실패 시 거부
    4. Fernet 암호화 + DB commit
    5. NotificationService.send_system_alert 로 변경 이력 기록 (audit trail)
    """
    from app.core.strategy_status import TERMINAL_STATUSES
    from app.models.strategy_instance import StrategyInstance

    account = db.execute(
        select(ExchangeAccount)
        .where(ExchangeAccount.id == exchange_account_id)
        .where(ExchangeAccount.user_id == user_id)
    ).scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exchange account not found")

    # 1) is_testnet 토글 가드 — 활성 strategy 가 있으면 거부 (포지션 mismatch 방지)
    will_change_env = payload.is_testnet is not None and payload.is_testnet != account.is_testnet
    if will_change_env:
        active_count = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.exchange_account_id == exchange_account_id)
            .where(StrategyInstance.status.notin_(TERMINAL_STATUSES))
            .where(StrategyInstance.is_archived.is_(False))
        ).all()
        if active_count:
            old_env = "testnet" if account.is_testnet else "mainnet"
            new_env = "testnet" if payload.is_testnet else "mainnet"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"⚠️ 환경 전환 불가 ({old_env} → {new_env}): 진행 중인 전략이 {len(active_count)}건 있습니다.\n\n"
                    "📌 testnet 포지션을 mainnet 키로 추적하면 좀비/혼란이 발생합니다.\n\n"
                    "💡 해결: 모든 활성 전략을 「⏸ 정지」 또는 「🛑 긴급 종료」 한 후 다시 시도하세요."
                ),
            )

    # 2) 새 키로 Binance 호출 검증 — 실패 시 DB 변경 0
    effective_is_testnet = payload.is_testnet if payload.is_testnet is not None else account.is_testnet
    try:
        client = BinanceClient(
            api_key=payload.api_key,
            api_secret=payload.api_secret,
            is_testnet=effective_is_testnet,
        )
        client.get_account()  # 인증 검증 (잔액 확인 부가효과)
    except Exception as e:
        logger.warning(
            "PATCH credentials Binance call failed: account_id=%s is_testnet=%s error=%s",
            exchange_account_id, effective_is_testnet, e,
        )
        env_str = "testnet" if effective_is_testnet else "mainnet"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"🔑 새 API 키로 Binance ({env_str}) 인증 실패\n\n"
                f"📋 상세: {e}\n\n"
                "💡 점검 사항:\n"
                "  • API 키/시크릿 정확히 복사했는지 (앞뒤 공백 X)\n"
                "  • Futures 권한 활성 (Spot Trading 만 활성이면 거부)\n"
                "  • IP Whitelist 에 VPS IP (152.42.232.195) 등록\n"
                "  • testnet/mainnet 환경 일치 (testnet 키를 mainnet 으로 등록 X)"
            ),
        ) from e

    # 3) 검증 성공 — 암호화 + 저장
    try:
        account.api_key_enc = encrypt_text(payload.api_key)
        account.api_secret_enc = encrypt_text(payload.api_secret)
        if payload.passphrase is not None:
            account.passphrase_enc = encrypt_text(payload.passphrase) if payload.passphrase else None
        if payload.is_testnet is not None:
            account.is_testnet = payload.is_testnet
        if payload.hedge_mode_enabled is not None:
            account.hedge_mode_enabled = payload.hedge_mode_enabled
        db.commit()
        db.refresh(account)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"키 저장 실패 (암호화 또는 DB): {e}",
        ) from e

    # 4) Audit 알림 — 키 회전은 보안 사건이라 텔레그램 + DB 기록
    try:
        from app.services.notification_service import NotificationService
        env_str = "testnet" if account.is_testnet else "mainnet"
        env_change = (
            f" + 환경 {('mainnet' if account.is_testnet else 'testnet')} → {env_str}"
            if will_change_env else ""
        )
        NotificationService(db).send_system_alert(
            title=f"🔑 [API 키 변경] account #{exchange_account_id}",
            body=(
                f"거래소: {account.exchange_name} · 환경: {env_str}{env_change}\n"
                "검증: get_account 성공 후 저장.\n"
                "이전 키 무효화됨 — 외부 시스템 (별도 봇 등) 에서 옛 키 사용 중이면 갱신 필요."
            ),
        )
    except Exception:
        pass  # audit 실패는 본 작업 성공 영향 X

    return ExchangeAccountResponse.model_validate(account)


@router.patch("/{exchange_account_id}/daily-loss-limit", response_model=ExchangeAccountResponse)
def update_daily_loss_limit(
    exchange_account_id: int,
    payload: ExchangeAccountDailyLimitUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> ExchangeAccountResponse:
    """계정 전용 일일 손실 한도 수정. NULL → global 폴백, 양수 → override, 0 → 비활성.

    daily_loss_aggregator 가 다음 사이클 (1분 내) 에 새 값으로 반영.
    """
    account = db.execute(
        select(ExchangeAccount)
        .where(ExchangeAccount.id == exchange_account_id)
        .where(ExchangeAccount.user_id == user_id)
    ).scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Exchange account not found")
    account.daily_loss_limit_usdt = payload.daily_loss_limit_usdt
    db.commit()
    db.refresh(account)
    return ExchangeAccountResponse.model_validate(account)


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
    # 사용 가능한 잔액 (Binance availableBalance — 현재 사용 마진만 차감)
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
    # 2026-06-01 사장님 요구 fix — 「전체 단계 예약」 모드:
    # 시스템 안전 운영의 핵심 사상. 사장님이 새 strategy 만들 때 진짜 가용 잔액
    # 확인 + 자동 4/5단계 진입 시 마진 부족(-2019) 절대 안 발생 보장.
    reserved_for_strategies: Decimal = Decimal("0")  # active strategy 의 total_capital 합 (5단계 풀 예약)
    our_available_balance: Decimal = Decimal("0")    # wallet - reserved (사장님 가용 잔액)
    active_strategy_count: int = 0                    # 활성 strategy 수 (예약에 포함된 것)


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

    # 2026-06-02 (#28 보강): Redis 캐시 15초 — frontend 5초 polling 부담 완화.
    # 캐시는 Binance accountInfo 응답만 (reserved 계산은 매번 — strategy 가 자주 바뀜).
    import json as _json
    from app.core.redis_client import get_redis_client
    _info_cache_key = f"binance:account_info:{exchange_account_id}"
    _redis = None
    info = None
    try:
        _redis = get_redis_client()
        cached = _redis.get(_info_cache_key)
        if cached:
            info = _json.loads(cached)
    except Exception:
        pass

    if info is None:
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
        # 캐시 저장 (Decimal → str)
        if _redis is not None:
            try:
                _redis.setex(_info_cache_key, 15, _json.dumps(info, default=str))
            except Exception:
                pass

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

    # 2026-06-01 사장님 요구 fix — 「전체 단계 예약」 모드 계산:
    # 활성 strategy 들의 total_capital 합 = 5단계 풀 자본 예약.
    # 사장님 가용 잔액 = wallet - 예약. 자동 stage 진입 시 마진 부족 절대 안 발생 보장.
    #
    # 2026-06-02 보강 (#31): 수동 증거금/포지션 추가 반영.
    # 문제: 사장님이 「💰 증거금 추가」 또는 「💉 포지션 추가」 클릭 후 실 사용 자본이
    #       template.total_capital 초과해도 reserved 가 안 늘어 → our_available 과대 표시.
    # 해결: 각 strategy 별 max(계획_total_capital, Binance_실_init_margin) 사용.
    #       Binance 측 실 사용 자본 > 계획 → 그 값 사용 (안전 측).
    #       Binance 측 실 사용 자본 ≤ 계획 → 계획값 유지 (5단계 풀 예약 보장).
    from app.models.strategy_instance import StrategyInstance
    from app.core.strategy_status import TERMINAL_STATUSES
    active_strategies = db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.exchange_account_id == exchange_account_id)
        .where(StrategyInstance.is_archived.is_(False))
        .where(StrategyInstance.status.notin_(TERMINAL_STATUSES))
    ).scalars().all()

    # Binance positions 중 active strategy 의 symbol 매칭 → 실 init_margin 추출.
    # ISOLATED: isolatedMargin (직접 마진 추가분 포함)
    # CROSS: positionInitialMargin (initial margin only)
    active_symbols_upper = {(s.symbol or "").upper() for s in active_strategies}
    binance_margin_by_symbol: dict[str, Decimal] = {}
    for p in positions:
        sym_upper = (p.get("symbol") or "").upper()
        if not sym_upper or sym_upper not in active_symbols_upper:
            continue
        iso = _d(p.get("isolatedMargin"))
        init = _d(p.get("positionInitialMargin"))
        # ISOLATED 면 iso, CROSS 면 init. 보수적으로 더 큰 값 (대개 같음).
        actual_margin = max(iso, init)
        # 한 symbol 에 multiple positions (예: LONG+SHORT hedge mode) 합산
        prev = binance_margin_by_symbol.get(sym_upper, Decimal("0"))
        binance_margin_by_symbol[sym_upper] = prev + actual_margin

    # 🚨 2026-06-08 사장님 critical 발견 silent bug fix (Pattern 4 — Asymmetric):
    # 사장님 BEATUSDT 4/6 진입 (= 5/6 단계 미진입, 자본 2,500 USDT 예약 필요)
    # 표시 = 「포지션 예약됨 0」 ← silent bug!
    #
    # 원인 (PR #84 자동 동기화 영향):
    # 1. 사장님 「💉 포지션 추가」 → isolated_margin > total_capital
    # 2. reconcile_worker (PR #84) = total_capital 자동 갱신 (= isolated_margin)
    # 3. = total_capital 이 "전체 단계 합" 의미 잃음 → "Binance 실 lock" 와 동일
    # 4. = max(planned, actual) = 동일 값 → 미진입 단계 예약 누락!
    #
    # Fix: template 의 stages_config.capitals 합 = "사장님 모든 단계 자본 합" 정확 사용
    # = PR #84 영향 없는 = 변하지 않는 사장님 의도 (= template 자체)
    # = 사장님 「↻ 설정만 수정」 으로만 변경 가능 (= 자동 동기화 영향 X)
    from app.models.strategy_template import StrategyTemplate
    template_ids = {s.strategy_template_id for s in active_strategies if s.strategy_template_id}
    templates_map = (
        {t.id: t for t in db.query(StrategyTemplate).filter(StrategyTemplate.id.in_(template_ids)).all()}
        if template_ids else {}
    )

    def _reserved_one(s) -> Decimal:
        actual = binance_margin_by_symbol.get((s.symbol or "").upper(), Decimal("0"))
        # 🌟 신: template stages_config.capitals 합 (= 모든 단계 자본 합)
        tpl = templates_map.get(s.strategy_template_id)
        stages_sum = Decimal("0")
        if tpl and tpl.stages_config:
            capitals = tpl.stages_config.get("capitals") or []
            for c in capitals:
                if c is None:
                    continue
                try:
                    stages_sum += Decimal(str(c))
                except Exception:
                    continue
        # max(모든 단계 자본 합, Binance 실 lock) — 사장님 자본 보호 사상
        if stages_sum > 0:
            return max(stages_sum, actual)
        # fallback (legacy: stages_config 없음 시)
        planned = s.total_capital or Decimal("0")
        return max(planned, actual)

    reserved_for_strategies = sum(
        (_reserved_one(s) for s in active_strategies), Decimal("0")
    )
    our_available_balance = total_wallet - reserved_for_strategies
    active_strategy_count = len(active_strategies)

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
        reserved_for_strategies=reserved_for_strategies,
        our_available_balance=our_available_balance,
        active_strategy_count=active_strategy_count,
    )


# 2026-06-01 (사장님 요구): 전략 인스턴스 행 아래 Binance 실데이터 인라인 표시용.
# Binance UI 의 「Positions」 탭 형식 그대로 → 우리 행과 시각적 비교 즉시 가능.
@router.get("/{account_id}/binance-positions")
def get_binance_positions(
    account_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict:
    """Binance 실 포지션 snapshot — UI 비교용 (30초 Redis 캐시).

    응답 형식 = Binance UI 「Positions」 탭 컬럼명 그대로:
      symbol / size / entry_price / break_even_price / mark_price
      / liquidation_price / margin / margin_mode / leverage
      / unrealized_pnl / roi_pct
    + fetched_at (확인 시각 — UI 에 표시)
    """
    import hashlib
    import hmac
    import json
    import time
    from datetime import datetime, timezone

    import requests

    from app.core.redis_client import get_redis_client

    account = db.execute(
        select(ExchangeAccount).where(
            ExchangeAccount.id == account_id,
            ExchangeAccount.user_id == user_id,
        )
    ).scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="계정 없음 또는 본인 소유 X")

    # 30초 캐시 — 「전략 인스턴스」 dashboard refresh 가 자주 호출되므로 부담 최소화
    cache_key = f"binance:positions:account:{account_id}"
    redis = None
    try:
        redis = get_redis_client()
        cached = redis.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    try:
        ak = decrypt_text(account.api_key_enc)
        sk = decrypt_text(account.api_secret_enc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"키 복호화 실패: {e}") from e

    base = "https://testnet.binancefuture.com" if account.is_testnet else "https://fapi.binance.com"
    ts = int(time.time() * 1000)
    qs = f"timestamp={ts}&recvWindow=5000"
    sig = hmac.new(sk.encode(), qs.encode(), hashlib.sha256).hexdigest()
    try:
        r = requests.get(
            f"{base}/fapi/v2/positionRisk?{qs}&signature={sig}",
            headers={"X-MBX-APIKEY": ak},
            timeout=10,
        )
        r.raise_for_status()
        raw = r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Binance positionRisk 호출 실패: {e}") from e

    positions: dict = {}
    for p in raw:
        try:
            amt = Decimal(str(p.get("positionAmt", "0")))
        except Exception:
            continue
        if amt == 0:
            continue
        entry = Decimal(str(p.get("entryPrice", "0") or "0"))
        mark = Decimal(str(p.get("markPrice", "0") or "0"))
        upnl = Decimal(str(p.get("unRealizedProfit", "0") or "0"))
        liq = Decimal(str(p.get("liquidationPrice", "0") or "0"))
        try:
            leverage = int(p.get("leverage", "1") or 1)
        except Exception:
            leverage = 1
        margin_mode = str(p.get("marginType", "isolated")).upper()
        try:
            iso_margin = Decimal(str(p.get("isolatedMargin", "0") or "0"))
        except Exception:
            iso_margin = Decimal("0")

        # ROI % — Binance UI 와 일치
        if margin_mode == "ISOLATED" and iso_margin > 0:
            roi = upnl / iso_margin * 100
            margin_display = iso_margin
        else:
            notional = abs(amt) * entry
            cross_margin = notional / leverage if leverage > 0 and notional > 0 else Decimal("0")
            roi = (upnl / cross_margin * 100) if cross_margin > 0 else Decimal("0")
            margin_display = cross_margin

        positions[p["symbol"]] = {
            "symbol": p["symbol"],
            "side": "LONG" if amt > 0 else "SHORT",
            "size": str(amt),
            "entry_price": str(entry),
            # Break Even Price 정확 값은 fapi/v2 응답에 없음 — Binance UI 는 commission 합산 표시.
            # 근사: entry_price (수수료 무시). 사장님이 commission 0.04% 가정하면 entry × 1.0008 보정 가능.
            "break_even_price": str(entry),
            "mark_price": str(mark),
            "liquidation_price": str(liq) if liq > 0 else None,
            "margin": str(margin_display.quantize(Decimal("0.01"))) if margin_display > 0 else None,
            "margin_mode": margin_mode,
            "leverage": leverage,
            "unrealized_pnl": str(upnl.quantize(Decimal("0.0001"))),
            "roi_pct": str(roi.quantize(Decimal("0.01"))),
        }

    response = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "account_id": account_id,
        "is_testnet": account.is_testnet,
        "positions": positions,
    }
    if redis:
        try:
            redis.setex(cache_key, 30, json.dumps(response))
        except Exception:
            pass
    return response
