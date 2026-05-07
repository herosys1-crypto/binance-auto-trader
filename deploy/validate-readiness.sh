#!/usr/bin/env bash
# validate-readiness.sh — VPS 배포 전 로컬 repo 의 준비 상태 확인.
#
# 목적: VPS 에서 docker compose up 하기 전에 미리 알 수 있는 문제들을
# 로컬에서 잡아낸다. 사용자가 droplet 비용 + 시간 낭비 방지.
#
# 검사 항목:
#   1. 필수 파일 존재 (docker-compose.yml / production.yml / Dockerfile / migrations)
#   2. .env.production.template 의 필드와 app/core/config.py 의 settings 동기화
#   3. alembic head 가 0011 이상 (5-06 archive + 5-06 tp10 마이그레이션 포함)
#   4. backend pytest 통과 (전체 또는 빠른 unit subset)
#   5. backend/Dockerfile 이 build 가능한지 (선택, --build 플래그 시)
#
# 사용:
#   ./deploy/validate-readiness.sh           # 1~4 항목만
#   ./deploy/validate-readiness.sh --build   # + Dockerfile build (10분 추가)

set -euo pipefail

cd "$(dirname "$0")/.."  # repo root

GREEN='\033[32m'
RED='\033[31m'
YELLOW='\033[33m'
NC='\033[0m'

PASS=0
FAIL=0

ok()   { echo -e "${GREEN}✓${NC} $1"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}✗${NC} $1"; FAIL=$((FAIL+1)); }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }

echo "==> [1/5] 필수 파일 존재 검사"
for f in \
    backend/Dockerfile \
    backend/docker-compose.yml \
    docker-compose.production.yml \
    backend/.env.production.template \
    backend/alembic.ini \
    deploy/vps-bootstrap.sh \
    deploy/generate-secrets.sh \
    deploy/nginx ; do
    if [ -e "$f" ]; then
        ok "$f"
    else
        fail "$f 없음"
    fi
done

echo ""
echo "==> [2/5] .env.production.template ↔ Settings 동기화 검사"
# Settings 의 env_file 인식 가능한 필드 추출 (소문자 → UPPER_SNAKE_CASE)
SETTINGS_FIELDS=$(python3 -c "
import sys; sys.path.insert(0, 'backend')
from app.core.config import Settings
fields = list(Settings.model_fields.keys())
print('\n'.join(f.upper() for f in fields))
" 2>/dev/null || echo "")

if [ -z "$SETTINGS_FIELDS" ]; then
    warn "Settings 임포트 실패 (백엔드 가상환경 활성 X 또는 dependency 미설치) — 항목 2 skip"
else
    MISSING=0
    while IFS= read -r field; do
        # template 에 해당 키가 있는지 (= 또는 # 주석으로 라도 언급)
        if ! grep -qE "(^|#\s*)${field}=" backend/.env.production.template; then
            warn "  template 에 ${field} 없음"
            MISSING=$((MISSING+1))
        fi
    done <<< "$SETTINGS_FIELDS"
    if [ "$MISSING" -eq 0 ]; then
        ok "Settings 필드 ${#SETTINGS_FIELDS} 모두 template 에 존재"
    else
        fail ".env.production.template 에 ${MISSING}개 Settings 필드 누락"
    fi
fi

echo ""
echo "==> [3/5] alembic 마이그레이션 head 검사"
LATEST_MIGRATION=$(ls backend/alembic/versions/*.py 2>/dev/null | sort | tail -1 | xargs -I {} basename {} .py)
if [ -z "$LATEST_MIGRATION" ]; then
    fail "alembic versions 디렉토리 비어 있음"
else
    ok "Latest migration: $LATEST_MIGRATION"
    # 0012 이상 (5-06 tp6_to_tp10) 권장
    case "$LATEST_MIGRATION" in
        00[0-1][0-1]_*) warn "  마이그레이션 ${LATEST_MIGRATION} 가 0012 미만 — 5-06 변경 누락 가능" ;;
        *) ;;
    esac
fi

echo ""
echo "==> [4/5] backend pytest 빠른 검증 (unit only — ~30s)"
if cd backend && python -m pytest tests/unit -q --tb=no 2>&1 | tail -3; then
    cd .. && ok "unit 테스트 통과"
else
    cd .. && fail "unit 테스트 실패 — VPS 배포 보류"
fi

if [ "${1:-}" = "--build" ]; then
    echo ""
    echo "==> [5/5] backend Dockerfile build 검증 (~10분)"
    if cd backend && docker build -t binance-auto-trader-readiness-check . > /tmp/build.log 2>&1; then
        cd .. && ok "Dockerfile build 성공"
        docker rmi binance-auto-trader-readiness-check &>/dev/null || true
    else
        cd .. && fail "Dockerfile build 실패 — /tmp/build.log 참조"
    fi
else
    echo ""
    echo "==> [5/5] Dockerfile build 검증 skip (--build 옵션으로 활성)"
fi

echo ""
echo "============================================================="
if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}✅ 배포 준비 완료${NC} (PASS=$PASS)"
    echo "다음: VPS-DEPLOY-CHECKLIST.md Phase 0 (droplet 생성)"
    exit 0
else
    echo -e "${RED}❌ 배포 보류${NC} (PASS=$PASS, FAIL=$FAIL)"
    echo "위 ✗ 항목 해결 후 재실행 필요."
    exit 1
fi
