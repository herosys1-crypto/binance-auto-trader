# 🔒 HTTPS 설정 가이드 (사장님 다중 Sub-Account 운영 전 필수)

**작성**: 2026-06-03 (#10)
**목적**: 사장님 API key 평문 전송 차단 — 다중 계정 운영 + 미래 사용자 추가 대비

---

## 🎯 옵션 비교

| 옵션 | 도메인 | 시간 | 신뢰성 | 추천 |
|---|---|---|---|---|
| **A. self-signed** | 불필요 (IP) | 5분 | 브라우저 경고 (사장님 1회 클릭) | ✅ **즉시** |
| **B. Let's Encrypt** | 필요 ($1~$15/년) | 30분 | 정상 자물쇠 | ✅ **정통** |
| **C. Cloudflare proxy** | 필요 | 1시간 | + DDoS 방어 | 고급 |

---

## 🚀 옵션 A — self-signed (즉시 적용)

### 사장님 작업
```bash
ssh root@159.65.137.250
cd ~/binance-auto-trader
git pull origin main
bash deploy/setup-https-self-signed.sh
```

→ 5분 후 완료. `https://159.65.137.250` 접속 가능.

### 브라우저 경고 우회 (첫 접속 1회)
1. Chrome/Edge: `https://159.65.137.250` 접속
2. **「이 연결은 비공개 연결이 아닙니다」** 경고
3. **「고급」** 클릭 → **「159.65.137.250(안전하지 않음)으로 이동」** 클릭
4. → 이후 영구 신뢰 (사장님 브라우저)

### 브라우저 영구 신뢰 등록 (선택 — 깔끔)
**Chrome (Windows)**:
1. cert 파일 다운로드: `scp root@159.65.137.250:/etc/nginx/ssl/trader-self-signed.crt .`
2. 더블클릭 → 「인증서 설치」 → 「로컬 컴퓨터」 → 「신뢰할 수 있는 루트 인증 기관」
3. Chrome 재시작 → 자물쇠 정상 표시

---

## 🌐 옵션 B — Let's Encrypt (도메인 + 정통)

### 사전 작업 (사장님)

1. **도메인 구매** (예시):
   - Gabia (.com $10/년, .kr $15/년)
   - Namesilo ($1/년 ~)
   - GoDaddy / Cloudflare Registrar

2. **DNS A 레코드 추가** (도메인 등록사 패널):
   ```
   타입: A
   호스트: trader (또는 @)
   값: 159.65.137.250
   TTL: 300
   ```

3. **DNS 전파 대기** (10분 ~ 1시간):
   ```bash
   dig +short trader.yourdomain.com
   # → 159.65.137.250 표시되면 OK
   ```

### 사장님 VPS 작업
```bash
ssh root@159.65.137.250
cd ~/binance-auto-trader
git pull origin main
bash deploy/setup-https-letsencrypt.sh trader.yourdomain.com
```

→ 30분 후 완료. `https://trader.yourdomain.com` 정상 자물쇠.

### 자동 갱신
- Let's Encrypt cert = 90일 유효
- `certbot.timer` (systemd) 가 자동 갱신
- 검증: `certbot renew --dry-run`

---

## 🔄 self-signed → Let's Encrypt 교체

사장님이 옵션 A 로 운영 중 도메인 구매 시:
```bash
# 도메인 DNS 설정 + 전파 대기 후
bash deploy/setup-https-letsencrypt.sh trader.yourdomain.com
```

→ 자동 교체 + 기존 self-signed 백업.

---

## ⚠️ 보안 권장 사항

### 1. firewall 설정 (UFW)
```bash
ufw allow 22/tcp     # SSH
ufw allow 80/tcp     # HTTP (Let's Encrypt 갱신 + redirect)
ufw allow 443/tcp    # HTTPS
ufw enable
ufw status
```

### 2. HSTS 활성 (사장님 결정 후)
- 한번 적용 후 사장님 브라우저가 HTTP 영구 차단
- self-signed → Let's Encrypt 교체 전엔 미적용 권장
- 교체 후 nginx config 의 HSTS 주석 해제

### 3. Grafana / Prometheus 외부 노출 차단
- 현재 `127.0.0.1` 만 bind (외부 X) — 정상
- 외부 노출 필요 시 별도 server block + Basic Auth (template 주석 참고)

---

## 🎯 사장님 추천 진행 순서

### 1️⃣ 즉시 (오늘)
- **옵션 A** 실행 → 5분 완료
- 사장님 브라우저 1회 신뢰 등록
- 다중 Sub-Account 추가 시 API key 암호화 전송

### 2️⃣ 1주 이내
- 도메인 구매 (적당한 이름)
- DNS 설정
- **옵션 B** 실행 → self-signed 자동 교체

### 3️⃣ 1개월 이내
- HSTS 활성
- UFW firewall 적용
- Sentry DSN 등록 (#9)

---

## 📋 검증 체크리스트

설정 완료 후 확인:
- [ ] `https://...` 접속 시 자물쇠 표시 (또는 사장님 신뢰)
- [ ] `http://...` 접속 시 자동 `https://` 리다이렉트
- [ ] 「💼 계정」 모달의 API key 등록 시 브라우저 개발자 도구 Network 탭 — 요청 `Protocol: h2` 또는 `https` 확인
- [ ] `curl -v https://159.65.137.250/health` → SSL handshake 성공
- [ ] cert 만료일 확인: `openssl s_client -connect 159.65.137.250:443 < /dev/null | openssl x509 -noout -dates`

---

## 🆘 트러블슈팅

### 「nginx -t」 실패
- `/etc/nginx/sites-enabled/default` 가 80 port 점유 → 위 setup script 가 자동 제거

### 「port 80 already in use」
- 다른 서비스 (apache 등) 가 80 사용:
  ```bash
  ss -tulpn | grep ':80'
  systemctl stop apache2  # 또는 해당 서비스
  ```

### 「Let's Encrypt rate limit」
- 같은 도메인 5번 발급 시 1주 차단
- staging 으로 먼저 테스트: `certbot --staging ...`

### Docker 컨테이너가 80 port 사용 중
- 우리 시스템은 `127.0.0.1:8000` 만 bind (외부 X) — nginx 가 외부 80 → 내부 8000 reverse proxy
- docker compose port 정의 확인: `127.0.0.1:8000->8000/tcp`
