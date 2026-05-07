# VPS 배포 체크리스트 (testnet → mainnet)

`DEPLOYMENT-DIGITALOCEAN.md` 의 단계별 가이드를 사용자 결정 사항과 함께 정리.
**예상 시간**: 사전 결정 30분 + 실제 셋업 2~3시간 + testnet 검증 24시간.

> 🎯 **사용자 의도 (2026-05-07)**: testnet 도 VPS 에 배포해 "실전 테스트처럼" 운영.
> 검증 통과 후 「🔑 키 변경」 (PR #17) 으로 testnet → mainnet 전환. 인프라/도구는 동일.

## 🚀 빠른 시작 (이미 droplet 있는 경우)
```bash
# VPS 의 trader 사용자 ssh 후:
cd ~/binance-auto-trader
git pull origin main

# 1) 로컬 (개발 PC) 에서 사전 검증 — 옵션
./deploy/validate-readiness.sh

# 2) VPS 에서 .env + secrets
chmod +x deploy/generate-secrets.sh
deploy/generate-secrets.sh > /tmp/new-secrets.env
cp backend/.env.production.template backend/.env
# /tmp/new-secrets.env 의 자동 생성 값 + 외부 자격증명 채우기 (Neon, Binance testnet, Telegram)
chmod 600 backend/.env

# 3) 컨테이너 기동
cd backend
docker compose -f docker-compose.yml -f ../docker-compose.production.yml up -d --build

# 4) 알렘빅 + 첫 사용자
docker compose exec api alembic upgrade head
# (User 생성은 VPS-DEPLOY-CHECKLIST 의 2-E)

# 5) 종합 검증
chmod +x ../deploy/smoke-test.sh
../deploy/smoke-test.sh
```

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
u = User(email='herosys1@gmail.com', password_hash=bcrypt.hash('YOUR_PASSWORD'), role='admin', is_active=True)
db.add(u); db.commit()
print(f'Created user #{u.id}')
db.close()
"
```

### 2-F. 종합 검증 (5-07 신규)
```bash
# 1~2분 안정화 후:
chmod +x ~/binance-auto-trader/deploy/smoke-test.sh
~/binance-auto-trader/deploy/smoke-test.sh
```
8개 항목 자동 검증:
- 컨테이너 4개 모두 running
- /health 200
- alembic head 일치
- DB 쿼리 가능 (Neon)
- redis PONG
- scheduler 1분 활동 흔적
- user-stream 정상
- 필수 환경변수 (SECRET_KEY/ENCRYPTION_KEY/DATABASE_URL) + 권장 변수 (TELEGRAM/MAX_*/ALLOWED_*) 검사

모두 ✓ 면 Phase 3 (도메인) 또는 Phase 4 (testnet 검증) 로.

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

VPS 의 .env 는 mainnet 자격증명을 채우되, UI 「💼 계정」 에서 `is_testnet=true` 로 testnet 키를 등록해 testnet 거래로 검증.
또는 testnet 키만 등록한 상태로 시작 → 검증 통과 후 「🔑 키 변경」 (PR #17) 으로 mainnet 키 + 환경 전환.

### 4-A. 핵심 검증 (사용자 클릭)
- [ ] testnet API key 등록 → 잔고 표시 정상 (「💼 계정」)
- [ ] 새 전략 시작 (TP1~10 모두 채움) → TP3~5 까지 progression 확인
- [ ] **최종단계 trigger 표시** (PR #13) — 단계별 계획 테이블 마지막 행에 "최종" 배지 + 「+20% 도달 시」 정상
- [ ] 「📈 시장 순위」 → 13 period × 2 direction 모두 정상
- [ ] 「💰 증거금 추가」 시연 — ISOLATED 자동 적용 + 텔레그램 알림 도착
- [ ] 「🗑」 archive → realized 통계 합계 변화 X
- [ ] 24시간 운영 후 좀비 발생 없음 (`docker stats` 메모리 leak 없음)
- [ ] 텔레그램 알림 끊김 없음

### 4-B. mainnet 안전망 검증 (5-07 신규 — 의도적 손실로 검증)
- [ ] **일일 손실 한도** — testnet 에서 의도적 손실로 80% 도달
  - 예상: status='WARNED' + 텔레그램 「⚠️ [일일 손실 한도 임계치 도달]」 1건 (PR #15)
- [ ] **일일 손실 한도 100% 초과** — 추가 손실
  - 예상: kill-switch 발동 + 텔레그램 「⚠️🔴 [Kill-Switch 발동]」 1건 (PR #15)
  - 신규 strategy create 거부 확인
- [ ] **자본 % 가드** (PR #16) — `MAX_STRATEGY_CAPITAL_PCT_OF_BALANCE=5.0` 설정 후
  잔액의 6% 자본 strategy 생성 시도 → 「자본 상한 초과」 ValueError
- [ ] **심볼 화이트리스트** (PR #16) — `ALLOWED_SYMBOLS_CSV=BTCUSDT,ETHUSDT` 설정 후
  SOLUSDT 시도 → 「허용 목록에 없음」 ValueError
- [ ] **동시성 한도** (PR #16) — `MAX_CONCURRENT_STRATEGIES_PER_ACCOUNT=3` 설정 후
  4번째 strategy 시도 → 「동시 활성 전략 수 한도 (3개) 초과」 ValueError
- [ ] **API 키 회전** (PR #17) — 「💼 계정」 → 「🔑 키 변경」 → 새 testnet 키
  → 텔레그램 「🔑 [API 키 변경]」 audit 도착

### 4-C. 알려진 운영 안전망 (이전 세션 fix)
- 트레일링 peak DB fallback (`#103` 사례 영구 방어)
- 1~10 단계 자동 status 매핑
- soft delete (cascade defense)
- ISOLATED margin 자동 적용 (PR 5-06)

---

## 📋 Phase 5 — Mainnet 전환 (1~2시간)

testnet 24시간 검증 통과 후만.

### 5-A. Mainnet 키 발급 (사용자 직접)
- [ ] [Binance API Management](https://www.binance.com/en/my/settings/api-management) 에서 새 API
- [ ] 권한: Futures ✅ / Spot ❌ / Withdrawals ❌
- [ ] **IP whitelist** ✅ + droplet 공인 IP 입력

### 5-B. ENCRYPTION_KEY 회전 (PR #14, 권장)
```bash
cd ~/binance-auto-trader/backend
NEW_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# Dry-run
NEW_ENCRYPTION_KEY="$NEW_KEY" docker compose exec -T -e NEW_ENCRYPTION_KEY="$NEW_KEY" api \
    python scripts/rotate_encryption_key.py --dry-run

# 실 실행 (백업 JSON 자동 생성)
NEW_ENCRYPTION_KEY="$NEW_KEY" docker compose exec -T -e NEW_ENCRYPTION_KEY="$NEW_KEY" api \
    python scripts/rotate_encryption_key.py

# .env 의 ENCRYPTION_KEY 새 값으로 교체 → api 재시작
sed -i "s/^ENCRYPTION_KEY=.*/ENCRYPTION_KEY=${NEW_KEY}/" .env
docker compose restart api
```

### 5-C. testnet → mainnet 키 전환 (PR #17 — 권장 워크플로우)
- [ ] 모든 활성 strategy 를 「⏸ 정지」 또는 「🛑 긴급 종료」 (전제 조건)
- [ ] 「💼 계정」 → 「🔑 키 변경」 클릭
- [ ] 3단계 prompt:
   - 새 mainnet api_key
   - 새 mainnet api_secret
   - 환경: `mainnet` 입력
- [ ] 백엔드가 자동:
   - 활성 strategy 0건 확인
   - Binance get_account 인증 검증
   - Fernet 재암호화 + DB 저장
   - 텔레그램 「🔑 [API 키 변경]」 audit 발송
- [ ] 잔고 카드 새로고침 → mainnet 잔액 표시되면 성공

### 5-D. 첫 거래 (가장 작은 자본)
- [ ] 새 전략: 자본 $20 / 1단계 / TP1 +5% / SL -10%
- [ ] `MAX_STRATEGY_CAPITAL_PCT_OF_BALANCE=5.0` 활성 시 — 자본 ≤ 잔액의 5% 자동 검증
- [ ] 진입 → TP 또는 수동 정지 → 거래소 ↔ DB 일치 검증
- [ ] 텔레그램 진입/체결 알림 도착 확인

### 5-E. 본격 운영
- [ ] `MAINNET-CHECKLIST.md` 의 모든 항목 ✅
- [ ] 일일 손실 한도 (`exchange_accounts.daily_loss_limit_usdt`) 설정
- [ ] Kill switch 수동 테스트 (admin 엔드포인트로 enable → 신규 진입 차단 확인 → disable)

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
