import argparse
import logging
from sqlalchemy import select
from app.core.api_backoff import is_account_banned, maybe_record_ban_from_exc
from app.core.crypto import decrypt_text
from app.core.database import SessionLocal
from app.core.strategy_status import TERMINAL_STATUSES

logger = logging.getLogger(__name__)
from app.integrations.binance.client import BinanceClient
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.services.notification_service import NotificationService
from app.services.symbol_sync_service import SymbolSyncService
from app.services.tp_sl_orchestrator import TPSLOrchestratorService
from app.workers.keepalive_worker import run_keepalive_once
from app.workers.reconcile_worker import run_position_reconcile_once

def run_symbol_sync_once() -> None:
    db = SessionLocal()
    try:
        account = db.execute(select(ExchangeAccount).where(ExchangeAccount.exchange_name == "binance", ExchangeAccount.is_active.is_(True))).scalar_one_or_none()
        if not account:
            print("[symbol_sync] no active exchange account found")
            return
        client = BinanceClient(api_key=decrypt_text(account.api_key_enc), api_secret=decrypt_text(account.api_secret_enc), is_testnet=account.is_testnet)
        count = SymbolSyncService(db, client).sync()
        print(f"[symbol_sync] synced symbols={count}")
    finally:
        db.close()

def run_tp_sl_once() -> None:
    """모든 활성 strategy 의 TP/SL 평가를 한 사이클 실행.

    2026-05-05 critical fix (사용자 #96 TSTUSDT 좀비 사례):
      이전 status hardcoded 화이트리스트 (`STAGE1~4_OPEN, TP1/2_DONE_PARTIAL`) 가
      옵션 C 5+단계 strategy 와 TP3/4/5_DONE_PARTIAL / TP2_DONE / TRAILING_ARMED 를
      누락 → STAGE6_OPEN 인 #96 가 평가 0회 → max_profit_pct 갱신 X → TP 발동 X.
      종료 status 만 제외하는 패턴으로 변경 — 새 status 추가 시 자동 포함.
    """
    db = SessionLocal()
    try:
        # STOPPING 은 emergency_close 진행 중 — TP/SL 평가 의미 없음 (곧 qty=0).
        # WAITING 은 진입 전 — orchestrator 의 early return 으로 처리되지만 SQL 단계에서 거름.
        _NOT_FOR_TP_SL = frozenset(TERMINAL_STATUSES) | {"STOPPING", "WAITING"}
        rows = db.execute(
            select(StrategyInstance, ExchangeAccount)
            .join(ExchangeAccount, StrategyInstance.exchange_account_id == ExchangeAccount.id)
            .where(~StrategyInstance.status.in_(_NOT_FOR_TP_SL))
            .where(StrategyInstance.is_archived.is_(False))  # 2026-05-06 C-full: archived 제외
            .where(ExchangeAccount.is_active.is_(True))
        ).all()
        # 2026-05-17 rate limit ban 스파이럴 사후: account 별 ban 1회 체크 캐시.
        # ban 중이면 그 account 의 모든 strategy skip → ban 윈도우 중 호출 폭주 차단.
        _banned_accounts: set[int] = set()
        for strategy, account in rows:
            if account.id in _banned_accounts:
                continue
            if is_account_banned(account.id):
                _banned_accounts.add(account.id)
                logger.info("[tp_sl] API ban active account=%s — skip cycle", account.id)
                continue
            try:
                TPSLOrchestratorService(db, api_key=decrypt_text(account.api_key_enc), api_secret=decrypt_text(account.api_secret_enc), is_testnet=account.is_testnet).run_for_strategy(strategy.id)
            except Exception as e:
                # rate limit/ban 이면 기록 + 이 account 나머지 strategy skip (스파이럴 차단)
                if maybe_record_ban_from_exc(e, account.id, notification_service=NotificationService(db)):
                    _banned_accounts.add(account.id)
                    logger.warning("[tp_sl] rate limit detected account=%s — skip rest of cycle", account.id)
                    continue
                NotificationService(db).send_system_alert(title="[시스템 오류] TP/SL orchestration 실패", body=f"strategy_id={strategy.id}, error={e}")
    finally:
        db.close()

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", required=True, choices=["keepalive", "reconcile", "symbol-sync", "tp-sl"])
    args = parser.parse_args()
    if args.worker == "keepalive":
        run_keepalive_once(decrypt_text)
    elif args.worker == "reconcile":
        run_position_reconcile_once(decrypt_text)
    elif args.worker == "symbol-sync":
        run_symbol_sync_once()
    elif args.worker == "tp-sl":
        run_tp_sl_once()

if __name__ == "__main__":
    main()
