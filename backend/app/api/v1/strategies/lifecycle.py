"""Strategies — lifecycle 액션 (margin/position 추가 + stop/force-stop/delete/restore).

전략 종료 / 보관 / 복원 + ad-hoc 마진/포지션 추가 endpoint 모음.
2026-05-14 Phase 4 split: 기존 strategies.py 에서 분리.
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from datetime import datetime, timezone

from app.api.deps import get_current_user_id, get_db
from app.core.crypto import decrypt_text
from app.core.strategy_status import MANUAL_CLEANUP_REQUIRED, TERMINAL_STATUSES
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from app.repositories.exchange_account_repository import ExchangeAccountRepository
from app.repositories.strategy_repository import StrategyRepository
from app.schemas.strategy import StrategyActionResponse, StrategyStopRequest
from app.services.execution_service import EmergencyCloseInProgress, ExecutionService, PreflightCheckFailed

router = APIRouter(prefix="/strategies", tags=["strategies"])


def _phase_c_wallet_capital_check(db: Session, account, addition_amount: Decimal, action: str) -> None:
    """Phase C (2026-06-01 사장님 핵심 사상 — 잔액 기반 운영):
    증거금 추가 / 포지션 추가 시 wallet 자본 검증.

    sum(active strategy total_capital) + addition > wallet → 400 차단.
    Phase A (전략 생성 시점) + Phase B (자동 stage 진입 시점) + Phase C (수동 추가 시점) = 다층 안전망.

    API 실패 시 skip (preflight 가 백업) — 안전.
    """
    from sqlalchemy import select
    from app.integrations.binance.client import BinanceClient

    try:
        client = BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=account.is_testnet,
        )
        acct = client.get_account()
    except Exception:
        return  # API 실패 — preflight 가 백업

    wallet = Decimal(str(acct.get("totalWalletBalance", "0")))
    if wallet <= 0:
        return  # wallet 0 이면 검증 skip (이상 상황, 다른 가드가 처리)

    active = db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.exchange_account_id == account.id)
        .where(StrategyInstance.is_archived.is_(False))
        .where(StrategyInstance.status.notin_(TERMINAL_STATUSES))
    ).scalars().all()
    total_reserved = sum(
        (Decimal(str(s.total_capital or 0)) for s in active), Decimal("0")
    )
    addition = Decimal(str(addition_amount or 0))
    projected = total_reserved + addition

    if projected > wallet:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"💰 {action} 차단 — 사장님 안전 사상 (잔액 기반 운영) 위반.\n\n"
                f"📌 계산 (자본 절대값 기준 — 화면 「예약」 카드와 동일):\n"
                f"  • 활성 strategy {len(active)}개 자본 합: {total_reserved:.2f} USDT\n"
                f"  • + 추가 ({action}): {addition:.2f} USDT\n"
                f"  • = 총 예약: {projected:.2f} USDT  >  Wallet: {wallet:.2f} USDT\n"
                f"  • 부족: {(projected - wallet):.2f} USDT\n\n"
                f"💡 조치 (택1):\n"
                f"  • USDT 입금 → wallet 회복\n"
                f"  • 다른 strategy 일부 청산 → 자본 예약 감소\n"
                f"  • 추가 금액 축소"
            ),
        )


class AddMarginRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, description="추가할 증거금 (USDT, 양수). 거래소 ISOLATED 모드 포지션에만 가능.")


@router.post("/{strategy_id}/add-margin", response_model=StrategyActionResponse)
def add_margin_to_strategy(
    strategy_id: int,
    payload: AddMarginRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyActionResponse:
    """ISOLATED 모드 포지션에 증거금 추가 — 청산가 완화.

    검증:
    - strategy 존재 + 본인 소유
    - 포지션 보유 (qty != 0)
    - amount > 0 (Pydantic 가드)
    - 거래소 마진 모드가 CROSS 면 -4046 거절 (친절 에러 메시지)
    """
    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.")
    account = ExchangeAccountRepository(db).get(strategy.exchange_account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="⚠️ 거래소 계정이 삭제됐거나 본인 소유가 아닙니다. 「💼 계정」 모달에서 확인하세요.")
    # Phase C (2026-06-01 사장님 사상): wallet 자본 검증 — 추가 후 sum > wallet 차단.
    _phase_c_wallet_capital_check(db, account, payload.amount, action="증거금 추가")
    try:
        execution_service = ExecutionService(
            db,
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=account.is_testnet,
        )
        execution_service.add_position_margin(strategy.id, amount=payload.amount)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    db.refresh(strategy)
    # 2026-05-06 (사용자 요청): 증거금 추가 시 텔레그램 알림 발송.
    try:
        from app.services.notification_service import NotificationService
        NotificationService(db).send_margin_added_alert(
            strategy_instance_id=strategy.id,
            symbol=strategy.symbol,
            side=strategy.side,
            amount=payload.amount,
        )
    except Exception:
        # 알림 실패는 본 작업 성공에 영향 X (silent fail, NotificationService 자체에서 SENT/FAILED 기록)
        pass
    return StrategyActionResponse(
        strategy_id=strategy.id,
        status=strategy.status,
        message=f"증거금 {payload.amount} USDT 추가 완료. 거래소에서 새 청산가 확인.",
    )


# 2026-05-04 (사용자 요청): 「💉 포지션 추가」 — 자유 금액 즉시 진입 (시장가 또는 지정가).
class AddPositionRequest(BaseModel):
    amount_usdt: Decimal = Field(..., gt=0, description="추가할 자본 (USDT, margin). qty = amount × leverage / price.")
    order_type: str = Field(..., description="MARKET 또는 LIMIT")
    limit_price: Decimal | None = Field(None, gt=0, description="LIMIT 주문일 때 지정가 (양수). MARKET 이면 무시.")


@router.post("/{strategy_id}/add-position", response_model=StrategyActionResponse)
def add_position_to_strategy(
    strategy_id: int,
    payload: AddPositionRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyActionResponse:
    """ad-hoc 포지션 추가 — 사용자가 입력한 USDT 금액을 시장가/지정가로 즉시 진입.

    증거금 추가 (마진만 늘림) 와 다름: qty 도 늘어남 + 평단 갱신 + invested_capital 증가.

    검증:
    - 본인 소유 strategy
    - kill-switch 미발동
    - amount_usdt > 0 (Pydantic 가드)
    - order_type ∈ {MARKET, LIMIT}
    - LIMIT 면 limit_price 필수
    """
    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.")
    account = ExchangeAccountRepository(db).get(strategy.exchange_account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="⚠️ 거래소 계정이 삭제됐거나 본인 소유가 아닙니다. 「💼 계정」 모달에서 확인하세요.")
    # Phase C (2026-06-01 사장님 사상): wallet 자본 검증 — 추가 후 sum > wallet 차단.
    _phase_c_wallet_capital_check(db, account, payload.amount_usdt, action="포지션 추가")
    try:
        execution_service = ExecutionService(
            db,
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=account.is_testnet,
        )
        order = execution_service.add_position_now(
            strategy.id,
            amount_usdt=payload.amount_usdt,
            order_type=payload.order_type,
            limit_price=payload.limit_price,
        )
    except PreflightCheckFailed as e:
        # Phase 3: 사전 마진 검증 실패 — 거래소 호출 0, 친절 400 에러.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Exchange error: {e}") from e
    db.refresh(strategy)
    order_type_label = payload.order_type.upper()
    # 2026-05-06 (사용자 요청): 포지션 추가 시 텔레그램 알림 발송.
    try:
        from app.services.notification_service import NotificationService
        NotificationService(db).send_position_added_alert(
            strategy_instance_id=strategy.id,
            symbol=strategy.symbol,
            side=strategy.side,
            amount_usdt=payload.amount_usdt,
            order_type=order_type_label,
            qty=order.orig_qty,
            limit_price=payload.limit_price,
        )
    except Exception:
        # 알림 실패는 본 작업 성공에 영향 X
        pass
    msg = (
        f"포지션 추가 — {order_type_label} 주문 발송됨 (amount={payload.amount_usdt} USDT, qty={order.orig_qty}). "
        f"체결되면 평단/qty 자동 갱신."
    )
    return StrategyActionResponse(
        strategy_id=strategy.id,
        status=strategy.status,
        message=msg,
    )


@router.post("/{strategy_id}/force-stop", response_model=StrategyActionResponse)
def force_stop_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyActionResponse:
    """거래소 호출 없이 DB 상에서만 전략을 STOPPED 로 마킹한다.

    사용 사례:
    - 거래소 API 키가 깨져서 일반 /stop 이 실패하는 고립 전략
    - 미체결 주문이 이미 거래소에서 사라진(만료/수동취소) 후 DB 만 남은 전략
    - 테스트/실험용 미사용 strategy 정리

    포지션이 거래소에 남아있을 수 있으니 운영자가 직접 확인 후 사용 권장.
    """
    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.")
    strategy.status = "STOPPED"
    strategy.reentry_ready = False
    # 좀비 방지 (2026-05-03): force-stop 시에도 qty=0 보장 — UI/통계 잔재 방지.
    # 실제 거래소 포지션은 운영자가 직접 정리해야 함 (force-stop 본 의도).
    from decimal import Decimal as _D
    strategy.current_position_qty = _D("0")
    if not strategy.stopped_at:
        from datetime import datetime as _dt, timezone as _tz
        strategy.stopped_at = _dt.now(_tz.utc)
    db.commit()
    db.refresh(strategy)
    return StrategyActionResponse(
        strategy_id=strategy.id,
        status=strategy.status,
        message="DB 상에서만 STOPPED + qty=0 마킹됨 (거래소 호출 없음 — 거래소 잔재는 운영자가 직접 확인)",
    )


@router.delete("/{strategy_id}", response_model=StrategyActionResponse)
def delete_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyActionResponse:
    """종료된 전략을 archive (soft delete) 한다 — DB row 보존.

    UX #17 (2026-04-29): 시작 실패한 전략 (-4164 등) 이 STOPPED 상태로
    "수동 종료" 표시되어 대시보드에 쌓이는 문제.

    2026-05-06 (사용자 #96 사례 — cascade hard delete 로 +867 USDT
    realized_pnl 누락 — soft delete 로 변경):
    - 한 번도 체결 안 한 전략 (current_stage=0): archive (UI 숨김 가능)
    - 1단계 이상 체결된 전략: archive (realized_pnl 통계 보존됨)
    - 어느 경우든 row + orders 보존 → realized_pnl 합계 정확성 유지

    안전장치:
    - 종료 상태가 아니면 거절 (활성 전략 archive 방지)
    - 이미 archived 면 noop (idempotent)
    """
    from datetime import datetime as _dt
    from datetime import timezone as _tz
    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.")

    # 2026-05-04: 공통 TERMINAL_STATUSES 사용 (이전엔 inline set 이라 다른 곳과 drift).
    if strategy.status not in TERMINAL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"활성 전략은 삭제 불가. 먼저 종료(/stop)하세요. 현재 status={strategy.status}",
        )

    # 이미 archived → idempotent
    if getattr(strategy, "is_archived", False):
        return StrategyActionResponse(
            strategy_id=strategy.id,
            status="ARCHIVED",
            message=f"전략 #{strategy.id} 는 이미 archive 상태입니다.",
        )

    # 2026-05-06 fix (#96 사례): hard delete → soft delete.
    # row + orders 보존 → /admin/stats 의 realized_pnl 합계가 거래소 history 일치.
    sid = strategy.id
    had_position = (strategy.current_stage or 0) > 0 or (
        strategy.avg_entry_price and Decimal(str(strategy.avg_entry_price)) > 0
    )
    realized = Decimal(str(strategy.realized_pnl or 0))

    # 2026-05-15 fix (사용자 #33 AVAAIUSDT + #41 ESPORTSUSDT 좀비 사례):
    # archive 시 latest position 의 qty 가 0 이 아니면 (force-stop 후 또는 외부 청산 누락)
    # 거래소에 잔량이 남아있을 가능성 높음 → CRITICAL RiskEvent + WARN 메시지.
    # archive 자체는 진행 (운영자 판단 존중) — 단 사후 알림 보장.
    from app.models.position import Position
    from app.models.risk_event import RiskEvent
    from sqlalchemy import select as sa_select
    latest_pos = db.execute(
        sa_select(Position)
        .where(Position.strategy_instance_id == strategy.id)
        .order_by(Position.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    suspected_orphan = False
    suspected_qty = None
    if latest_pos and latest_pos.position_amt is not None:
        try:
            suspected_qty = abs(Decimal(str(latest_pos.position_amt)))
            if suspected_qty > 0:
                suspected_orphan = True
        except Exception:
            pass

    strategy.is_archived = True
    strategy.archived_at = _dt.now(_tz.utc)

    if suspected_orphan:
        db.add(RiskEvent(
            strategy_instance_id=strategy.id,
            event_type="ARCHIVE_WITH_NONZERO_POSITION",
            severity="CRITICAL",
            title=f"🚨 전략 #{sid} archive 시 거래소 잔량 의심 ({suspected_qty})",
            message=(
                f"{strategy.symbol} {strategy.side} 전략 #{sid} archive 처리됐으나 "
                f"마지막 position snapshot 의 qty 가 {suspected_qty} (≠ 0). "
                f"거래소에 좀비 포지션 가능성 — 직접 확인/수동 청산 권장. "
                f"force-stop 후 archive 한 경우 자주 발생 (force-stop 은 DB qty=0 만 마킹)."
            ),
            event_payload={
                "strategy_id": sid,
                "symbol": strategy.symbol,
                "side": strategy.side,
                "last_known_position_amt": str(suspected_qty),
                "snapshot_id": latest_pos.id,
            },
        ))

    db.commit()

    if suspected_orphan:
        msg = (
            f"⚠️ 전략 #{sid} 보관 처리됨 (DB row + orders 보존). "
            f"마지막 snapshot qty={suspected_qty} → 거래소 잔량 가능성 높음. "
            f"CRITICAL 알림 발송됨 — 거래소에서 직접 청산 확인 필요."
        )
    elif had_position:
        msg = (
            f"전략 #{sid} 보관 처리됨 (DB row + orders 보존, UI 숨김). "
            f"realized_pnl {realized:+.4f} USDT 통계 합계에 유지됨."
        )
    else:
        msg = f"전략 #{sid} 보관 처리됨 (포지션 미진입, audit log 보존)."
    return StrategyActionResponse(
        strategy_id=sid,
        status="ARCHIVED",
        message=msg,
    )


@router.post("/{strategy_id}/restore", response_model=StrategyActionResponse)
def restore_strategy(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyActionResponse:
    """archived 된 strategy 를 복원 (is_archived → false). 2026-05-06 (C-full Step 2).

    DELETE 가 archive 로 변경됐으니 (PR #7), 실수로 archive 한 경우 되돌리기.
    archived 가 아닌 strategy 는 noop (idempotent). 복원 후 status 그대로 유지 —
    여전히 종료 상태 (STOPPED/COMPLETED/등). 사용자가 「🔄 다시 시작」 으로 새 progression
    시작 가능.
    """
    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.")

    if not getattr(strategy, "is_archived", False):
        return StrategyActionResponse(
            strategy_id=strategy.id,
            status=strategy.status,
            message=f"전략 #{strategy.id} 는 archive 상태가 아닙니다 (이미 활성/UI 표시 중).",
        )

    strategy.is_archived = False
    strategy.archived_at = None
    db.commit()
    return StrategyActionResponse(
        strategy_id=strategy.id,
        status=strategy.status,
        message=(
            f"전략 #{strategy.id} 복원 완료 — UI 목록에 다시 표시. status={strategy.status} "
            "그대로. 「🔄 다시 시작」 으로 새 progression 시작 가능."
        ),
    )


@router.post("/{strategy_id}/stop", response_model=StrategyActionResponse)
def stop_strategy(
    strategy_id: int,
    payload: StrategyStopRequest,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyActionResponse:
    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.")

    # Terminal status guard (2026-05-04 fix):
    # COMPLETED / STOPPED / REENTRY_READY 등 이미 종료된 strategy 에 stop 누르면
    # 무조건 STOPPING 으로 덮어쓰던 버그 → 좀비 발생 (#90 사례).
    # 종료 상태에서는 noop 으로 응답.
    if strategy.status in TERMINAL_STATUSES:
        return StrategyActionResponse(
            strategy_id=strategy.id,
            status=strategy.status,
            message=f"이미 종료된 전략 ({strategy.status}) 입니다. 추가 정지 불필요.",
        )

    account = ExchangeAccountRepository(db).get(strategy.exchange_account_id)
    if not account:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="⚠️ 거래소 계정이 삭제됐거나 본인 소유가 아닙니다. 「💼 계정」 모달에서 확인하세요.")

    execution_service = ExecutionService(
        db,
        api_key=decrypt_text(account.api_key_enc),
        api_secret=decrypt_text(account.api_secret_enc),
        is_testnet=account.is_testnet,
    )

    message = ""
    try:
        if payload.mode == "cancel_only":
            execution_service.client.cancel_all_orders(symbol=strategy.symbol)
            strategy.status = "STOPPING"
            db.commit()
            message = "All open orders cancelled"
        elif payload.mode in {"close_position_market", "emergency_stop"}:
            execution_service.client.cancel_all_orders(symbol=strategy.symbol)
            qty = Decimal(str(strategy.current_position_qty or 0)).copy_abs()
            if qty > 0:
                try:
                    execution_service.emergency_close_position(strategy.id, quantity=qty)
                except ValueError as ve:
                    # UX (2026-04-29): Bug #8 fix 가 거래소 포지션 0 일 때 ValueError 를
                    # 던짐 (cleanup 은 이미 완료). 이 경우 502 가 아닌 정상 응답으로 처리.
                    if "no" in str(ve).lower() and "position" in str(ve).lower():
                        db.refresh(strategy)
                        return StrategyActionResponse(
                            strategy_id=strategy.id,
                            status=strategy.status,
                            message=f"이미 청산된 상태였습니다. 미체결 주문 취소 + STOPPED 마킹 완료. ({ve})",
                        )
                    raise
                except EmergencyCloseInProgress:
                    # 2026-05-08 (#120 사례): 같은 전략에 대해 다른 caller (자동 TP/SL,
                    # admin cleanup) 가 이미 청산 중. 중복 발사 방지 — 정상 응답으로 처리.
                    db.refresh(strategy)
                    return StrategyActionResponse(
                        strategy_id=strategy.id,
                        status=strategy.status,
                        message="이미 다른 청산 요청이 처리 중입니다. 5초 후 상태를 다시 확인하세요.",
                    )
            strategy.status = "STOPPING"
            db.commit()
            message = "Position closed at market"
    except HTTPException:
        raise
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Exchange error: {e}") from e

    db.refresh(strategy)
    return StrategyActionResponse(strategy_id=strategy.id, status=strategy.status, message=message)


# ============================================================================
# 2026-05-21 Phase 2 — 수동 청산 처리 완료 ack (사장님 요구)
# ============================================================================
@router.post("/{strategy_id}/acknowledge-manual-cleanup", response_model=StrategyActionResponse)
def acknowledge_manual_cleanup(
    strategy_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StrategyActionResponse:
    """수동 청산 요청 (MANUAL_CLEANUP_REQUIRED) → 사장님 명시적 STOPPED 전환.

    사용 시나리오:
      1. emergency_close 가 거래소에서 거절돼 strategy 가 MANUAL_CLEANUP_REQUIRED 로 전환됨
      2. 사장님이 거래소 UI 에서 직접 포지션 청산 (또는 대시보드 「긴급 종료」 재시도 성공)
      3. 대시보드에서 「✅ 수동 청산 처리 완료」 버튼 클릭 → 본 endpoint 호출
      4. status MANUAL_CLEANUP_REQUIRED → STOPPED 전환 + RiskEvent (감사 추적)

    이전엔 reconcile 이 거래소 포지션 0 보면 자동 STOPPED 처리했지만, 「사장님이 직접
    처리한 건」 vs 「자동 정리된 건」 구분 불가 → 책임 추적 어려움. 본 endpoint 는
    사장님의 명시적 ack 만 STOPPED 전환을 허용함.

    가드:
      - 본인 소유 strategy 만 (user_id 일치)
      - status 가 MANUAL_CLEANUP_REQUIRED 인 경우에만 (다른 status 면 400)
    """
    strategy = StrategyRepository(db).get_strategy(strategy_id)
    if not strategy or strategy.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="⚠️ 전략을 찾을 수 없거나 본인 소유가 아닙니다.",
        )
    if strategy.status != MANUAL_CLEANUP_REQUIRED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"⚠️ 수동 청산 처리 가능한 상태가 아닙니다 (현재 status: {strategy.status}). "
                f"MANUAL_CLEANUP_REQUIRED 상태에서만 사용하세요."
            ),
        )

    previous_status = strategy.status
    strategy.status = "STOPPED"
    strategy.current_position_qty = Decimal("0")  # 사장님이 거래소에서 청산 완료한 상태
    strategy.stopped_at = datetime.now(timezone.utc)

    # 감사 추적 — 「사장님이 직접 처리 완료 확인」 trail 로그
    db.add(RiskEvent(
        strategy_instance_id=strategy.id,
        event_type="MANUAL_CLEANUP_ACKNOWLEDGED",
        severity="INFO",
        title="✅ 수동 청산 처리 완료 확인 (사장님 ack)",
        message=(
            f"{strategy.symbol} {strategy.side} — 사장님이 거래소에서 직접 청산 후 "
            f"대시보드에서 처리 완료 확인. {previous_status} → STOPPED 전환."
        ),
        event_payload={
            "strategy_id": strategy.id,
            "previous_status": previous_status,
            "acknowledged_by_user_id": user_id,
        },
    ))
    db.commit()
    db.refresh(strategy)
    return StrategyActionResponse(
        strategy_id=strategy.id,
        status=strategy.status,
        message=(
            "수동 청산 처리 완료 확인됨. STOPPED 전환 + 감사 로그 기록. "
            "(reconcile 다음 사이클이 거래소 잔재 포지션 0 을 재확인합니다)"
        ),
    )
