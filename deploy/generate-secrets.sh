#!/usr/bin/env bash
# generate-secrets.sh — production .env 의 자격증명 신규 생성.
#
# 5-04 핸드오프부터 보류 중인 보안 로테이션 항목 자동 생성:
#   - SECRET_KEY (JWT 서명, secrets.token_urlsafe(48))
#   - ENCRYPTION_KEY (Fernet, API key 암호화)
#   - POSTGRES_PASSWORD (로컬 db 사용 시, Neon 사용 시 무관)
#   - REDIS_PASSWORD (옵션)
#
# 외부 자격증명 (수동 발급 필요 — 출력에 안내):
#   - DATABASE_URL — Neon console 에서 신규 password 로 reset 후 복사
#   - BINANCE_API_KEY/SECRET — Binance API Management (mainnet, IP 화이트리스트 필수)
#   - TELEGRAM_BOT_TOKEN — @BotFather 새 봇 생성
#   - TELEGRAM_CHAT_ID — 봇과 1:1 채팅 후 getUpdates
#   - SENTRY_DSN — sentry.io 새 프로젝트
#
# 실행:
#   ./deploy/generate-secrets.sh > /tmp/new-secrets.env
#   # 출력을 .env 에 수동 복사 (또는 sed 로 .env 의 placeholder 자동 교체)

set -euo pipefail

if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 가 필요합니다 (sudo apt install python3)" >&2
    exit 1
fi

# Python 의 cryptography 가 설치돼 있는지 — Fernet key 생성용
HAS_CRYPTO=0
if python3 -c "from cryptography.fernet import Fernet" 2>/dev/null; then
    HAS_CRYPTO=1
fi

SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
POSTGRES_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
REDIS_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")

if [ "$HAS_CRYPTO" -eq 1 ]; then
    ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
else
    ENCRYPTION_KEY="<INSTALL cryptography first: pip3 install cryptography>"
fi

cat <<EOF
# ─── 신규 자동 생성 (안전하게 보관 — 잃어버리면 기존 데이터 복호화 불가) ───
SECRET_KEY=${SECRET_KEY}
ENCRYPTION_KEY=${ENCRYPTION_KEY}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
REDIS_PASSWORD=${REDIS_PASSWORD}

# ─── 수동 발급 필요 (각 service console 에서) ───

# 1. Neon DB — https://console.neon.tech/
#    Project → Roles → neondb_owner → Reset password (새 비밀번호 받음)
#    Connection details → DATABASE_URL 복사 (?sslmode=require 포함)
DATABASE_URL=postgresql+psycopg2://neondb_owner:<NEW_NEON_PASSWORD>@<NEON_ENDPOINT>.aws.neon.tech/neondb?sslmode=require

# 2. Binance Mainnet API — https://www.binance.com/en/my/settings/api-management
#    - Enable Futures: ✅
#    - Enable Spot: ❌ (선물 전용)
#    - Enable Withdrawals: ❌ (절대 OFF)
#    - Restrict access to trusted IPs: ✅ + VPS 공인 IP 입력
BINANCE_API_KEY=<MAINNET_API_KEY>
BINANCE_API_SECRET=<MAINNET_API_SECRET>
BINANCE_FUTURES_BASE_URL=https://fapi.binance.com
BINANCE_FUTURES_TESTNET_BASE_URL=https://testnet.binancefuture.com

# 3. Telegram — @BotFather 에서 /newbot → token 받음
#    Chat ID: 봇과 1:1 채팅 후 https://api.telegram.org/bot<TOKEN>/getUpdates
TELEGRAM_BOT_TOKEN=<NEW_BOTFATHER_TOKEN>
TELEGRAM_CHAT_ID=<YOUR_CHAT_ID>

# 4. Sentry (선택, mainnet 권장) — https://sentry.io/
#    Create Project → Python/FastAPI → DSN 복사
SENTRY_DSN=
SENTRY_TRACES_SAMPLE_RATE=0.1
SENTRY_PROFILES_SAMPLE_RATE=0.0

# ─── 환경 ───
APP_NAME=Binance Futures Auto Trading Platform
APP_ENV=production
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=10080
TEST_DATABASE_URL=postgresql+psycopg2://postgres:postgres@db:5432/binance_auto_trader_test
REDIS_URL=redis://redis:6379/0
ENABLE_METRICS=true

# ─── 일일 손실 한도 (선택) ───
# DAILY_LOSS_LIMIT_USDT=500   # 또는 exchange_account 별 daily_loss_limit_usdt 사용

EOF

cat <<'STDERR_NOTICE' >&2

==================================================================
⚠️  보안 주의:
1. 위 출력을 안전한 곳에만 저장 (절대 git commit 또는 텔레그램/슬랙 X)
2. ENCRYPTION_KEY 손실 시 DB 의 암호화된 API key 영구 복호화 불가
   → 1Password / Bitwarden / 종이 안전한 곳에 백업
3. SECRET_KEY 변경 시 모든 사용자 JWT 무효화 (재로그인 필요)
4. mainnet 전환 전 위 5개 외부 자격증명 모두 신규 발급 권장
   (5-04 핸드오프부터 보류 중인 보안 로테이션 = 이 단계)

다음 단계:
- VPS 의 backend/.env 에 위 값 채우기
- chmod 600 backend/.env
- docker compose up -d --build
==================================================================
STDERR_NOTICE
