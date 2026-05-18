"""자동 재진입 워커.

scheduler 에서 주기적으로 호출 → reentry_policy='auto' 이고 status=REENTRY_READY 이며
stopped_at + reentry_delay_seconds 가 지난 strategy 를 자동으로 재시작.

동작:
1. 후보 전략 검색
2. 각 후보:
   - 거래소 현재가 조회 (Binance public API)
   - 새 start_price = 현재가 × (1 ± offset_pct/100)
   - 새 strategy_instance + stage_plans 생성 (StrategyService.create_strategy_instance)
   - 1단계 LIMIT 주문 발송 (ExecutionService.start_stage1)
   - 원본 strategy 의 status = REENTRY_DONE 으로 변경
   - Telegram 알림
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable

import requests
from sqlalchemy import select

from app.core.api_backoff import is_account_banned, maybe_record_ban_from_exc
from app.core.database import SessionLocal
from app.core.sentry import capture_strategy_event
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_template import StrategyTemplate
from app.services.execution_service import ExecutionService
from app.services.notification_service import NotificationService
from app.services.strategy_service import StrategyService

logger = logging.getLogger(__name__)


# 명시 export — 테스트 헬퍼가 patch 할 때 좀 더 안정적인 lookup 보장.
__all__ = ["run_auto_reentry_once"]


def _fetch_current_price(symbol: str, is_testnet: bool) -> Decimal | None:
    base = "https://testnet.binancefuture.com" if is_testnet else "https://fapi.binance.com"
    try:
        r = requests.get(
            f"{base}/fapi/v1/ticker/price",
            params={"symbol": symbol},
            timeout=5,
        )
        r.raise_for_status()
        return Decimal(str(r.json()["price"]))
    except Exception as e:  # pragma: no cover
        logger.warning("auto_reentry: failed to fetch %s price: %s", symbol, e)
        return None


def run_auto_reentry_once(decrypt_text: Callable[[str], str]) -> None:
    """1회 자동 재진입 검사 + 실행."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        # 후보: REENTRY_READY 상태 + 템플릿이 auto + delay 경과
        rows = db.execute(
            select(StrategyInstance, StrategyTemplate)
            .join(StrategyTemplate, StrategyInstance.strategy_template_id == StrategyTemplate.id)
            .where(
                StrategyInstance.status == "REENTRY_READY",
                StrategyInstance.reentry_ready.is_(True),
                StrategyInstance.is_archived.is_(False),  # 2026-05-06 C-full
                StrategyTemplate.reentry_policy == "auto",
            )
        ).all()

        for strategy, tpl in rows:
            stopped = strategy.stopped_at or strategy.updated_at
            if stopped is None:
                continue
            # postgres 는 DateTime(timezone=True) 로 tz-aware 반환, sqlite 는 naive 반환.
            # `now` 가 tz-aware 이라 비교 시 type mismatch 가능 — 방어적으로 normalize.
            if stopped.tzinfo is None:
                stopped = stopped.replace(tzinfo=timezone.utc)
            delay = timedelta(seconds=int(tpl.reentry_delay_seconds or 600))
            if now < stopped + delay:
                # 아직 대기 시간 미경과
                continue

            # 거래소 계정 가져오기
            account = db.get(ExchangeAccount, strategy.exchange_account_id)
            if not account or not account.is_active:
                logger.warning("auto_reentry: skip strategy %s — exchange account inactive", strategy.id)
                strategy.status = "REENTRY_FAILED"
                strategy.last_error_message = "Exchange account inactive"
                # 2026-05-04 fix: status 변경을 즉시 commit — 다음 strategy 처리 중 rollback
                # 발생 시 같이 lost 되지 않도록.
                db.commit()
                continue

            # 2026-05-17 rate limit ban 스파이럴 사후: ban 중이면 skip.
            # ★ REENTRY_FAILED 로 마킹하지 않음 — status 그대로 REENTRY_READY 유지 →
            #   ban 만료 후 다음 cycle 에서 정상 재진입 (일시적 ban 으로 재진입 영구 상실 방지).
            if is_account_banned(account.id):
                logger.info("auto_reentry: skip strategy %s — API ban active account=%s", strategy.id, account.id)
                continue

            # 현재가 → 새 start_price
            current_price = _fetch_current_price(strategy.symbol, account.is_testnet)
            if current_price is None:
                logger.warning("auto_reentry: skip strategy %s — price fetch failed", strategy.id)
                continue

            offset = Decimal(str(tpl.reentry_offset_pct or "1.0"))
            multiplier = (Decimal("1") + offset / Decimal("100")) if strategy.side == "SHORT" else (Decimal("1") - offset / Decimal("100"))
            new_start_price = (current_price * multiplier).quantize(Decimal("0.00000001"))

            try:
                # 새 strategy 생성
                new_strategy = StrategyService(db).create_strategy_instance(
                    user_id=strategy.user_id,
                    exchange_account_id=strategy.exchange_account_id,
                    strategy_template_id=strategy.strategy_template_id,
                    symbol=strategy.symbol,
                    side=strategy.side,
                    start_price=new_start_price,
                )
                # 1단계 주문 발송
                exec_svc = ExecutionService(
                    db,
                    api_key=decrypt_text(account.api_key_enc),
                    api_secret=decrypt_text(account.api_secret_enc),
                    is_testnet=account.is_testnet,
                )
                exec_svc.start_stage1(new_strategy.id)

                # 원본 strategy 마킹
                strategy.status = "REENTRY_DONE"
                strategy.reentry_ready = False
                db.commit()

                # 알림
                try:
                    NotificationService(db).send_system_alert(
                        title=f"🔁 [자동 재진입] {strategy.symbol} {strategy.side}",
                        body=(
                            f"이전 전략 #{strategy.id} 손절 후 {int(tpl.reentry_delay_seconds)}초 경과.\n"
                            f"새 전략 #{new_strategy.id} 자동 시작.\n"
                            f"현재가: {current_price} → 새 시작가: {new_start_price} (오프셋 {offset}%)"
                        ),
                    )
                except Exception:  # pragma: no cover
                    pass

                logger.info("auto_reentry: strategy #%s → new #%s (start_price=%s)",
                           strategy.id, new_strategy.id, new_start_price)
            except Exception as e:
                # 2026-05-17: rate limit/ban 이면 REENTRY_FAILED 마킹 금지 — rollback 후
                # status 그대로 두어 ban 만료 후 다음 cycle 에서 재시도 (일시적 ban 으로
                # 재진입 영구 상실 방지). ban 기록만 하고 다음 strategy 로.
                if maybe_record_ban_from_exc(e, account.id, notification_service=NotificationService(db)):
                    db.rollback()
                    logger.warning("auto_reentry: rate limit detected account=%s — skip (status 유지, 다음 cycle 재시도)", account.id)
                    continue
                logger.exception("auto_reentry: failed for strategy #%s: %s", strategy.id, e)
                # 2026-05-04 fix: 이전 코드 버그 — last_error_message 설정 후 rollback 하면
                # 그 변경도 같이 rollback 되어 영구히 lost. 또 status 가 REENTRY_READY 그대로
                # 남아 다음 사이클에 무한 retry 됨 (영구 실패 케이스).
                # 이제: rollback 으로 진행 중 변경 (StrategyService.create_strategy_instance 의
                # 부분 commit 등) 정리 후, 명시적으로 REENTRY_FAILED + last_error_message 를
                # 새로 set + commit.
                db.rollback()
                # rollback 후 strategy 객체가 detached 일 수 있어 새로 fetch.
                _refetched = db.get(StrategyInstance, strategy.id)
                if _refetched is not None:
                    _refetched.status = "REENTRY_FAILED"
                    _refetched.last_error_message = f"auto_reentry failed: {e}"[:500]
                    db.commit()
                # Sentry 캡처 — 운영 가시성 (DSN 미설정 시 no-op).
                capture_strategy_event(
                    "auto_reentry failed for strategy",
                    level="error", error=e,
                    strategy_id=strategy.id, symbol=strategy.symbol, side=strategy.side,
                    account_id=strategy.exchange_account_id,
                    tags={"event_type": "AUTO_REENTRY_FAILED"},
                )
        # 2026-05-04 fix: 루프 끝에서 명시적 commit (방어적). 만약 위 분기에서 누락된
        # 변경이 있어도 함수 종료 시 persist 보장.
        try:
            db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()
