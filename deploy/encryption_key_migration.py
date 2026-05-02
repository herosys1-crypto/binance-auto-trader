"""ENCRYPTION_KEY 마이그레이션 스크립트.

채팅에 노출된 옛 ENCRYPTION_KEY 로 암호화된 거래소 자격증명을 새 키로 재암호화.

사용법 (mainnet 가기 전 실행):
  1. 옛 .env 의 ENCRYPTION_KEY 백업
  2. 새 키 생성:
       python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  3. 이 스크립트의 OLD_KEY, NEW_KEY 변수에 두 값 모두 설정
  4. 실행:
       cd backend
       python3 ../deploy/encryption_key_migration.py
  5. 성공 시 .env 의 ENCRYPTION_KEY 를 새 값으로 교체
  6. backend 재시작

⚠️ 주의:
- 활성 거래 0개 상태에서 실행 권장
- Production DB 백업 후 실행
- 한 번 실행 후 OLD_KEY 값으로 다시 돌아가면 복호화 불가
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
import psycopg2

# =============================================================================
# 설정 — 실행 전 반드시 채울 것
# =============================================================================
OLD_KEY = ""  # 노출된 옛 키 (예: "EoKgJ1FiSq-t5NCefzU-wuHxA8tMWAVKoyUJ8td-DXE=")
NEW_KEY = ""  # 새로 생성한 키
DATABASE_URL = ""  # .env 의 DATABASE_URL 값 (postgresql:// 형식, +psycopg2 빼고)


def main():
    if not OLD_KEY or not NEW_KEY:
        sys.exit("OLD_KEY 와 NEW_KEY 를 먼저 설정하세요")
    if OLD_KEY == NEW_KEY:
        sys.exit("OLD_KEY 와 NEW_KEY 가 같음")
    if not DATABASE_URL:
        sys.exit("DATABASE_URL 을 먼저 설정하세요")

    old_fernet = Fernet(OLD_KEY.encode())
    new_fernet = Fernet(NEW_KEY.encode())

    # 호환성 검증 — 새 키로 한 번 encrypt/decrypt 테스트
    test_text = "migration_test"
    cipher = new_fernet.encrypt(test_text.encode())
    plain = new_fernet.decrypt(cipher).decode()
    assert plain == test_text, "새 키 self-test 실패"

    url = DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://")
    print(f"[*] DB 연결: {url[:50]}...")

    with psycopg2.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, api_key_enc, api_secret_enc
                FROM exchange_accounts
                ORDER BY id
            """)
            rows = cur.fetchall()
            print(f"[*] 마이그레이션 대상: {len(rows)} rows")

            migrated = 0
            failed = 0
            for row_id, api_key_enc, api_secret_enc in rows:
                try:
                    # 옛 키로 복호화 → 새 키로 재암호화
                    api_key_plain = old_fernet.decrypt(api_key_enc.encode()).decode()
                    api_secret_plain = old_fernet.decrypt(api_secret_enc.encode()).decode()

                    new_api_key = new_fernet.encrypt(api_key_plain.encode()).decode()
                    new_api_secret = new_fernet.encrypt(api_secret_plain.encode()).decode()

                    cur.execute(
                        "UPDATE exchange_accounts SET api_key_enc=%s, api_secret_enc=%s WHERE id=%s",
                        (new_api_key, new_api_secret, row_id),
                    )
                    migrated += 1
                    print(f"  ✅ row #{row_id} 마이그레이션 완료")
                except InvalidToken as e:
                    failed += 1
                    print(f"  ❌ row #{row_id} 복호화 실패: {e}")
                except Exception as e:
                    failed += 1
                    print(f"  ❌ row #{row_id} 에러: {e}")

            if failed > 0:
                conn.rollback()
                sys.exit(f"\n실패 {failed} 건 — 전체 롤백. .env 키 변경하지 말 것.")
            conn.commit()
            print(f"\n✅ 완료: {migrated} rows 마이그레이션, commit 완료")
            print(f"   다음 단계: .env 의 ENCRYPTION_KEY 를 새 값으로 교체 + backend 재시작")


if __name__ == "__main__":
    main()
