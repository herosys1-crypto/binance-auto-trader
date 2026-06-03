#!/usr/bin/env bash
# =============================================================================
# Setup HTTPS (self-signed) — 사장님 다중 Sub-Account 운영 전 API key 평문 차단
# =============================================================================
# 2026-06-03 #10: 도메인 없이 IP 만으로 HTTPS 자동 설정.
# 사장님 VPS (root) 에서 1회 실행:
#   bash deploy/setup-https-self-signed.sh
#
# 작업 흐름:
#   1. nginx 설치 (없으면)
#   2. self-signed cert 생성 (10년 유효, IP 159.65.137.250 포함)
#   3. /etc/nginx/sites-available/trader 배치
#   4. /etc/nginx/sites-enabled/ symlink
#   5. nginx -t && systemctl reload nginx
#
# 사장님 브라우저: https://159.65.137.250 접속 시 「고급 → 진행」 1회 클릭.
# (cert 신뢰 추가 옵션: 브라우저 설정 → 인증서 → 가져오기, 자세한 안내는 README)
#
# 도메인 구매 후 Let's Encrypt 교체:
#   bash deploy/setup-https-letsencrypt.sh trader.yourdomain.com
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CERT_DIR="/etc/nginx/ssl"
CERT_NAME="trader-self-signed"
CONF_TEMPLATE="${REPO_ROOT}/deploy/nginx/trader-https-self-signed.conf.template"
NGINX_AVAILABLE="/etc/nginx/sites-available/trader"
NGINX_ENABLED="/etc/nginx/sites-enabled/trader"
VPS_IP="${VPS_IP:-159.65.137.250}"

echo "════════════════════════════════════════════════════════════════"
echo "  HTTPS Setup (self-signed) — VPS IP: ${VPS_IP}"
echo "════════════════════════════════════════════════════════════════"

# 1. nginx 설치 (Ubuntu/Debian)
if ! command -v nginx &> /dev/null; then
  echo "[1/5] nginx 설치 중..."
  apt-get update -qq
  apt-get install -y nginx openssl
else
  echo "[1/5] ✅ nginx 이미 설치됨"
fi

# 2. self-signed cert 생성 (10년)
mkdir -p "${CERT_DIR}"
if [[ -f "${CERT_DIR}/${CERT_NAME}.crt" ]]; then
  echo "[2/5] ⚠️  기존 cert 발견 (${CERT_DIR}/${CERT_NAME}.crt) — skip"
  echo "       재생성하려면: rm ${CERT_DIR}/${CERT_NAME}.* 후 재실행"
else
  echo "[2/5] self-signed cert 생성 중 (10년 유효, CN=${VPS_IP})..."
  openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout "${CERT_DIR}/${CERT_NAME}.key" \
    -out "${CERT_DIR}/${CERT_NAME}.crt" \
    -subj "/C=KR/ST=Seoul/L=Seoul/O=BinanceAutoTrader/CN=${VPS_IP}" \
    -addext "subjectAltName=IP:${VPS_IP},DNS:localhost"
  chmod 600 "${CERT_DIR}/${CERT_NAME}.key"
  echo "       ✅ cert 생성됨"
fi

# 3. nginx config 배치
if [[ ! -f "${CONF_TEMPLATE}" ]]; then
  echo "❌ ${CONF_TEMPLATE} 없음 — git pull 후 재시도"
  exit 1
fi
cp "${CONF_TEMPLATE}" "${NGINX_AVAILABLE}"
echo "[3/5] ✅ nginx config 배치 (${NGINX_AVAILABLE})"

# 4. /etc/nginx/sites-enabled/ symlink
if [[ -L "${NGINX_ENABLED}" || -f "${NGINX_ENABLED}" ]]; then
  echo "[4/5] ⚠️  기존 symlink 발견 — 갱신"
  rm -f "${NGINX_ENABLED}"
fi
ln -s "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"
# default site 비활성 (port 80 충돌 차단)
if [[ -L /etc/nginx/sites-enabled/default ]]; then
  rm /etc/nginx/sites-enabled/default
  echo "       default site 비활성"
fi
echo "       ✅ symlink: ${NGINX_ENABLED}"

# 5. nginx -t + reload
echo "[5/5] nginx config 검증..."
if nginx -t; then
  systemctl reload nginx || systemctl restart nginx
  echo "       ✅ nginx reload 완료"
else
  echo "❌ nginx config 검증 실패 — 위 에러 확인 후 수동 fix"
  exit 1
fi

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  ✅ HTTPS 설정 완료!"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "📌 사장님 브라우저:"
echo "   https://${VPS_IP}  ← HTTPS 접속"
echo "   첫 접속 시 「보안 경고」 → 「고급 → 진행」 1회 클릭"
echo "   (Chrome 의 「이 사이트 신뢰」 옵션으로 영구 등록 가능)"
echo ""
echo "📌 HTTP 접속 자동 차단:"
echo "   http://${VPS_IP}  → 자동 https:// 리다이렉트"
echo ""
echo "📌 도메인 구매 후 Let's Encrypt 교체:"
echo "   bash ${REPO_ROOT}/deploy/setup-https-letsencrypt.sh trader.yourdomain.com"
echo ""
echo "📌 cert 정보:"
echo "   유효기간: 10년 (2036-06-03 까지)"
echo "   위치: ${CERT_DIR}/${CERT_NAME}.{crt,key}"
echo ""
