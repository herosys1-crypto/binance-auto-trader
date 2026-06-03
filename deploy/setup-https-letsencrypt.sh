#!/usr/bin/env bash
# =============================================================================
# Setup HTTPS (Let's Encrypt) — 사장님 도메인 구매 후 정통 HTTPS
# =============================================================================
# 2026-06-03 #10: 도메인 + Let's Encrypt = 브라우저 정상 자물쇠 표시.
# self-signed 의 「보안 경고」 사라짐.
#
# 사전 작업 (사장님):
#   1. 도메인 구매 (gabia/godaddy/namesilo 등, $1~$15/년)
#   2. 도메인 DNS A 레코드 → ${VPS_IP} (159.65.137.250)
#   3. DNS 전파 대기 (보통 10분 ~ 1시간):
#      dig +short trader.yourdomain.com → 159.65.137.250 확인
#
# 사용 (사장님 VPS root):
#   bash deploy/setup-https-letsencrypt.sh trader.yourdomain.com
#
# 작업 흐름:
#   1. 기존 self-signed config 백업
#   2. nginx config 의 server_name 을 도메인으로 교체 (도메인 검증)
#   3. certbot 설치 (없으면)
#   4. certbot --nginx -d ${DOMAIN}  (자동 cert 발급 + nginx config 갱신)
#   5. cron 자동 갱신 (90일마다)
# =============================================================================

set -euo pipefail

DOMAIN="${1:-}"
if [[ -z "${DOMAIN}" ]]; then
  echo "❌ 사용법: bash $0 <도메인> (예: trader.yourdomain.com)"
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONF_TEMPLATE="${REPO_ROOT}/deploy/nginx/trader.conf.template"
NGINX_AVAILABLE="/etc/nginx/sites-available/trader"

echo "════════════════════════════════════════════════════════════════"
echo "  HTTPS Setup (Let's Encrypt) — 도메인: ${DOMAIN}"
echo "════════════════════════════════════════════════════════════════"

# 0. DNS 검증 (도메인이 VPS IP 가리키는지)
EXPECTED_IP="${VPS_IP:-159.65.137.250}"
ACTUAL_IP=$(dig +short "${DOMAIN}" | head -1)
if [[ "${ACTUAL_IP}" != "${EXPECTED_IP}" ]]; then
  echo "❌ DNS A 레코드 미설정 또는 전파 중"
  echo "   도메인 (${DOMAIN}) → ${ACTUAL_IP:-(없음)}"
  echo "   기대 IP: ${EXPECTED_IP}"
  echo "   사장님 도메인 DNS 패널에서 A 레코드 추가 후 10분 ~ 1시간 대기"
  exit 1
fi
echo "[0/5] ✅ DNS 검증 OK (${DOMAIN} → ${ACTUAL_IP})"

# 1. 기존 self-signed config 백업
if [[ -f "${NGINX_AVAILABLE}" ]]; then
  cp "${NGINX_AVAILABLE}" "${NGINX_AVAILABLE}.bak.$(date +%s)"
  echo "[1/5] ✅ 기존 config 백업"
fi

# 2. nginx config 의 server_name 을 도메인으로 교체
# trader.conf.template 의 placeholder 치환
sed "s/trader.yourdomain.com/${DOMAIN}/g" "${CONF_TEMPLATE}" > "${NGINX_AVAILABLE}"
echo "[2/5] ✅ nginx config 의 server_name = ${DOMAIN}"

# 3. certbot 설치 (Ubuntu)
if ! command -v certbot &> /dev/null; then
  echo "[3/5] certbot 설치 중..."
  apt-get update -qq
  apt-get install -y certbot python3-certbot-nginx
else
  echo "[3/5] ✅ certbot 이미 설치됨"
fi

# 4. nginx reload (도메인 config 활성)
nginx -t && systemctl reload nginx
echo "      ✅ nginx 새 config 적용"

# 5. Let's Encrypt cert 자동 발급
echo "[4/5] Let's Encrypt cert 발급 중..."
certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos --register-unsafely-without-email
echo "      ✅ cert 발급 + nginx config 자동 갱신"

# 6. cron 자동 갱신 (certbot 기본 timer 사용 — Ubuntu 는 자동)
systemctl enable --now certbot.timer 2>/dev/null || true
echo "[5/5] ✅ 자동 갱신 활성 (90일 주기 자동)"

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  ✅ HTTPS (Let's Encrypt) 설정 완료!"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "📌 사장님 브라우저:"
echo "   https://${DOMAIN}  ← 정상 자물쇠 표시 (보안 경고 X)"
echo ""
echo "📌 cert 정보:"
echo "   유효기간: 90일 (자동 갱신)"
echo "   위치: /etc/letsencrypt/live/${DOMAIN}/"
echo ""
echo "📌 갱신 테스트:"
echo "   certbot renew --dry-run"
echo ""
