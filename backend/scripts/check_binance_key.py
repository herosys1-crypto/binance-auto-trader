"""DB 에 저장된 Binance API 키가 유효한지 확인하는 진단 스크립트.

실행:
    docker compose run --rm api python scripts/check_binance_key.py

exchange_account id=1 의 키를 복호화 → 공개 ping → private balance 호출까지 시도.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app.core.crypto import decrypt_text  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.integrations.binance.client import BinanceAPIError, BinanceClient  # noqa: E402
from app.repositories.exchange_account_repository import ExchangeAccountRepository  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        acc = ExchangeAccountRepository(db).get(1)
        if not acc:
            print("[error] exchange_account id=1 not found")
            return 1

        print(f"[meta] is_testnet = {acc.is_testnet}")
        print(f"[meta] hedge_mode = {acc.hedge_mode_enabled}")
        print(f"[meta] is_active  = {acc.is_active}")

        api_key = decrypt_text(acc.api_key_enc)
        api_secret = decrypt_text(acc.api_secret_enc)
        print(f"[key]  head={api_key[:10]}... len={len(api_key)}")
        print(f"[sec]  head={api_secret[:10]}... len={len(api_secret)}")

        client = BinanceClient(
            api_key=api_key,
            api_secret=api_secret,
            is_testnet=acc.is_testnet,
        )
        print(f"[url]  base={client.base_url}")

        print("")
        print("[step] public ping ...")
        try:
            client.ping()
            print("[ok]   public endpoint reachable")
        except BinanceAPIError as e:
            print(f"[fail] public ping: {e}")
            return 2

        print("")
        print("[step] signed get_balance ...")
        try:
            bal = client.get_balance()
            print(f"[ok]   {len(bal)} balance entries")
            for item in bal[:5]:
                asset = item.get("asset")
                balance = item.get("balance")
                print(f"       - {asset}: {balance}")
        except BinanceAPIError as e:
            print(f"[fail] get_balance: {e}")
            return 3

        print("")
        print("[step] signed get_account ...")
        try:
            acct = client.get_account()
            print(f"[ok]   canTrade={acct.get('canTrade')}, canDeposit={acct.get('canDeposit')}")
            print(f"       totalWalletBalance={acct.get('totalWalletBalance')}")
        except BinanceAPIError as e:
            print(f"[fail] get_account: {e}")
            return 4

        print("")
        print("[done] all checks passed — key is valid and has futures permissions")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
