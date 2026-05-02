# DigitalOcean 배포 가이드 (Ubuntu 24.04 / 8GB RAM / 2 vCPU)

testnet 최종 검증 통과 후 mainnet 운영 환경 구축 → 첫 거래까지 단계별 가이드.

---

## 📋 자원 산정

| 컴포넌트 | RAM | CPU 사용 (idle / peak) |
|---|---|---|
| postgres (Neon Cloud 외부 사용 권장) | 0 / VPS 에서는 redis 만 | — |
| redis | 100MB | 낮음 |
| api (uvicorn × workers) | 400MB | 낮음 / 거래 진입 시 spike |
| scheduler | 200MB | 30초 reconcile cycle |
| user-stream | 200MB | websocket 상시 |
| prometheus | 500MB ~ 1GB | TSDB 누적 |
| grafana | 200MB | 낮음 |
| db-backup | 100MB | 일 1회 spike |
| nginx | 50MB | 낮음 |
| **합계** | **~2GB** | 2 vCPU 충분 |
| OS + buffer | 1GB | |
| **여유** | **5GB+** | mainnet 거래량 늘어도 충분 |

**디스크**: 기본 160GB SSD 충분 (DB 작음, prometheus TSDB 15일 retention default).

**Region**: **Singapore (`sgp1`)** 권장 — Binance Asia API 와 가깝고 한국에서 latency 50ms 이내.

**비용**: Basic AMD $48/월 또는 Regular SSD $40/월. mainnet 거래 자본 대비 무시할 수준.

---

## Phase 0 — DigitalOcean Droplet 생성 ⚠️

