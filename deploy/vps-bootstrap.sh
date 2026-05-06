#!/usr/bin/env bash
# vps-bootstrap.sh — Ubuntu 24.04 droplet 의 Phase 1 자동화 (root 사용자로 1회 실행).
#
# 실행 방법:
#   1) 새 droplet 에 root 로 ssh 접속
#   2) curl -O https://raw.githubusercontent.com/herosys1-crypto/binance-auto-trader/main/deploy/vps-bootstrap.sh
#      또는 scp 로 업로드 후
#   3) chmod +x vps-bootstrap.sh && ./vps-bootstrap.sh <my-ssh-pubkey-string>
#
# 인자:
#   $1 = trader 사용자가 사용할 SSH 공개키 (~/.ssh/id_ed25519.pub 내용 한 줄)
#        없으면 SSH key 등록 단계 skip — 별도 수동 등록 필요.
#
# 무엇을 하는가 (DEPLOYMENT-DIGITALOCEAN.md Phase 1 의 1-1 ~ 1-11 자동화):
#   - 시스템 업데이트 + 기본 도구
#   - non-root 사용자 'trader' 생성 + SSH 키 등록
#   - SSH 보안 강화 (root 로그인 차단, password auth 차단)
#   - ufw 방화벽 (22/80/443 만)
#   - fail2ban
#   - unattended-upgrades
#   - swap 4GB
#   - NTP 동기화
#   - Docker Engine + Compose
#   - trader 를 docker 그룹에
#   - Docker daemon log rotation
#
# 안전 정책:
#   - 모든 destructive 작업 전 idempotency 체크 (이미 적용됐으면 skip)
#   - SSH 보안 강화는 새 사용자가 SSH 접속 가능 확인 후에만 활성 (script 마지막에 안내)
#   - 실패 시 즉시 중단 (set -euo pipefail)

set -euo pipefail

NEW_USER="trader"
SSH_PUBKEY="${1:-}"

# 1-1: 시스템 업데이트 + 기본 도구
echo "==> [1/10] 시스템 업데이트"
apt update
DEBIAN_FRONTEND=noninteractive apt -y upgrade
DEBIAN_FRONTEND=noninteractive apt -y install \
    curl wget git vim htop jq ufw fail2ban unattended-upgrades \
    ca-certificates gnupg lsb-release chrony

# 1-2: non-root 사용자
echo "==> [2/10] 사용자 ${NEW_USER} 생성"
if id "${NEW_USER}" &>/dev/null; then
    echo "  -> 이미 존재"
else
    adduser --gecos "" --disabled-password "${NEW_USER}"
    usermod -aG sudo "${NEW_USER}"
    echo "${NEW_USER} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-${NEW_USER}
    chmod 440 /etc/sudoers.d/90-${NEW_USER}
fi

# SSH key 등록 (인자 제공 시)
if [ -n "${SSH_PUBKEY}" ]; then
    echo "==> [3/10] SSH 공개키 등록"
    install -d -m 700 -o ${NEW_USER} -g ${NEW_USER} /home/${NEW_USER}/.ssh
    AUTH_KEYS=/home/${NEW_USER}/.ssh/authorized_keys
    if ! grep -qF "${SSH_PUBKEY}" "${AUTH_KEYS}" 2>/dev/null; then
        echo "${SSH_PUBKEY}" >> "${AUTH_KEYS}"
    fi
    chmod 600 "${AUTH_KEYS}"
    chown ${NEW_USER}:${NEW_USER} "${AUTH_KEYS}"
else
    echo "==> [3/10] SSH 공개키 인자 없음 — 수동 등록 필요"
fi

# 1-3: SSH 보안 강화
echo "==> [4/10] SSH hardening (root 로그인 차단 / password 차단)"
SSHD_CONF=/etc/ssh/sshd_config
cp -n "${SSHD_CONF}" "${SSHD_CONF}.bak.$(date +%s)" || true
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' "${SSHD_CONF}"
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' "${SSHD_CONF}"
sed -i 's/^#*PubkeyAuthentication.*/PubkeyAuthentication yes/' "${SSHD_CONF}"
# AllowUsers 명시 (보안 강화)
if ! grep -q "^AllowUsers ${NEW_USER}" "${SSHD_CONF}"; then
    echo "AllowUsers ${NEW_USER}" >> "${SSHD_CONF}"
fi
# sshd 재시작은 script 마지막에 (이전에 trader 로 ssh 가능 확인 권장)

# 1-4: ufw 방화벽
echo "==> [5/10] ufw 방화벽"
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'
ufw --force enable

# 1-5: fail2ban
echo "==> [6/10] fail2ban (SSH brute-force 방어)"
cat > /etc/fail2ban/jail.local <<'EOF'
[sshd]
enabled = true
port = 22
filter = sshd
logpath = /var/log/auth.log
maxretry = 5
bantime = 3600
findtime = 600
EOF
systemctl enable fail2ban
systemctl restart fail2ban

# 1-6: unattended-upgrades
echo "==> [7/10] 자동 보안 패치"
dpkg-reconfigure -f noninteractive unattended-upgrades

# 1-7: Swap 4GB
echo "==> [8/10] Swap 4GB"
if [ ! -f /swapfile ]; then
    fallocate -l 4G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo "/swapfile none swap sw 0 0" >> /etc/fstab
else
    echo "  -> /swapfile 이미 있음"
fi

# 1-8: NTP (chrony)
echo "==> [9/10] NTP 동기화 (chrony)"
systemctl enable chrony
systemctl start chrony

# 1-9, 1-10: Docker Engine + Compose
echo "==> [10/10] Docker 설치"
if ! command -v docker &>/dev/null; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${VERSION_CODENAME}") stable" \
        > /etc/apt/sources.list.d/docker.list
    apt update
    DEBIAN_FRONTEND=noninteractive apt -y install \
        docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    usermod -aG docker "${NEW_USER}"
else
    echo "  -> docker 이미 설치됨"
fi

# 1-11: Docker daemon log rotation
echo "==> Docker log rotation"
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "5"
  }
}
EOF
systemctl restart docker

cat <<'DONE'

=============================================================
✅ Phase 1 완료 — VPS OS hardening + Docker 설치 끝.

다음 단계 (별도 ssh 세션에서):
1) 새 사용자로 SSH 접속 가능한지 확인:
     ssh trader@<droplet-ip>
   (key auth 정상 작동해야 함)

2) 위 1) 성공 후, root SSH 차단 활성:
     sudo systemctl restart sshd

3) Phase 2 진행 (코드 clone + .env 작성):
     cd ~
     git clone https://github.com/herosys1-crypto/binance-auto-trader.git
     cd binance-auto-trader/backend
     cp .env.production.template .env
     # 자격증명 새로 생성 (deploy/generate-secrets.sh 실행)
     vim .env

4) docker compose up:
     cd ..
     docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build

자세한 가이드: DEPLOYMENT-DIGITALOCEAN.md
=============================================================
DONE
