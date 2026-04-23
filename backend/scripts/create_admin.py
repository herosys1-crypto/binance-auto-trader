"""관리자 계정 및 Binance API 키 최초 등록 CLI.

사용법:
    python scripts/create_admin.py --email admin@example.com --password 'ChangeMe!123'

추가 옵션:
    --binance-api-key XXX        Binance testnet API key (암호화되어 저장)
    --binance-api-secret YYY     Binance testnet API secret
    --testnet                    testnet 계정으로 등록 (기본 False = mainnet)

이미 해당 이메일이 존재하면 비밀번호만 갱신합니다.
"""
from __future__ import annotations

import argparse
import os
import sys
from getpass import getpass

# 프로젝트 루트(backend/)가 sys.path 에 있어야 `app.*` import 가 됨.
# `python scripts/create_admin.py ...` 처럼 스크립트를 직접 실행할 경우 Python 은
# scripts/ 디렉터리만 sys.path 에 올리므로 수동 보정이 필요하다.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from sqlalchemy import select  # noqa: E402

from app.core.crypto import encrypt_text  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.exchange_account import ExchangeAccount  # noqa: E402
from app.models.user import User  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Create/update admin user & Binance account.")
    parser.add_argument("--email", required=True, help="Admin email (login id)")
    parser.add_argument("--password", help="Admin password (omit to be prompted)")
    parser.add_argument("--full-name", default="Admin", help="Admin display name")
    parser.add_argument("--binance-api-key", help="Binance API key to register")
    parser.add_argument("--binance-api-secret", help="Binance API secret to register")
    parser.add_argument("--testnet", action="store_true", help="Mark the exchange account as testnet")
    parser.add_argument("--no-hedge-mode", action="store_true", help="Disable hedge mode flag")
    args = parser.parse_args()

    password = args.password or getpass("Admin password: ")
    if not password:
        print("password is empty", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.email == args.email)).scalar_one_or_none()
        if user is None:
            user = User(
                email=args.email,
                password_hash=hash_password(password),
                full_name=args.full_name,
                role="admin",
                is_active=True,
                timezone="Asia/Seoul",
            )
            db.add(user)
            db.flush()
            print(f"[created] user id={user.id} email={user.email}")
        else:
            user.password_hash = hash_password(password)
            user.is_active = True
            if args.full_name:
                user.full_name = args.full_name
            print(f"[updated] user id={user.id} email={user.email}")

        if args.binance_api_key and args.binance_api_secret:
            existing = db.execute(
                select(ExchangeAccount).where(ExchangeAccount.user_id == user.id)
            ).scalar_one_or_none()
            enc_key = encrypt_text(args.binance_api_key)
            enc_sec = encrypt_text(args.binance_api_secret)
            hedge = not args.no_hedge_mode
            if existing is None:
                account = ExchangeAccount(
                    user_id=user.id,
                    exchange_name="binance",
                    market_type="usds_m_futures",
                    api_key_enc=enc_key,
                    api_secret_enc=enc_sec,
                    passphrase_enc=None,
                    hedge_mode_enabled=hedge,
                    is_testnet=args.testnet,
                    is_active=True,
                )
                db.add(account)
                db.flush()
                print(f"[created] exchange_account id={account.id} testnet={account.is_testnet}")
            else:
                existing.api_key_enc = enc_key
                existing.api_secret_enc = enc_sec
                existing.hedge_mode_enabled = hedge
                existing.is_testnet = args.testnet
                existing.is_active = True
                print(f"[updated] exchange_account id={existing.id} testnet={existing.is_testnet}")

        db.commit()
        print("[ok] committed.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