### 0-1. 계정 + 결제 등록
- [ ] DigitalOcean 가입 (https://www.digitalocean.com/)
- [ ] 결제 카드 등록
- [ ] (권장) 2FA 활성화

### 0-2. Droplet 생성
- [ ] Create → Droplet
- [ ] **Region**: Singapore (sgp1)
- [ ] **Image**: Ubuntu 24.04 LTS x64
- [ ] **Size**:
  - Basic AMD 2 vCPU / 8GB / 160GB SSD ($48/월) — 권장
  - 또는 Regular SSD 2 vCPU / 8GB / 160GB ($40/월) — 비용 절감
- [ ] **Authentication**: SSH Key (password 비추천)
  - 로컬에서 키 생성: `ssh-keygen -t ed25519 -C "binance-trader-vps"` (없으면)
  - 공개키 (`~/.ssh/id_ed25519.pub`) 내용을 DO 콘솔에 붙여넣기
- [ ] **Hostname**: `binance-trader-prod` (식별용)
- [ ] **Backups** 옵션 활성화 (월 +20% 비용, 주 1회 자동 snapshot — 권장)
- [ ] **Monitoring** 활성화 (무료, CPU/메모리/디스크 모니터링)

### 0-3. Cloud Firewall 생성
DigitalOcean Networking → Firewalls → Create.

| Rule | Type | Protocol | Port | Sources |
|---|---|---|---|---|
| SSH | Inbound | TCP | 22 | (본인 IP) — 또는 모두 (정 안되면) |
| HTTP | Inbound | TCP | 80 | All IPv4 / IPv6 |
| HTTPS | Inbound | TCP | 443 | All IPv4 / IPv6 |
| **나머지** | Inbound | — | **차단** | |
| All outbound | Outbound | All | All | All |

이 firewall 을 droplet 에 적용. **8000 / 5432 / 6379 / 3000 / 9090 절대 외부 노출 금지** (ufw 도 같이 적용).

### 0-4. SSH 접속 확인
```bash
ssh root@<droplet-ip>
# (방금 등록한 SSH 키로 자동 인증)
```

---

## Phase 1 — OS hardening + Docker 설치 ⚠️

### 1-1. 시스템 업데이트 + 기본 도구
```bash
# root 로 처음 들어간 직후
apt update && apt upgrade -y
apt install -y ufw fail2ban unattended-upgrades vim git curl wget htop tmux ncdu
```

### 1-2. non-root 사용자 생성
```bash
adduser trader   # 비번 설정
usermod -aG sudo trader
# SSH 키 복사
mkdir -p /home/trader/.ssh
cp /root/.ssh/authorized_keys /home/trader/.ssh/
chown -R trader:trader /home/trader/.ssh
chmod 700 /home/trader/.ssh
chmod 600 /home/trader/.ssh/authorized_keys
```

### 1-3. SSH 보안 강화
```bash
vim /etc/ssh/sshd_config
```
변경:
```
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
PermitEmptyPasswords no
# (선택) Port 22 → 22822 같은 다른 번호 — 단 firewall 도 같이 변경
```
재시작: `systemctl restart ssh`

**다음 SSH 접속부터는 trader 계정**으로:
```bash
ssh trader@<droplet-ip>
```

### 1-4. ufw 방화벽
```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp     # SSH (또는 변경한 포트)
sudo ufw allow 80/tcp     # HTTP
sudo ufw allow 443/tcp    # HTTPS
sudo ufw enable
sudo ufw status verbose
```

### 1-5. fail2ban (SSH brute-force 방어)
```bash
sudo cp /etc/fail2ban/jail.conf /etc/fail2ban/jail.local
sudo vim /etc/fail2ban/jail.local
```
`[sshd]` 블록:
```
[sshd]
enabled = true
maxretry = 3
findtime = 10m
bantime = 1h
```
재시작:
```bash
sudo systemctl enable --now fail2ban
sudo fail2ban-client status sshd
```

### 1-6. unattended-upgrades (자동 보안 패치)
```bash
sudo dpkg-reconfigure -plow unattended-upgrades   # → Yes
```
`/etc/apt/apt.conf.d/50unattended-upgrades` 의 `Unattended-Upgrade::Allowed-Origins` 에서 security 만 활성화 (default 가 안전).

### 1-7. Swap 추가 (8GB RAM → 4GB swap)
```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h
```

### 1-8. NTP 동기화 (거래소 시각 정확성 critical)
```bash
sudo timedatectl set-timezone UTC   # 또는 Asia/Seoul
sudo timedatectl set-ntp true
timedatectl status   # NTP synchronized: yes 확인
```

### 1-9. Docker Engine + Compose 설치
```bash
# Docker 공식 repo
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### 1-10. trader 사용자를 docker 그룹에
```bash
sudo usermod -aG docker trader
# 로그아웃 후 다시 로그인 (그룹 적용)
exit
ssh trader@<droplet-ip>
docker ps   # 권한 에러 없이 실행되면 OK
```

### 1-11. Docker daemon log rotation
```bash
sudo vim /etc/docker/daemon.json
```
```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",
    "max-file": "5"
  }
}
```
```bash
sudo systemctl restart docker
```

---

## Phase 2 — 앱 배포 ⚠️

### 2-1. 코드 clone
```bash
cd ~
git clone https://github.com/herosys1-crypto/binance-auto-trader.git
cd binance-auto-trader/backend
```

### 2-2. Production `.env` 작성
**절대 testnet 의 .env 그대로 가져오지 말 것.** 모든 자격증명 새로.

```bash
cp .env.example .env
vim .env
```

다음 값으로 (각각 새로 생성):

```bash
APP_NAME=Binance Futures Auto Trading Platform
APP_ENV=production              # 중요: production 으로

# JWT — 새 키 (`python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`)
SECRET_KEY=<NEW_VALUE>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=10080

# Postgres — Neon Cloud 사용 (외부 관리형, 자동 백업)
POSTGRES_PASSWORD=<NEON_NEW_PASSWORD>    # docker-compose.yml 의 db service 가 사용 안 함 (Neon 쓰니까)
DATABASE_URL=postgresql+psycopg2://neondb_owner:<NEW_NEON_PASSWORD>@ep-sparkling-forest-xxx.aws.neon.tech/neondb?sslmode=require

