"""우리 시스템 (DB) vs Binance 실 데이터 동기화 검증 worker.

배경 (2026-06-01 사장님 요구):
"우리 시스템과 Binance Sub-Account 가 잘 맞으면 지금처럼 계속 해도 됩니다.
수시로 비교분석해서 간략한 보고서로 최근동향에 알려줘요"

동작:
- 매 5분 주기로 모든 active strategy 의 DB ↔ Binance 비교:
  - 포지션 수량 (DB.current_position_qty vs Binance positionAmt)
  - 평균 진입가 (DB.avg_entry_price vs Binance entryPrice)
  - 미실현 손익 (DB.unrealized_pnl vs Binance unRealizedProfit)
- 임계 초과 차이 발견 → 「최근 활동」 알림 (WARN, 30분 dedup)
- 정상 → 매 6시간 1회 summary 알림 ("동기화 정상")
"""
from __future__ import annotations
import hashlib
import hmac
import logging
import time
from decimal import Decimal

import requests
from sqlalchemy import select

from app.core.api_backoff import is_account_banned
from app.core.crypto import decrypt_text
from app.core.database import SessionLocal
from app.core.redis_client import get_redis_client
from app.core.strategy_status import ACTIVE_WITH_POSITION
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance

logger = logging.getLogger(__name__)

# 차이 감지 임계 — 이 % / 금액 초과 시만 WARN (작은 변동은 무시)
_QTY_THRESHOLD_PCT = Decimal("1.0")          # 수량 1% 이상 차이
_ENTRY_PRICE_THRESHOLD_PCT = Decimal("0.1")  # 진입가 0.1% 이상 차이
_UPNL_THRESHOLD_USDT = Decimal("1.0")        # 미실현 1 USDT 이상 차이

# 알림 dedup TTL
_MISMATCH_DEDUP_TTL_SEC = 30 * 60   # 차이 알림 — 30분 1회 (spam 방지)
_HEALTHY_DEDUP_TTL_SEC = 6 * 3600   # 정상 summary — 6시간 1회

BASE_MAINNET = "https://fapi.binance.com"
BASE_TESTNET = "https://testnet.binancefuture.com"


def _binance_positions(ak: str, sk: str, base_url: str) -> dict:
    ts = int(time.time() * 1000)
    qs = f"timestamp={ts}&recvWindow=5000"
    sig = hmac.new(sk.encode(), qs.encode(), hashlib.sha256).hexdigest()
    r = requests.get(
        f"{base_url}/fapi/v2/positionRisk?{qs}&signature={sig}",
        headers={"X-MBX-APIKEY": ak},
        timeout=10,
    )
    r.raise_for_status()
    return {p["symbol"]: p for p in r.json() if float(p.get("positionAmt", 0)) != 0}


def _compare_strategy(s: StrategyInstance, bp: dict | None) -> list[str]:
    """단일 strategy 비교 — 차이 목록 반환 (빈 list = 일치)."""
    diffs = []

    if bp is None:
        # Binance 측 포지션 없음 (DB 만 있음)
        db_qty = s.current_position_qty
        if db_qty is not None and abs(float(db_qty)) > 1e-12:
            diffs.append(f"#{s.id} {s.symbol}: DB qty={db_qty} but Binance 포지션 없음")
        return diffs

    # 수량 비교
    db_qty = Decimal(str(s.current_position_qty or 0))
    bn_qty = Decimal(str(bp.get("positionAmt", 0)))
    if db_qty != 0 and abs((db_qty - bn_qty) / db_qty * 100) > _QTY_THRESHOLD_PCT:
        diffs.append(
            f"#{s.id} {s.symbol}: 수량 DB={db_qty} vs Binance={bn_qty}"
        )

    # 평균 진입가 비교
    db_entry = Decimal(str(s.avg_entry_price or 0))
    bn_entry = Decimal(str(bp.get("entryPrice", 0)))
    if db_entry > 0 and bn_entry > 0:
        diff_pct = abs((db_entry - bn_entry) / db_entry * 100)
        if diff_pct > _ENTRY_PRICE_THRESHOLD_PCT:
            diffs.append(
                f"#{s.id} {s.symbol}: 진입가 DB={db_entry} vs Binance={bn_entry} ({diff_pct:.3f}%)"
            )

    # 미실현 손익 비교
    db_upnl = Decimal(str(s.unrealized_pnl or 0))
    bn_upnl = Decimal(str(bp.get("unRealizedProfit", 0)))
    if abs(db_upnl - bn_upnl) > _UPNL_THRESHOLD_USDT:
        diffs.append(
            f"#{s.id} {s.symbol}: uPnL DB={db_upnl:.2f} vs Binance={bn_upnl:.2f} (차이 {(db_upnl - bn_upnl):.2f} USDT)"
        )

    return diffs


