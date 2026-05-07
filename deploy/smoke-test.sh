#!/usr/bin/env bash
# smoke-test.sh — VPS 배포 직후 종합 검증.
#
# 실행 위치: VPS 의 ~/binance-auto-trader (또는 backend) 에서 trader 사용자로.
# 전제: docker compose -f ... up -d --build 완료 후 1~2분 경과 (서비스 안정화).
#
# 검사 항목:
#   1. 모든 컨테이너 Running / Healthy
#   2. api 의 /health 응답 200
#   3. alembic head 가 latest migration 과 일치
#   4. db 연결 (Neon 또는 로컬) — strategy_instances 쿼리 1건 가능
#   5. redis ping 응답
#   6. scheduler 워커가 1분 내 guarded_job 실행 흔적 (logs)
#   7. user-stream listenKey 발급 (Binance 인증 통과 의미)
#   8. settings 환경변수 누락 검증 (필수 키 모두 set)
#
# 실패 시 exit code != 0 + 어느 단계 실패인지 보고.

set -uo pipefail

cd "$(dirname "$0")/.." 2>/dev/null || cd "$(dirname "$0")"
[ -f docker-compose.yml ] || cd backend

GREEN='\033[32m'
RED='\033[31m'
YELLOW='\033[33m'
NC='\033[0m'

PASS=0
FAIL=0

ok()   { echo -e "${GREEN}✓${NC} $1"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}✗${NC} $1"; FAIL=$((FAIL+1)); }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }

echo "==> [1/8] 컨테이너 상태"
EXPECTED=("api" "scheduler" "user-stream" "redis")
for svc in "${EXPECTED[@]}"; do
    status=$(docker compose ps --format "{{.Service}}\t{{.State}}" 2>/dev/null | grep "^${svc}" | awk '{print $2}')
    if [ "$status" = "running" ]; then
        ok "${svc}: ${status}"
    else
        fail "${svc}: ${status:-not found}"
    fi
done