TEST_DATABASE_URL=postgresql+psycopg2://postgres:postgres@db:5432/binance_auto_trader_test
REDIS_URL=redis://redis:6379/0

# Binance — mainnet 만!
BINANCE_FUTURES_BASE_URL=https://fapi.binance.com
BINANCE_FUTURES_TESTNET_BASE_URL=https://testnet.binancefuture.com   # 코드 호환성 위해 유지

# 새 ENCRYPTION_KEY (`python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`)
ENCRYPTION_KEY=<NEW_FERNET_KEY>

ENABLE_METRICS=true

# Telegram — 새 token
TELEGRAM_BOT_TOKEN=<NEW_BOTFATHER_TOKEN>
TELEGRAM_CHAT_ID=<YOUR_CHAT_ID>

# Sentry (production 에선 필수 권장)
SENTRY_DSN=https://xxx@xxx.ingest.sentry.io/xxx
SENTRY_TRACES_SAMPLE_RATE=0.1
SENTRY_PROFILES_SAMPLE_RATE=0.0
```

```bash
chmod 600 .env   # 권한 제한
```

### 2-3. docker-compose 조정 (Neon DB 사용 시)
`docker-compose.yml` 의 `db` 서비스가 로컬 postgres 인데 Neon 사용 시 disabled 가능 (의존만 제거).

또는 그대로 둬도 됨 — `db` 컨테이너는 띄워지지만 DATABASE_URL 이 Neon 향하므로 사용 안 됨. 자원 좀 낭비. 권장: `db`, `db-backup` 서비스 disable.

```bash
vim docker-compose.yml
```
`db`, `db-backup` 서비스의 `restart: unless-stopped` 를 `restart: "no"` 로 또는 주석 처리. 하지만 docker compose 는 service 정의 자체를 무효화할 수 없으므로 깔끔한 건 별도 override 파일:

```bash
cat > docker-compose.override.yml << 'EOF'
services:
  db:
    profiles: ["disabled"]
  db-backup:
    profiles: ["disabled"]
EOF
```
이러면 `docker compose up -d` 시 db / db-backup 빠짐. 단 Neon Cloud 가 백업 책임짐 (Neon 자동 백업 정책 확인).

### 2-4. 첫 빌드 + 기동
```bash
docker compose up -d --build
docker compose ps          # api/scheduler/user-stream/redis/prometheus/grafana 5~6개 Running
docker compose logs api --tail=30
docker compose logs user-stream --tail=20
```

### 2-5. DB 마이그레이션 (Neon 에 alembic upgrade head)
```bash
docker compose exec api alembic upgrade head
```

### 2-6. 첫 사용자 생성
관리자 계정 생성 (auth API 또는 직접 DB):
```bash
# UI 회원가입 통해 (만약 막혀있으면 admin endpoint)
# 또는 직접 DB:
docker compose exec api python -c "
from app.core.database import SessionLocal
from app.models.user import User
from app.core.security import hash_password
db = SessionLocal()
u = User(email='admin@example.com', password_hash=hash_password('STRONG_PASSWORD'), is_active=True, is_admin=True)
db.add(u)
db.commit()
print(f'created user id={u.id}')
db.close()
"
```

---

## Phase 3 — Nginx + HTTPS 🟡

### 3-1. 도메인 준비
- [ ] 도메인 구매 (예: Cloudflare Registrar, Namecheap)
- [ ] DNS A record: `trader.yourdomain.com` → Droplet IP

### 3-2. Nginx 설치
```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

### 3-3. Nginx 설정
```bash
sudo vim /etc/nginx/sites-available/trader
```
```nginx
server {
    listen 80;
    server_name trader.yourdomain.com;

    # certbot 이 자동으로 HTTPS 로 리다이렉트 추가함
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket (필요하면)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # 타임아웃 (장기 요청)
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
    
    # 정적 파일 직접 제공 (선택, 성능)
    # location /static/ {
    #     alias /home/trader/binance-auto-trader/backend/app/static/;
    # }
}
```
```bash
sudo ln -s /etc/nginx/sites-available/trader /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default
sudo nginx -t                    # 설정 검증
sudo systemctl reload nginx
```

