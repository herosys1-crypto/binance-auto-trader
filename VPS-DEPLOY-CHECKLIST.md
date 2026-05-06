# VPS 배포 체크리스트 (testnet → mainnet)

`DEPLOYMENT-DIGITALOCEAN.md` 의 단계별 가이드를 사용자 결정 사항과 함께 정리.
**예상 시간**: 사전 결정 30분 + 실제 셋업 2~3시간 + testnet 검증 24시간.

---

## ✅ 사전 결정 (사용자 직접) — 30분

### 0-A. DigitalOcean 계정 & 결제
- [ ] [DigitalOcean 가입](https://www.digitalocean.com/) (Github 로그인 가능)
- [ ] 결제 카드 등록
- [ ] 2FA 활성화
- [ ] (선택) 첫 가입 시 $200 크레딧 promo 적용 (60일 — 검증 충분)

### 0-B. SSH 키 (없으면 생성)
**Windows PowerShell**:
```powershell
# C:\Users\user\.ssh\ 폴더에 키 없으면 생성
ssh-keygen -t ed25519 -C "binance-trader-vps"
# Enter (default 경로) Enter (passphrase 비워둠 — 또는 입력)
type $env:USERPROFILE\.ssh\id_ed25519.pub
```
출력된 **공개키 한 줄을 메모** (`ssh-ed25519 AAAA... binance-trader-vps`).

### 0-C. 도메인 (옵션 — 권장)
- [ ] [Cloudflare Registrar](https://www.cloudflare.com/products/registrar/) 또는 Namecheap 에서 도메인 구매 (`yourdomain.com` ~$10/년)
- [ ] DNS A record: `trader.yourdomain.com` → (droplet 생성 후 IP 입력)
- 도메인 없이도 가능 — IP 직접 (`http://<IP>:80`), 단 HTTPS 어려움 (Let's Encrypt 가 도메인 요구)

### 0-D. 외부 서비스 (mainnet 직전 필수)
- [ ] **Neon DB** — [console](https://console.neon.tech/) 에서:
  - 현재 plan 확인 (Launch $19/월 → 충분, 또는 quota 검토)
  - "Project Settings → IP Allow" — VPS 셋업 후 droplet 공인 IP 추가
  - "Roles → neondb_owner → Reset password" — mainnet 직전 새 password
- [ ] **Binance Mainnet API** — [API Management](https://www.binance.com/en/my/settings/api-management):
  - Create API → Enable Futures ✅, Spot ❌, Withdrawals ❌
  - **Restrict access to trusted IPs** ✅ + droplet IP 입력 (셋업 후)
- [ ] **Telegram BotFather** — `/newbot` → 새 봇 생성, token 받기
- [ ] **(선택) Sentry** — [sentry.io](https://sentry.io/) → 새 프로젝트 → DSN 복사

---

## 📋 Phase 0 — Droplet 생성 (15분)

### 0-1. Droplet 사양 (DEPLOYMENT-DIGITALOCEAN.md 참조)
- [ ] DO console → Create → Droplet
- [ ] **Region**: Singapore (sgp1) ⭐ Binance Asia API + Neon ap-southeast-1 와 같은 region
- [ ] **Image**: Ubuntu 24.04 LTS x64
- [ ] **Size**: Basic AMD 2 vCPU / 8GB RAM / 160GB SSD ($48/월) — 권장
  - 또는 Regular 2 vCPU / 8GB / 160GB ($40/월) — $8/월 절약
- [ ] **Authentication**: SSH Key — 0-B 의 공개키 붙여넣기
- [ ] **Hostname**: `binance-trader-prod`
- [ ] **Backups**: ✅ 활성 (월 +20% 비용, 주 1회 자동 snapshot)
- [ ] **Monitoring**: ✅ (무료)

### 0-2. Cloud Firewall
- [ ] Networking → Firewalls → Create
- [ ] Inbound: SSH (22) / HTTP (80) / HTTPS (443) 만 허용, 그 외 차단
- [ ] Apply to droplet

### 0-3. 첫 SSH 접속
```bash
# Windows PowerShell 또는 Git Bash:
ssh root@<droplet-ip>
# (방금 등록한 SSH 키로 자동 인증)
```

---

## 📋 Phase 1 — OS hardening + Docker (자동 30분)

### 1-A. bootstrap 스크립트 다운로드 + 실행 (root 로)
```bash
# droplet 에 root 로 ssh 접속한 상태에서:
curl -fsSL https://raw.githubusercontent.com/herosys1-crypto/binance-auto-trader/main/deploy/vps-bootstrap.sh -o vps-bootstrap.sh
chmod +x vps-bootstrap.sh

# 0-B 의 공개키 한 줄을 인자로 전달
./vps-bootstrap.sh "ssh-ed25519 AAAA... binance-trader-vps"
```

스크립트가 자동 처리:
- 시스템 업데이트 + 기본 도구 설치
- non-root 사용자 `trader` 생성 + SSH 키 등록
- ufw 방화벽 (22/80/443 만)
- fail2ban + unattended-upgrades + swap 4GB + chrony NTP
- Docker Engine + Compose plugin
- Docker daemon log rotation

### 1-B. 새 사용자 SSH 검증 (script 완료 후)
```bash
# 별도 터미널에서:
ssh trader@<droplet-ip>
# key auth 정상 동작해야 함 (password 묻지 않음)
```

### 1-C. root SSH 차단 활성 (1-B 성공 후만)
```bash
# trader 사용자로 ssh 접속 후:
sudo systemctl restart sshd
# 이후 root SSH 차단 + password auth 차단 적용됨
```

---

## 📋 Phase 2 — 앱 배포 (30분)

### 2-A. 코드 clone (trader 로)
```bash
ssh trader@<droplet-ip>
cd ~
git clone https://github.com/herosys1-crypto/binance-auto-trader.git
cd binance-auto-trader/backend
```

### 2-B. Production .env 작성
```bash
# 자격증명 자동 생성
chmod +x ../deploy/generate-secrets.sh
../deploy/generate-secrets.sh > /tmp/new-secrets.env

# 위 출력의 SECRET_KEY / ENCRYPTION_KEY / POSTGRES_PASSWORD / REDIS_PASSWORD 자동 생성됨
# 외부 서비스 자격증명은 0-D 에서 발급한 값 채우기:
#   DATABASE_URL (Neon), BINANCE_API_KEY/SECRET, TELEGRAM_BOT_TOKEN, SENTRY_DSN

cp .env.production.template .env
vim .env
# /tmp/new-secrets.env 의 값 + 0-D 자격증명 모두 채우기

chmod 600 .env
```

### 2-C. docker-compose 기동
```bash
cd ~/binance-auto-trader

# Neon DB 사용 시 로컬 db / db-backup 비활성 (선택, 자원 절약)
cat > docker-compose.override.yml <<'EOF'
services:
  db:
    profiles: ["disabled"]
  db-backup:
    profiles: ["disabled"]
EOF

docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build
docker compose ps    # api/scheduler/user-stream/redis/prometheus/grafana 5~6개 Running
docker compose logs api --tail=30
```

### 2-D. Alembic 마이그레이션 (Neon 에 적용)
```bash
docker compose exec api alembic upgrade head
# 기대 head: 0012_template_tp6_to_tp10
```

### 2-E. 첫 사용자 생성
```bash
# UI 회원가입 (테스트 후) 또는 SQL 직접 (admin):
docker compose exec api python -c "
from app.core.database import SessionLocal
from app.models.user import User
from passlib.hash import bcrypt
db = SessionLocal()
u = User(email='herosys1@gmail.com', password_hash=bcrypt.hash('YOUR_PASSWORD'), is_active=True, is_admin=True)
db.add(u); db.commit()
print(f'Created user #{u.id}')
db.close()
"
```

---

## 📋 Phase 3 — Nginx + HTTPS (30분)

도메인 (0-C) 보유 시만. 없으면 Phase 4 로 (HTTP 만, 보안 약함).

### 3-A. DNS 적용 (0-C 의 도메인)
- A record `trader.yourdomain.com` → droplet IP
- 적용 검증: `dig trader.yourdomain.com +short` (droplet IP 반환되어야)

### 3-B. Nginx + Let's Encrypt
```bash
sudo apt install -y nginx certbot python3-certbot-nginx

# template 사용
sudo cp ~/binance-auto-trader/deploy/nginx/trader.conf.template /etc/nginx/sites-available/trader
sudo vim /etc/nginx/sites-available/trader   # server_name 만 도메인으로 수정
sudo ln -s /etc/nginx/sites-available/trader /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# HTTPS 자동 (Let's Encrypt)
sudo certbot --nginx -d trader.yourdomain.com
```

### 3-C. 검증
- [ ] `https://trader.yourdomain.com` 접속 → 대시보드 표시
- [ ] HTTP 자동 HTTPS 리다이렉트
- [ ] `curl http://<droplet-ip>:8000` → connection refused (firewall + nginx 만 listen)

### 3-D. ngrok 폐지 ✓
- 더 이상 ngrok 불필요. 로컬 PC 끄고 VPS 만 운영.

---

## 📋 Phase 4 — testnet 종단간 검증 (24시간)

VPS 가 production .env (mainnet API key) 인 채로 testnet 검증 가능 — UI 의 「거래소 계정 추가」 에서 `is_testnet=true` 선택.

### 핵심 검증 (사용자 클릭 필요)
- [ ] testnet API key 등록 → 잔고 표시 정상
- [ ] 새 전략 시작 (TP1~10 모두 채움) → TP3~5 까지 progression 확인
- [ ] 「📈 시장 순위」 클릭 → 13 period × 2 direction 모두 정상
- [ ] 「💰 증거금 추가」 시연
- [ ] 「🗑」 archive → realized 통계 합계 변화 X
- [ ] 24시간 운영 후 좀비 발생 없음 (`docker stats` 메모리 leak 없음)
- [ ] 텔레그램 알림 끊김 없음

### 알려진 운영 안전망 (5-06 세션 fix)
- 트레일링 peak DB fallback (`#103` 사례 영구 방어)
- 스 단계 자동 status 매핑 (1~10 동적)
- 일일 손실 한도 자동 발동
- soft delete (cascade defense)

---

## 📋 Phase 5 — Mainnet 전환 (1~2시간)

testnet 24시간 검증 통과 후만.

### 5-A. Mainnet API key 등록
- [ ] UI 「거래소 계정 추가」 → mainnet key/secret + `is_testnet=false`
- [ ] 잔고 표시 정상

### 5-B. 첫 거래 (가장 작은 자본)
- [ ] 새 전략: 자본 $20 / 1단계 / TP1 +5% / SL -10%
- [ ] 진입 → TP 또는 수동 정지 → 거래소 ↔ DB 일치 검증

### 5-C. 본격 운영
- [ ] `MAINNET-CHECKLIST.md` 의 모든 항목 ✅
- [ ] 일일 손실 한도 (`exchange_accounts.daily_loss_limit_usdt`) 설정
- [ ] Kill switch 테스트

---

## 💰 월 비용 정리

| 항목 | 비용 |
|---|---|
| DigitalOcean droplet (Basic AMD 2 vCPU 8GB) | $48/월 |
| DigitalOcean Backups (옵션) | +$10/월 (월 20%) |
| Neon DB Launch (이미 결제) | $19/월 |
| 도메인 (옵션) | $10/년 ≈ $1/월 |
| Sentry (free tier 충분) | $0 |
| ngrok (폐지) | **$0** |
| **총** | **~$78/월** (= ~10만원/월) |

mainnet 거래 자본 대비 무시할 수준. 첫 60일 DO promo $200 크레딧 적용 시 거의 무료.

---

## 🆘 문제 발생 시

| 증상 | 첫 점검 |
|---|---|
| droplet 접속 안 됨 | DO Console (브라우저) 또는 firewall 확인 |
| docker compose up 실패 | `docker compose logs <service>` |
| Neon connection 실패 | DATABASE_URL 의 sslmode=require 확인 + Neon IP allowlist |
| nginx 502 | api 컨테이너 가동 확인 + `curl localhost:8000/health` |
| HTTPS 인증서 발급 실패 | DNS 가 제대로 droplet IP 가리키는지 확인 (5분 정도 propagation 시간) |

상세: `RUNBOOK.md` 의 트러블슈팅 섹션.

---

**작성: 2026-05-06. 다음 단계: 사용자가 0-A~0-D (사전 결정) 완료 후 Phase 0 시작.**
