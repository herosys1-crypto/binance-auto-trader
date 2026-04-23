import argparse
from sqlalchemy import select
from app.core.crypto import decrypt_text
from app.core.database import SessionLocal
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
    db = SessionLocal()
    try:
        rows = db.execute(
            select(StrategyInstance, ExchangeAccount)
            .join(ExchangeAccount, StrategyInstance.exchange_account_id == ExchangeAccount.id)
            .where(StrategyInstance.status.in_(["STAGE1_OPEN","STAGE2_OPEN","STAGE3_OPEN","STAGE4_OPEN","TP1_DONE_PARTIAL","TP2_DONE_PARTIAL"]))
            .where(ExchangeAccount.is_active.is_(True))
        ).all()
        for strategy, account in rows:
            try:
                TPSLOrchestratorService(db, api_key=decrypt_text(account.api_key_enc), api_secret=decrypt_text(account.api_secret_enc), is_testnet=account.is_testnet).run_for_strategy(strategy.id)
            except Exception as e:
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