### 3-4. Let's Encrypt HTTPS
```bash
sudo certbot --nginx -d trader.yourdomain.com
# 이메일 + 약관 동의 + HTTPS 리다이렉트 yes
```
자동 갱신: `sudo systemctl status certbot.timer` 으로 확인.

### 3-5. 외부 접근 검증
- `https://trader.yourdomain.com` 접속 → 대시보드 정상 표시
- HTTP 접속 → HTTPS 자동 리다이렉트
- 8000 직접 접근 차단 확인: `curl http://<droplet-ip>:8000` → connection refused (firewall + nginx 만 listen)

### 3-6. Grafana 보호 (선택)
Grafana (3000) 도 외부 노출하려면 nginx subpath 또는 SSH tunnel:
```bash
# 로컬에서 SSH tunnel (간편하고 안전)
ssh -L 3000:localhost:3000 trader@<droplet-ip>
# 브라우저 → http://localhost:3000
```

---

## Phase 4 — testnet 환경에서 종단간 검증 ⚠️

VPS 에서 mainnet 가기 전, testnet 으로 한 번 검증:

### 4-1. testnet 거래소 계정 등록
- [ ] UI 의 「거래소 계정 추가」 → testnet API key/secret + `is_testnet=true`
- [ ] 잔고 표시 정상

### 4-2. 옵션 C #75 시나리오 종단간
[`MAINNET-CHECKLIST.md` 의 2-1 항목](MAINNET-CHECKLIST.md) 따라 진행. 합격 기준:
- [ ] 미리보기 6단계 = "+20% 도달 시"
- [ ] 1단계 진입 알림 정확히 1회 (dedup)
- [ ] 2~6단계 자동 트리거
- [ ] TP1 부분 청산 시 잔량 보존 (origin `0da0f55` 검증)
- [ ] 「수동 청산」 시 자동 STOPPED 전환 (오늘 fix `2677aff` 검증)
- [ ] max_loss/profit_pct 의미상 정확 (오늘 fix `69692d4` 검증)

### 4-3. 24시간 운영 검증
- [ ] testnet 거래 띄워놓고 24시간 운영
- [ ] listenKey 자동 갱신 정상
- [ ] reconcile_worker 30초 사이클 정상 (좀비 발생 없음)
- [ ] 텔레그램 알림 끊김 없음
- [ ] 메모리 leak 없음 (`docker stats`)

### 4-4. Backup 시뮬레이션
Neon 사용이라면 Neon UI 에서 backup → restore 한 번 테스트 (별도 DB 로 복원).

### 4-5. Kill switch 검증
- [ ] UI 의 kill switch 기능 발동 → 모든 활성 전략 STOPPING
- [ ] 새 거래 진입 차단 확인
- [ ] 텔레그램 발동 알림

---

## Phase 5 — Mainnet 전환 준비 ⚠️

testnet 모든 검증 통과 후에만 진행.

### 5-1. Binance Mainnet API 키 발급
- [ ] https://www.binance.com → API Management → Create API
- [ ] **권한 설정 (critical)**:
  - ✅ Enable Futures
  - ❌ Enable Spot & Margin Trading (선물 only 면 OFF)
  - ❌ Enable Withdrawals (절대 OFF)
  - ❌ Permits Universal Transfer (필요시만)
- [ ] **Restrict access to trusted IPs only** 활성화
  - Droplet 의 public IP 입력 (DigitalOcean Networking → Droplet 의 IP)
- [ ] **2FA 통과** 후 API key/secret 받기 (한 번만 보임 — 즉시 안전한 곳에 저장)