echo ""
echo "==> [2/8] api /health 응답"
HEALTH=$(curl -sf -m 5 http://127.0.0.1:8000/health 2>/dev/null || echo "FAIL")
if echo "$HEALTH" | grep -q "ok\|healthy\|status"; then
    ok "/health: ${HEALTH:0:80}"
else
    fail "/health 응답 없음 또는 비정상 (api 컨테이너 로그 확인: docker compose logs api --tail=30)"
fi

echo ""
echo "==> [3/8] alembic head 검사"
# alembic 의 current 출력은 SHA (<rev>) 만 보임 — 우리 마이그레이션은 파일명을
# revision 으로 사용하지 않으므로, 파일에서 'revision = ' 라인 추출해 비교한다.
# 5-07 fix: 이전엔 '[0-9]{4}_[a-z_]+' regex 가 파일명 안의 'tp6_to_tp10' 같이
# 숫자 포함된 부분을 truncate 해서 false-negative 발생.
LATEST_FILE=$(ls alembic/versions/*.py 2>/dev/null | sort | tail -1)
if [ -z "$LATEST_FILE" ]; then
    fail "alembic versions 비어 있음"
else
    LATEST_REV=$(grep -E "^revision[: ]" "$LATEST_FILE" | head -1 | grep -oE "['\"][^'\"]+['\"]" | tr -d "'\"" | head -1)
    ACTUAL=$(docker compose exec -T api alembic current 2>/dev/null | grep -oE '\b[a-f0-9]{8,}\b|\b[0-9]{4}_[a-z_0-9]+' | head -1)
    LATEST_BASENAME=$(basename "$LATEST_FILE" .py)
    if [ -n "$ACTUAL" ] && { [ "$ACTUAL" = "$LATEST_REV" ] || [ "$ACTUAL" = "$LATEST_BASENAME" ]; }; then
        ok "alembic head = ${ACTUAL} (latest migration 과 일치)"
    elif [ -z "$ACTUAL" ]; then
        fail "alembic current 호출 실패 (DB 연결 또는 alembic.ini 문제)"
    else
        fail "alembic head=${ACTUAL} ≠ latest=${LATEST_REV:-$LATEST_BASENAME} — 'docker compose exec api alembic upgrade head' 필요"
    fi
fi

echo ""
echo "==> [4/8] DB 연결"
DB_OK=$(docker compose exec -T api python -c "
from app.core.database import SessionLocal
from app.models.strategy_instance import StrategyInstance
from sqlalchemy import select, func
db = SessionLocal()
try:
    cnt = db.execute(select(func.count()).select_from(StrategyInstance)).scalar()
    print(f'OK: {cnt} strategies in DB')
except Exception as e:
    print(f'FAIL: {e}')
finally:
    db.close()
" 2>&1 | tail -1)
if echo "$DB_OK" | grep -q "^OK"; then
    ok "DB query: ${DB_OK}"
else
    fail "DB query 실패: ${DB_OK}"
fi

echo ""
echo "==> [5/8] Redis ping"
REDIS=$(docker compose exec -T redis redis-cli ping 2>&1 | tr -d '\r')
if [ "$REDIS" = "PONG" ]; then
    ok "redis: PONG"
else
    fail "redis ping 실패: ${REDIS}"
fi

echo ""
echo "==> [6/8] scheduler 워커 로그 (최근 60s)"
SCHED_LOG=$(docker compose logs scheduler --since 60s 2>/dev/null | grep -E "guarded_job|tp_sl|stage_trigger|reconcile" | wc -l)
if [ "$SCHED_LOG" -gt 0 ]; then
    ok "scheduler 활동 ${SCHED_LOG} lines/min"
else
    warn "scheduler 활동 없음 — 운영 1분 더 대기 후 재실행 또는 logs 확인"
fi

echo ""
echo "==> [7/8] user-stream listenKey"
US_LOG=$(docker compose logs user-stream --tail=30 2>/dev/null | grep -E "listenKey|user_data|websocket" | tail -1)
if [ -n "$US_LOG" ]; then
    ok "user-stream 가동: ${US_LOG:0:100}"
else
    warn "user-stream 로그에 listenKey 흔적 없음 — 첫 strategy 시작 시점에 발급되므로 정상일 수 있음"
fi

echo ""
echo "==> [8/8] 필수 환경변수 검사"
REQUIRED_VARS=("SECRET_KEY" "ENCRYPTION_KEY" "DATABASE_URL")
RECOMMENDED_VARS=("TELEGRAM_BOT_TOKEN" "TELEGRAM_CHAT_ID" "DAILY_LOSS_LIMIT_USDT" \
                  "MAX_CONCURRENT_STRATEGIES_PER_ACCOUNT" "MAX_STRATEGY_CAPITAL_PCT_OF_BALANCE" \
                  "ALLOWED_SYMBOLS_CSV" "SENTRY_DSN")
for var in "${REQUIRED_VARS[@]}"; do
    val=$(docker compose exec -T api printenv "$var" 2>/dev/null || echo "")
    if [ -n "$val" ] && [ "$val" != "change_me" ] && [ "$val" != "change-me" ]; then
        ok "${var}: 설정됨"
    else
        fail "${var}: 미설정 또는 default — .env 확인 필수"
    fi
done
for var in "${RECOMMENDED_VARS[@]}"; do
    val=$(docker compose exec -T api printenv "$var" 2>/dev/null || echo "")
    if [ -z "$val" ]; then
        warn "${var}: 미설정 (mainnet 권장)"
    else
        echo -e "  ${GREEN}·${NC} ${var}: 설정됨"
    fi
done

echo ""
echo "============================================================="
if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}✅ Smoke test 통과${NC} (PASS=$PASS)"
    echo "다음: 대시보드 접속 → 「💼 계정」 → 「🔑 키 변경」 으로 testnet 키 등록"
    exit 0
else
    echo -e "${RED}❌ Smoke test 실패${NC} (PASS=$PASS, FAIL=$FAIL)"
    echo "위 ✗ 항목 해결 후 재실행. 상세 로그: docker compose logs <service>"
    exit 1
fi
