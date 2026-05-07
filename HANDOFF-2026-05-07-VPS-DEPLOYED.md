# Handoff — 2026-05-07 VPS 배포 + 안전망 완성

이 문서는 5-07 세션의 **모든 작업 + 다음 세션이 알아야 할 운영 상태** 를 정리.

---

## 🎯 한 문장 요약

**testnet on VPS 24/7 운영 중. mainnet 전환 코드 측면 완성. 다음 단계는 사용자의 testnet 운영 검증.**

---

## 📦 인프라 현황 (2026-05-07 시점)

### VPS — DigitalOcean Singapore
- **IP**: `152.42.232.195`
- **Plan**: General Purpose 2 vCPU 8GB / 50GB SSD ($68/월)
- **OS**: Ubuntu 24.04 LTS x64
- **Hostname**: `binance-trader-prod`
- **SSH**: `ssh -i ~/.ssh/id_ed25519 trader@152.42.232.195`
- **대시보드**: http://152.42.232.195/ (자동 → /admin-ui 리다이렉트)
- **컨테이너 6개**: api / scheduler / user-stream / redis / prometheus / grafana
- **nginx reverse proxy**: 80 → api 8000

### Database — Neon Cloud (Singapore)
- **프로젝트**: `binance-auto-trader`
- **Region**: AWS Asia Pacific 1 (ap-southeast-1)
- **Database**: `neondb` / Role: `neondb_owner`
- **현재 데이터**: strategy 48건 보존 (testnet 검증 데이터)
- **DATABASE_URL**: pooler 형식 사용 중 (`-pooler.c-2.ap-southeast-1.aws.neon.tech`)

### 외부 자격증명 (.env 에 적용)
- **Binance Testnet API**: DB 의 ExchangeAccount #1 (is_testnet=True, websocket 연결 확인됨)
- **Telegram Bot**: token 8703...AAFI / chat_id 6445185531
- **Sentry DSN**: 미설정 (옵션)

---

## 🚀 5-07 세션 변경 요약 — 7 PR 머지

| PR | 내용 | 테스트 |
|---|---|---|
| #13 | 5-07 trigger 표기 fix | 412 |
| #14 | ENCRYPTION_KEY 회전 도구 + 백업/복구 + dry-run | +7 (419) |
| #15 | kill-switch + daily-loss 텔레그램 알림 wire-up (audit 발견) | +8 (427) |
| #16 | 자본 상한 / 동시성 / 심볼 화이트리스트 가드 (3-3) | +13 (440) |
| #17 | API 키 회전 + testnet ↔ mainnet 전환 endpoint | +8 (448) |
| #18 | VPS 배포 자동화 (validate/smoke) + 5-07 PR 반영 | 448 |
| #19 | KS 수동 해제 UI + leverage cap + liq 거리 + heartbeat | +17 (465) |

**main HEAD**: `59e8ca4` · pytest 465 passed

---

## ⚙️ 적용된 운영 환경변수 (VPS .env)

mainnet 시뮬 강도로 testnet 운영 중:

```bash
DAILY_LOSS_LIMIT_USDT=2000           # testnet 운영용 (mainnet 시 자본 10% 권장)
MAX_CONCURRENT_STRATEGIES_PER_ACCOUNT=3
MAX_STRATEGY_CAPITAL_PCT_OF_BALANCE=5.0
ALLOWED_SYMBOLS_CSV=BTCUSDT,ETHUSDT
MAX_LEVERAGE=5
MIN_LIQUIDATION_DISTANCE_PCT=5
HEARTBEAT_INTERVAL_HOURS=6
```

---

## ✅ 코드 측면 mainnet 준비 — 완료