### 5-2. Mainnet 거래소 계정 등록
시스템 UI 또는 admin endpoint:
- [ ] 「거래소 계정 추가」
- [ ] API key/secret 입력
- [ ] **`is_testnet = false`** 선택
- [ ] 등록 후 잔고 표시 확인 (소량 USDT 이미 입금돼 있어야 함)
- [ ] 등록된 row 의 `api_key_enc` 가 새 ENCRYPTION_KEY 로 암호화됨 확인

### 5-3. 자본 / 리스크 한도 설정
- [ ] **`account_daily_risk_limit`**: 일일 −5% 또는 −10% (보수적)
- [ ] **`account_kill_switch`**: 발동 조건 + 알림 설정
- [ ] **단일 전략 자본 상한**: 계좌의 5~10% (예: 100 USDT 계좌 → 한 전략 최대 10 USDT)
- [ ] **동시 활성 전략 수**: 처음엔 1~2개

---

## Phase 6 — Phase 1: 첫 mainnet 거래 (10 USDT) ⚠️

**한 번에 큰 자본 넣지 말 것.** 모든 fix 가 mainnet 환경에서 정상 동작하는지 먼저 확인.

### 6-1. 사전 입금
- [ ] Binance Mainnet 선물 지갑에 **10~50 USDT** 입금

### 6-2. 첫 전략 (1단계만)
- [ ] 새 전략 모달 열기
- [ ] BTC/ETH (high-liquidity)
- [ ] 1단계 자본 10 USDT
- [ ] 2~10단계 비움
- [ ] TP1 5%, qty 100% (전체 청산)
- [ ] SL −10% (보수적)
- [ ] 레버리지 1x
- [ ] 「전략 생성」

### 6-3. 검증 항목
- [ ] 1단계 IMMEDIATE 진입 → Binance 거래소에 실제 포지션 생김
- [ ] 텔레그램 [전략 시작] + [1단계 진입] 알림 1회씩
- [ ] DB 의 `strategy_instances` 정상 (status=STAGE1_OPEN, qty 정확)
- [ ] TP1 또는 SL 발동 → 청산 → realized_pnl 정확 누적
- [ ] 청산 후 status 가 REENTRY_READY 또는 STOPPED 정상 전환

### 6-4. 회복 시나리오 검증
- [ ] backend 재시작 (`docker compose restart api scheduler user-stream`) 후
  - reconcile_worker 가 거래소 상태 정확히 동기화하는지
  - 좀비 STOPPING 발생 안 하는지

---

## Phase 7 — 점진적 자본 확대

| 단계 | 기간 | 자본 | 멀티 단계 | 동시 전략 | 심볼 |
|---|---|---|---|---|---|
| Phase 1 | 1주 | 10~50 USDT | 1단계만 | 1개 | BTC/ETH |
| Phase 2 | 2주 | 100~500 USDT | 2~3단계 | 1개 | BTC/ETH/BNB |
| Phase 3 | 2주 | 500~2000 USDT | 4~6단계 | 2개 | + 다른 high-liquidity |
| Phase 4 | 운영 | 기획 자본 | 옵션 C 풀 (최대 10단계) | 2~3개 | 화이트리스트 |

각 Phase 끝에:
- [ ] DB 통계 (realized_pnl, profit/loss count)
- [ ] 좀비 / 에러 / 알림 누락 0건 확인
- [ ] 다음 Phase 진입 결정

---

## Phase 8 — 운영 자동화 🟡

### 8-1. DigitalOcean Snapshot 자동
- [ ] Droplet → Backups → Enable (주 1회 자동, $추가 비용)

### 8-2. Offsite DB 백업
Neon 의 자동 백업 + 본인 별도 backup 권장:
```bash
# crontab 에 등록 (예: 매일 04:00 UTC)
crontab -e
0 4 * * * pg_dump "<DATABASE_URL>" | gzip > /home/trader/backups/$(date +\%Y\%m\%d).sql.gz
0 5 * * * find /home/trader/backups -mtime +30 -delete   # 30일 이상 자동 삭제
```
또는 AWS S3 / Backblaze B2 로 sync (rclone).