def _send_alert(account_id: int, kind: str, payload) -> None:
    """알림 발송 + dedup (Redis TTL)."""
    try:
        redis = get_redis_client()
    except Exception:
        redis = None

    ttl = _HEALTHY_DEDUP_TTL_SEC if kind == "healthy" else _MISMATCH_DEDUP_TTL_SEC
    dedup_key = f"sync_health:dedup:account:{account_id}:{kind}"

    if redis:
        try:
            if redis.get(dedup_key):
                return  # dedup 내 — skip
            redis.setex(dedup_key, ttl, "1")
        except Exception:
            pass

    try:
        from app.services.notification_service import NotificationService
        db = SessionLocal()
        try:
            ns = NotificationService(db)
            if kind == "healthy":
                count = int(payload)
                ns.send_system_alert(
                    title="✓ 동기화 정상 — Binance ↔ DB",
                    body=(
                        f"활성 strategy {count}개 비교 완료.\n"
                        f"수량 / 평단가 / 미실현 손익 모두 일치.\n\n"
                        f"(다음 정상 보고: 6시간 후. 차이 발견 시 즉시 알림)"
                    ),
                )
            else:  # mismatch
                diffs = list(payload)
                body_lines = [
                    "🔍 우리 시스템 (DB) vs Binance 실 데이터 차이 발견:",
                    "",
                ]
                for d in diffs:
                    body_lines.append(f"  • {d}")
                body_lines.extend([
                    "",
                    "🔧 자동 reconcile (매 2분) 이 차이 보정 시도 중.",
                    "30분 안 안 풀리면 수동 확인 권장.",
                ])
                ns.send_system_alert(
                    title=f"⚠ 동기화 차이 발견 — {len(diffs)}건",
                    body="\n".join(body_lines),
                )
            logger.info("[sync-health] alert sent kind=%s account=%s", kind, account_id)
        finally:
            db.close()
    except Exception as e:
        logger.warning("[sync-health] alert send failed: %s", e)


def run_sync_health_monitor_once() -> None:
    """매 5분 호출 — 모든 active strategy 의 DB ↔ Binance 비교."""
    db = SessionLocal()
    try:
        accounts = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_active.is_(True))
        ).scalars().all()

        for account in accounts:
            if is_account_banned(account.id):
                continue

            try:
                ak = decrypt_text(account.api_key_enc)
                sk = decrypt_text(account.api_secret_enc)
            except Exception as e:
                logger.warning("[sync-health] decrypt fail acc=%s: %s", account.id, e)
                continue

            base = BASE_TESTNET if account.is_testnet else BASE_MAINNET
            try:
                binance_pos = _binance_positions(ak, sk, base)
            except Exception as e:
                logger.warning("[sync-health] Binance positionRisk fail acc=%s: %s", account.id, e)
                continue

            strategies = db.execute(
                select(StrategyInstance)
                .where(StrategyInstance.exchange_account_id == account.id)
                .where(StrategyInstance.is_archived.is_(False))
                .where(StrategyInstance.status.in_(ACTIVE_WITH_POSITION))
            ).scalars().all()

            all_diffs = []
            for s in strategies:
                bp = binance_pos.get(s.symbol)
                all_diffs.extend(_compare_strategy(s, bp))

            if all_diffs:
                _send_alert(account.id, kind="mismatch", payload=all_diffs)
            elif strategies:
                _send_alert(account.id, kind="healthy", payload=len(strategies))
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    run_sync_health_monitor_once()
    sys.exit(0)
