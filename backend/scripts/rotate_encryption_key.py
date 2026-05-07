"""ENCRYPTION_KEY 회전 도구 — exchange_account 의 암호화 컬럼을 새 키로 재암호화.

배경 (MAINNET-CHECKLIST.md 1-3):
  채팅에 노출된 ENCRYPTION_KEY 로 암호화된 자격증명을 새 키로 마이그레이션한다.
  대상 컬럼: exchange_accounts.{api_key_enc, api_secret_enc, passphrase_enc}.

  Fernet 은 키 자체를 토큰에 매핑하지 않으므로, 옛 키로 복호화 후 새 키로 재암호화하는
  방식이 유일한 안전한 회전 절차.

사용법:

  # 1) Dry-run (DB 변경 없이 검증만)
  cd backend
  NEW_ENCRYPTION_KEY="<새-Fernet-키>" python scripts/rotate_encryption_key.py --dry-run

  # 2) 실 실행 (옛 ENCRYPTION_KEY 는 .env 에서 그대로, NEW_ENCRYPTION_KEY 는 환경변수로)
  NEW_ENCRYPTION_KEY="<새-Fernet-키>" python scripts/rotate_encryption_key.py

  # 3) 백업 경로 지정 (기본: ./key-rotation-backup-YYYYMMDD-HHMMSS.json)
  NEW_ENCRYPTION_KEY="<새-키>" python scripts/rotate_encryption_key.py --backup-path /path/to/backup.json

회전 절차 (전체):
  1. 새 Fernet 키 생성:
       python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  2. NEW_ENCRYPTION_KEY 환경변수에 설정 (현재 .env 의 ENCRYPTION_KEY 는 그대로 둠)
  3. 본 스크립트 --dry-run 으로 검증
  4. 실 실행 — 백업 JSON 자동 생성
  5. .env 의 ENCRYPTION_KEY 를 새 값으로 교체
  6. 백엔드 (uvicorn / docker-compose) 재시작
  7. 백업 JSON 안전한 곳으로 옮김 + 검증 후 폐기

Roll-back: 5단계까지만 진행 후 .env 를 옛 값으로 되돌리고 재시작 — DB 는 이미 새 키로
바뀌었으므로 복호화 실패. 그 경우 백업 JSON 의 옛 cipher_text 로 DB 복원 필요
(아래 RESTORE 섹션 참고).

RESTORE (긴급 복구):
  백업 JSON 의 형식:
    [{"id": 1, "api_key_enc": "old-cipher", "api_secret_enc": "...", "passphrase_enc": null}, ...]
  psql 에서:
    UPDATE exchange_accounts SET api_key_enc=$1, api_secret_enc=$2, passphrase_enc=$3
    WHERE id=$4;
  본 스크립트의 --restore-from <backup.json> 옵션으로 자동화 가능.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from cryptography.fernet import Fernet, InvalidToken  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.exchange_account import ExchangeAccount  # noqa: E402

# 컬럼 목록 — 향후 새 암호화 컬럼 추가 시 여기에 등록.
ENCRYPTED_COLUMNS = ("api_key_enc", "api_secret_enc", "passphrase_enc")


def _load_fernet(key: str, label: str) -> Fernet:
    if not key:
        raise SystemExit(f"[fatal] {label} 가 비어 있음")
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as e:
        raise SystemExit(
            f"[fatal] {label} 가 valid Fernet key 가 아님 (URL-safe base64 32바이트 필요): {e}"
        )


def _resolve_new_key(cli_arg: str | None) -> str:
    """--new-key CLI 우선, 없으면 NEW_ENCRYPTION_KEY 환경변수."""
    key = cli_arg or os.environ.get("NEW_ENCRYPTION_KEY", "")
    if not key:
        raise SystemExit(
            "[fatal] NEW_ENCRYPTION_KEY 환경변수 또는 --new-key 인자 필요. "
            "키 생성: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    return key.strip()


def rotate(
    db,
    old_fernet: Fernet,
    new_fernet: Fernet,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    """모든 ExchangeAccount 의 암호화 컬럼을 회전. 결과 dict 반환.

    반환:
      {
        "rows": int,                          # 처리된 row 개수
        "rotated": [{"id": ..., "api_key_enc": "<old>", ...}],  # 백업용
        "failed": [{"id": ..., "column": ..., "error": ...}],
      }

    실패 시 (decrypt 또는 verify) 트랜잭션 rollback 보장 — caller 가 commit 결정.
    """
    rows = db.query(ExchangeAccount).order_by(ExchangeAccount.id.asc()).all()
    rotated: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for row in rows:
        old_values: dict[str, str | None] = {col: getattr(row, col) for col in ENCRYPTED_COLUMNS}
        new_values: dict[str, str | None] = {}

        # 1) 모든 컬럼 옛 키로 복호화 시도 (실패 시 fail-fast — 회전 안전 우선)
        plain_values: dict[str, str | None] = {}
        for col in ENCRYPTED_COLUMNS:
            cipher = old_values[col]
            if cipher is None:
                plain_values[col] = None
                continue
            try:
                plain_values[col] = old_fernet.decrypt(cipher.encode("utf-8")).decode("utf-8")
            except InvalidToken:
                failed.append({
                    "id": row.id,
                    "column": col,
                    "error": "decrypt-with-old-key failed (옛 ENCRYPTION_KEY 가 .env 와 불일치?)",
                })
                continue
            except Exception as e:
                failed.append({"id": row.id, "column": col, "error": f"decrypt error: {e}"})
                continue

        if any(f["id"] == row.id for f in failed):
            continue  # 이 row 는 안전상 건너뜀

        # 2) 새 키로 재암호화 + 즉시 round-trip 검증
        for col, plain in plain_values.items():
            if plain is None:
                new_values[col] = None
                continue
            new_cipher = new_fernet.encrypt(plain.encode("utf-8")).decode("utf-8")
            # round-trip — 새 키로 다시 복호화해서 plain 과 같은지 확인
            try:
                back = new_fernet.decrypt(new_cipher.encode("utf-8")).decode("utf-8")
            except Exception as e:
                failed.append({"id": row.id, "column": col, "error": f"verify error: {e}"})
                continue
            if back != plain:
                failed.append({
                    "id": row.id,
                    "column": col,
                    "error": "round-trip mismatch (cryptography 라이브러리 이상)",
                })
                continue
            new_values[col] = new_cipher

        if any(f["id"] == row.id for f in failed):
            continue

        # 3) 백업 entry 기록
        rotated.append({
            "id": row.id,
            "user_id": row.user_id,
            "exchange_name": row.exchange_name,
            "is_testnet": row.is_testnet,
            **{col: old_values[col] for col in ENCRYPTED_COLUMNS},
        })

        # 4) 실 적용 (dry-run 이 아닐 때만)
        if not dry_run:
            for col, new_cipher in new_values.items():
                setattr(row, col, new_cipher)

    return {"rows": len(rows), "rotated": rotated, "failed": failed}


def _write_backup(path: str, rotated: list[dict[str, Any]]) -> None:
    payload = {
        "rotated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": 1,
        "note": "옛 ENCRYPTION_KEY 로 암호화된 cipher_text. 긴급 복구용 — 안전 보관 후 폐기.",
        "accounts": rotated,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def restore(db, backup_path: str) -> dict[str, Any]:
    """백업 JSON 의 옛 cipher_text 를 DB 에 다시 써넣음 (긴급 복구)."""
    with open(backup_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    accounts = payload.get("accounts") or []
    restored = 0
    missing: list[int] = []
    for entry in accounts:
        row = db.get(ExchangeAccount, entry["id"])
        if not row:
            missing.append(entry["id"])
            continue
        for col in ENCRYPTED_COLUMNS:
            if col in entry:
                setattr(row, col, entry[col])
        restored += 1
    return {"restored": restored, "missing": missing}


def main() -> int:
    parser = argparse.ArgumentParser(description="ENCRYPTION_KEY 회전 도구")
    parser.add_argument("--dry-run", action="store_true", help="DB 변경 없이 검증만")
    parser.add_argument(
        "--new-key",
        default=None,
        help="새 Fernet 키 (없으면 NEW_ENCRYPTION_KEY 환경변수)",
    )
    parser.add_argument(
        "--backup-path",
        default=None,
        help="백업 JSON 경로 (기본: ./key-rotation-backup-YYYYMMDD-HHMMSS.json)",
    )
    parser.add_argument(
        "--restore-from",
        default=None,
        help="백업 JSON 으로부터 옛 cipher_text 복원 (rotation 의 역방향)",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        # ---- 복구 모드 ----
        if args.restore_from:
            print(f"[restore] backup={args.restore_from}")
            result = restore(db, args.restore_from)
            print(f"[restore] restored={result['restored']} missing_ids={result['missing']}")
            if args.dry_run:
                db.rollback()
                print("[restore] dry-run — DB 변경 안 함")
                return 0
            db.commit()
            print("[restore] commit 완료. 백엔드 재시작 + 옛 ENCRYPTION_KEY 로 .env 복원 필요.")
            return 0

        # ---- 회전 모드 ----
        old_key = settings.encryption_key
        new_key = _resolve_new_key(args.new_key)
        if old_key == new_key:
            raise SystemExit("[fatal] 옛 키 == 새 키 — 회전 의미 없음")

        old_fernet = _load_fernet(old_key, "ENCRYPTION_KEY (옛)")
        new_fernet = _load_fernet(new_key, "NEW_ENCRYPTION_KEY (새)")

        print(f"[rotate] dry_run={args.dry_run}")
        print(f"[rotate] old_key head={old_key[:8]}...  len={len(old_key)}")
        print(f"[rotate] new_key head={new_key[:8]}...  len={len(new_key)}")

        result = rotate(db, old_fernet, new_fernet, dry_run=args.dry_run)
        print("")
        print(f"[summary] rows={result['rows']}  rotated={len(result['rotated'])}  failed={len(result['failed'])}")

        if result["failed"]:
            print("")
            print("[failed entries]")
            for f in result["failed"]:
                print(f"  - id={f['id']} column={f['column']} error={f['error']}")
            print("")
            print("[abort] 실패 row 가 있어 회전 중단. DB 는 변경 없음.")
            db.rollback()
            return 2

        # 백업 — dry-run 도 백업 만듦 (사전 검증용 + 실 회전 직전 비교용)
        backup_path = args.backup_path or (
            f"./key-rotation-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        )
        _write_backup(backup_path, result["rotated"])
        print(f"[backup] {backup_path} ({len(result['rotated'])} accounts)")

        if args.dry_run:
            db.rollback()
            print("")
            print("[done] dry-run 성공 — DB 변경 안 함. 실 회전: --dry-run 빼고 다시 실행.")
            return 0

        db.commit()
        print("")
        print("[done] 회전 commit 완료.")
        print("[next] 다음 단계:")
        print("  1) .env 의 ENCRYPTION_KEY 를 새 값으로 교체")
        print("  2) 백엔드 재시작 (uvicorn / docker-compose restart api)")
        print("  3) 새 키로 거래소 호출 1건 검증 (예: scripts/check_binance_key.py)")
        print(f"  4) 백업 ({backup_path}) 안전한 곳으로 옮김 + 검증 후 폐기")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
