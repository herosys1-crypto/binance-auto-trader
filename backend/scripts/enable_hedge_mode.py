"""DB 에 저장된 Binance 계정에 Hedge Mode (dualSidePosition=true) 활성화.

한 번만 실행하면 되며, Binance 계정 설정에 영구 저장됨.
열린 포지션이 있으면 변경 불가.
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

        client = BinanceClient(
            api_key=decrypt_text(acc.api_key_enc),
            api_secret=decrypt_text(acc.api_secret_enc),
            is_testnet=acc.is_testnet,
        )
        print(f"[info] target: {client.base_url}, testnet={acc.is_testnet}")

        try:
            response = client.change_position_mode(dual_side_position=True)
            print(f"[ok] hedge mode enabled. response: {response}")
        except BinanceAPIError as e:
            # code -4059 = "No need to change position side"
            if getattr(e, "code", None) == -4059:
                print("[ok] hedge mode was already enabled — nothing to change")
            else:
                print(f"[fail] {e}")
                return 2

        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