### 8-3. 재시작 자동화
- Droplet 재부팅 시 docker 자동 시작 (이미 enable):
  ```bash
  sudo systemctl enable docker
  ```
- docker compose 의 `restart: unless-stopped` 가 컨테이너 자동 재시작 처리

### 8-4. 외부 가용성 모니터링
- [ ] UptimeRobot (https://uptimerobot.com) 무료 — `https://trader.yourdomain.com/health` 5분 간격 체크
- [ ] 다운 시 텔레그램/이메일 알림

### 8-5. Grafana 알림 (선택)
- [ ] Prometheus 메트릭 기반 알림 룰 (이미 `alerts-binance-auto-trader.yml` 있음)
- [ ] Grafana → Notification Channels (텔레그램 webhook)

---

## 부록 A — 비상 절차

### 거래소 API 키 노출 의심 시
1. Binance UI 즉시 API key 비활성화
2. 새 key 발급 (위 5-1 절차)
3. 시스템 UI 에서 거래소 계정 row 의 키 갱신
4. backend 재시작

### Droplet 다운 시
1. DigitalOcean Console 접속 (web SSH 가능)
2. `docker compose ps` 로 컨테이너 상태 확인
3. 재시작 필요 시 `docker compose restart`
4. 그동안 거래소에 살아있는 포지션 → reconcile_worker 가 자동 동기화

### DB 손상 시
1. Neon UI 의 "Restore" 기능으로 시점 복구
2. 또는 본인 backup 에서 복원: `gunzip -c <backup>.sql.gz | psql "<DATABASE_URL>"`
3. backend 재시작

### kill switch 발동
1. UI 또는 admin endpoint 에서 trigger
2. 모든 활성 전략 STOPPING → 거래소에 reduce-only market order 발송
3. 결과 검증 (DB 와 거래소 둘 다)

---

## 부록 B — 비용 산정 (월)

| 항목 | 비용 |
|---|---|
| DigitalOcean Droplet 8GB AMD | $48 |
| DO Backup (선택) | +$10 |
| Neon Cloud DB (Pro tier) | $19~ (사용량) |
| 도메인 | ~$1 ($12/년) |
| Sentry (Developer free tier) | $0 |
| UptimeRobot free | $0 |
| **합계** | **~$78/월** |

거래 자본 10,000 USDT 운영 시 월 0.78% 운영 비용. 손익률에 미미.

---

## 부록 C — 트러블슈팅 빠른 참조

| 증상 | 점검 |
|---|---|
| 컨테이너 안 뜸 | `docker compose logs <서비스>` |
| 텔레그램 안 옴 | BOT_TOKEN 정확? CHAT_ID 정확? 봇이 채팅에 추가됨? |
| 거래소 API 호출 실패 | API key 권한? IP whitelist? 시각 sync? |
| DB 연결 실패 | Neon UI 에서 connection details 확인. password 정확? |
| user-stream 끊김 | listenKey 만료? `keepalive_worker` 살아있나? |
| 좀비 STOPPING 발생 | (오늘 fix 됨) reconcile_worker 30초 후 자동 정리 |
| 메모리 부족 | `docker stats` + `free -h`. swap 사용 중이면 설정 점검 |

---

## 다음 행동 (실행 순서)

이 가이드를 처음 보는 시점:

1. **이번 세션 정리** — git push 까지 완료
2. **다음 세션 / 시간 확보** 후 Phase 0 시작 (Droplet 생성)
3. **Phase 1 ~ 3** (인프라 + 앱 + HTTPS) — 약 2~4시간
4. **Phase 4** (testnet 24시간 검증) — 1일 운영
5. **Phase 5** (mainnet API 키 + 거래소 등록) — 1시간
6. **Phase 6** (10 USDT 첫 거래) — 1주
7. **Phase 7** (점진 확대) — 4~6주

총 6~8주에 걸쳐 안전하게 mainnet 안착.