### 안전망
- Kill-Switch: 자동 발동 + 텔레그램 알림 + UI 「🔓 해제」 버튼
- 일일 손실 한도: 80% 경고 → 100% kill-switch (PR #15)
- 자본 상한: 단일 strategy ≤ 잔액 5%
- 동시성: 계정당 ≤ 3개 strategy
- 심볼 화이트리스트: BTCUSDT/ETHUSDT 만
- 레버리지 상한: ≤ 5x
- 청산가 거리: ≥ 5% (leverage=20 거부)

### 알림 (모든 hook wired up)
- 단계 진입 / TP1~10 부분-전체 청산 / 손절 / 트레일링
- 증거금 추가 / 포지션 추가 / 키 변경 audit
- Kill-switch 발동 / 일일 손실 80% 경고
- System Heartbeat (6h 주기)

### 도구
- `scripts/rotate_encryption_key.py` (dry-run + 백업 + restore)
- `scripts/check_binance_key.py`
- `deploy/validate-readiness.sh` / `deploy/smoke-test.sh`
- 「💼 계정」 → 「🔑 키 변경」 (testnet ↔ mainnet 전환 UI)

---

## ⏳ 사용자 직접 작업 (코드 자동화 불가)

### 24시간 testnet 검증
[VPS-DEPLOY-CHECKLIST.md Phase 4](VPS-DEPLOY-CHECKLIST.md):
- [ ] 새 strategy 진입 → TP 단계 진행 → 청산까지 정상 cycle
- [ ] 의도적 손실 -$1,600 → 「⚠️ 일일 손실 한도 임계치 도달」 도착 (80%)
- [ ] 의도적 손실 -$2,000 → kill-switch + 「⚠️🔴 [Kill-Switch 발동]」 (100%)
- [ ] 6시간 후 「💚 [System Heartbeat]」 텔레그램 도착
- [ ] 24시간 운영 — 좀비/메모리 leak 없음
- [ ] 「🔓 KS 해제」 버튼 동작
- [ ] 「💉 포지션 추가」 + ISOLATED 자동 적용
- [ ] 「🗑」 archive → 통계 합계 변화 X

### Mainnet 전환 (검증 통과 후)
1. Binance mainnet API 발급 + IP whitelist `152.42.232.195`
2. ENCRYPTION_KEY 회전 (`scripts/rotate_encryption_key.py`)
3. `.env` 의 `DAILY_LOSS_LIMIT_USDT=100` (자본 10% 기준)
4. 「💼 계정」 → 「🔑 키 변경」 → mainnet 키 + 환경 "mainnet"
5. 작은 자본 ($20) 첫 거래 검증
6. 점진 자본 상향

### (옵션) HTTPS
도메인 구입 → DNS A record → certbot. [VPS-DEPLOY-CHECKLIST Phase 3](VPS-DEPLOY-CHECKLIST.md)

---

## 🔧 주요 명령어 (운영 중 자주 쓸 것)

```bash
# 로컬 PC 에서 VPS 접속
ssh -i ~/.ssh/id_ed25519 trader@152.42.232.195

# VPS 의 컨테이너 상태
cd ~/binance-auto-trader/backend
docker compose ps

# api 로그
docker compose logs api --tail=50

# 새 코드 배포 (이번 세션 처럼 main 에 push 후)
# 로컬에서:
cd "/c/Users/user/바이낸스/binance-auto-trader"
git archive --format=tar.gz HEAD -o /tmp/repo.tar.gz
scp -i ~/.ssh/id_ed25519 /tmp/repo.tar.gz trader@152.42.232.195:/tmp/

# VPS 에서:
cp ~/binance-auto-trader/backend/.env /tmp/env-backup
tar -xzf /tmp/repo.tar.gz -C ~/binance-auto-trader --overwrite
cp /tmp/env-backup ~/binance-auto-trader/backend/.env
find ~/binance-auto-trader -name '*.sh' -exec dos2unix {} \;
cd ~/binance-auto-trader/backend
docker compose -f docker-compose.yml -f ../docker-compose.production.yml up -d --build --force-recreate api scheduler user-stream

# Smoke test
bash ~/binance-auto-trader/deploy/smoke-test.sh

# Kill-switch 수동 해제 (UI 「🔓 해제」 버튼이 있으면 그것 사용 권장)
docker compose exec api python -c "
from app.core.database import SessionLocal
from app.services.account_kill_switch_service import AccountKillSwitchService
db = SessionLocal()
AccountKillSwitchService(db).clear(1)  # exchange_account_id=1
db.close()
"
```

---

## 🆘 트러블슈팅

| 증상 | 원인 / 조치 |
|---|---|
| 401 로그인 실패 | 잘못된 비밀번호 — 다시 입력 |
| Kill-switch 활성으로 거래 차단 | 배너의 「🔓 해제」 버튼 (PR #19) |
| 새 코드 적용 안 됨 | `docker compose ... up -d --force-recreate` 필요 (restart 만으론 .env 재로드 X) |
| Pydantic 빈 문자열 에러 | .env 에 `KEY=` (빈 값) 있으면 numeric 필드는 못 파싱 — 값 채우거나 `KEY=0` |
| Telegram 알림 안 옴 | `.env` 의 `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` 확인 + 봇과 1:1 채팅 시작했는지 |
| websocket 끊김 | listenkey_keepalive 워커 (30분 주기) — `docker compose logs scheduler` |

---

## 📂 핵심 파일 위치

### Repo (로컬 + VPS 동기화)
- `backend/app/services/strategy_service.py` — 진입 가드 (KS / leverage / liq / capital / symbol / concurrent)
- `backend/app/services/account_daily_loss_limiter.py` — 일일 손실 + 80% 경고
- `backend/app/services/account_kill_switch_service.py` — KS trigger/clear
- `backend/app/services/notification_service.py` — 모든 텔레그램 알림
- `backend/app/workers/heartbeat_worker.py` — 6h 주기 시스템 알림
- `backend/app/workers/daily_loss_aggregator.py` — 1분 주기 PnL 집계
- `backend/app/static/index.html` — 단일 HTML 대시보드 + KS UI
- `backend/scripts/rotate_encryption_key.py` — 키 회전
- `deploy/vps-bootstrap.sh` — 새 droplet OS 셋업
- `deploy/smoke-test.sh` — 배포 후 8 항목 검증

### 설정
- `backend/.env` (VPS) — 운영 자격증명 + 안전망 설정
- `backend/.env.production.template` — repo 의 마스터 (`generate-secrets.sh` 가 채움)
- `MAINNET-CHECKLIST.md` — mainnet 전환 전체 체크리스트

### 핸드오프 / 문서
- `VPS-DEPLOY-CHECKLIST.md` — VPS 배포 단계별
- `SYSTEM-SPEC.md` — 시스템 정의
- `AUDIT-FINDINGS.md` — audit 결과 누적
- `HANDOFF-2026-05-07-VPS-DEPLOYED.md` ← 이 문서

---

## 🧠 메모리 (Claude session 간 영속)

`C:\Users\user\.claude\projects\C--Users-user------binance-auto-trader\memory\`:
- `MEMORY.md` — 인덱스
- `project_overview.md` — 5-07 기준 PR #13~#19 반영 + 워크플로우
- `user_profile.md` — GitHub 웹 머지 패턴 + 한국어 + Windows
- `feedback_workflow.md` — 「추천으로 진행해줘」 자동 진행 패턴

다음 세션에서 메모리 자동 로드 → 즉시 컨텍스트 복원.

---

## 다음 세션 시작 시 권장

1. 현재 main HEAD 확인: `git log --oneline -3` (= `59e8ca4` 또는 그 이후)
2. VPS 상태 확인: `ssh trader@152.42.232.195 "cd ~/binance-auto-trader/backend && docker compose ps"`
3. 사용자가 testnet 운영 결과 보고 / 이슈 발견 보고
4. 발견된 이슈에 따라 fix 진행 또는 mainnet 전환 절차 안내

---

**작성: 2026-05-07. 작업 시간 약 12시간 (PR #13~#19, VPS 배포, testnet 운영 시작).**
