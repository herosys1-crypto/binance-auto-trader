# Binance Auto Trader — 운영 매뉴얼

작성일: 2026-04-26
운영자: 이규수 (herosys1@gmail.com)

이 문서는 일상 운용에 필요한 모든 절차를 담고 있습니다. 챗 도움 없이도 자력 운용 가능.

---

## 📌 목차

1. [매일 아침 1분 루틴](#1-매일-아침-1분-루틴)
2. [새 전략 시작](#2-새-전략-시작)
3. [대시보드 읽는 법](#3-대시보드-읽는-법)
4. [크라이시스 모드 대응](#4-크라이시스-모드-대응)
5. [흔한 에러와 해결](#5-흔한-에러와-해결)
6. [DB 백업 / 복구](#6-db-백업--복구)
7. [Mainnet 전환 체크리스트](#7-mainnet-전환-체크리스트)
8. [시스템 재기동](#8-시스템-재기동)
9. [핵심 URL / 자격증명](#9-핵심-url--자격증명)
10. [참고 — 코드 위치](#10-참고--코드-위치)

---

## 1. 매일 아침 1분 루틴

```powershell
cd C:\Users\user\바이낸스\binance_auto_trader_project\backend
docker compose up -d
docker compose exec db psql -U postgres -c "ALTER USER postgres WITH PASSWORD 'postgres';"
docker compose restart api
```

브라우저 → **http://localhost:8000/admin-ui** → 로그인 (`herosys1@gmail.com` / `Admin1234!`)

확인 항목:
- ⚙️ **시스템 상태**: 8개 컴포넌트 모두 🟢 인지
- 📊 **운영 통계**: 어제 대비 누적 PnL / 승률
- 📡 **최근 활동**: 밤사이 발생한 익절/손절/크라이시스 등
- 🎯 **전략 인스턴스**: 활성 전략의 PnL 상태 / 모드 배지

🔴 가 하나라도 보이거나 위험 알림 띠가 표시되면 [4. 크라이시스 모드 대응](#4-크라이시스-모드-대응) 참조.

---

## 2. 새 전략 시작

### 2-1. 빠른 시작 (대시보드)

1. 메인 화면 → **[➕ 새 전략 시작]** 클릭
2. **거래소 계정 선택**: testnet 또는 mainnet
3. **심볼**: 예 `BTCUSDT` (시세 패널에 현재가 자동 표시)
4. **방향**: 📉 숏 (2x 자동) / 📈 롱 (1x 자동)
5. **전략 구성**: 3가지 모드 중 선택
   - **📝 직접 입력**: 1~10단계 capital + trigger % 직접
   - **📋 템플릿 선택**: 미리 만든 템플릿 사용
   - **📂 이전 전략 불러오기**: 기존 전략 설정 그대로
6. **단계별 capital**: 1단계 필수, 나머지 사용할 단계만 입력
7. **트리거 %**: 기본값 (2/3/4단계=10, 5~9단계=20) 사용 또는 ▲▼ 수정
8. **익절/손절 설정** (펼쳐서): TP1~5 % + 청산 수량 % + 손절 % (기본값 사용 권장)
9. **시작가**: 시세 패널의 [현재가] / [+1%] / [-5%] 등 버튼 활용
10. **[📋 미리보기]** → 단계별 가격 + 수량 검증
11. **[🚀 전략 시작]** → 1단계 LIMIT 주문 즉시 발송

### 2-2. 권장 기본값 (중간 위험)

```
SHORT 2x:
  capitals: 100, 200, 300, 500, 700  (5단계)
  trigger %: 기본 (10, 10, 10, 20)
  TP: 10/15/20/25/30 %
  TP qty: 25/25/25/50/100 %
  SL: 50% (총 자본 대비)
  reentry: manual_ready (안전)

또는 자동 재진입 (공격적):
  reentry_policy: auto
  reentry_delay: 600 (10분)
  reentry_offset: 1.0 (현재가 +1%)
```

---

## 3. 대시보드 읽는 법

### 3-1. 상단 4개 메트릭 카드

| 카드 | 의미 |
|---|---|
| 시스템 상태 | API+DB 연결 (🟢/🔴) |
| 진행 중인 전략 | 활성 strategy 수 |
| 미실현 손익 합계 | 모든 활성 strategy 의 현재 PnL 합 |
| 전략 템플릿 | 사용 가능 템플릿 수 |

### 3-2. 시스템 상태 패널 (8개 컴포넌트)

| 신호 | 의미 |
|---|---|
| 🟢 ok | 정상 |
| 🟡 warn | 주의 (heartbeat 만료, Telegram 일부 실패 등) |
| 🔴 down | 장애 (즉시 점검) |

### 3-3. 운영 통계 패널

| 항목 | 의미 |
|---|---|
| 전체 전략 | DB 의 모든 strategy 수 |
| 완료(익절) | 정상 익절 종료 |
| 손절 | SL 또는 크라이시스 hard SL |
| 승률 | 완료 / (완료 + 손절) |
| 누적 실현손익 | 모든 strategy 의 realized_pnl 합 |
| 크라이시스 발동 | 누적 진입 횟수 (현재 활성) |

### 3-4. 전략 인스턴스 표 컬럼

| 컬럼 | 색상 의미 |
|---|---|
| 상태 | 🟢 진행 / 🟡 대기 / 🔴 위험 |
| 모드 | 정상 (회색) / 🚨 크라이시스 (노랑) / 🛡 크라이시스 보호 (빨강) |
| 진입요청가 | 🟡 운영자 입력 1단계 LIMIT 가격 |
| 평균진입가 | 🔵 실제 체결 평균 |
| 미실현 손익 | 🟢 양수 / 🔴 음수 |
| 최대손실/이익 | 🔴 누적 max_loss / 🟢 누적 max_profit |

### 3-5. 액션 버튼

- **✏️ 수정**: 기존 전략 종료 후 새 설정으로 재시작
- **⏸ 정지**: 미체결 주문만 취소 (포지션 유지)
- **🛑 긴급**: 시장가로 포지션 즉시 청산
- 정지 실패 시 → **DB 강제 정지** 옵션 자동 제안

---

## 4. 크라이시스 모드 대응

### 4-1. 자동 발동 조건
```
5+ 단계 진입 + 누적 최대 손실 ≥ 30%
```

### 4-2. 크라이시스 모드 단계

| 단계 | 표시 | 효과 |
|---|---|---|
| Stage 1 | 🚨 크라이시스 (노랑) | TP1 임계 +10% → +5% 로 낮춤. 손절은 정상 -50% 유지 |
| Stage 2 | 🛡 크라이시스 보호 (빨강) | TP1(+5%) 발동 후. 트레일링 -5% + 빠른 손절 -1% 활성 |

### 4-3. 운영자 대응

**Stage 1 시:**
- 시세 회복 기다리기 (자동으로 +5% 도달 시 25% 청산)
- 시세 더 빠지면 -50% 손절 자동 발동 (자연스럽게 종료)
- 즉시 청산 원하면 [🛑 긴급] 버튼

**Stage 2 시:**
- 트레일링이 자동 발동되니 가만 두면 됨
- -1% 도달 시 자동 손절
- 차익 봤으니 미련 두지 말 것

**Telegram 알림:**
- 🚨 크라이시스 모드 진입
- ⚡ 크라이시스 첫 TP +5%
- 🛡 트레일링 청산
- 🚨 빠른 손절 -1%

---

## 5. 흔한 에러와 해결

### 5-1. 로그인 실패: 500 Internal Server Error

원인: DB 인증 깨짐 (자주 발생).
```powershell
docker compose exec db psql -U postgres -c "ALTER USER postgres WITH PASSWORD 'postgres';"
```
→ 페이지 새로고침 후 재로그인.

### 5-2. Telegram 메시지 도착 안 함

```powershell
docker compose exec db psql -U postgres -d binance_auto_trader -c "SELECT id, send_status, SUBSTRING(body FROM '\[send_error\].*$') AS error FROM notifications ORDER BY id DESC LIMIT 3;" -P pager=off
```
- `chat not found` → `.env` 의 `TELEGRAM_CHAT_ID` 확인 (현재값: `6445185531`)
- `Unauthorized` → BotFather `/revoke` 후 새 토큰 발급
- `Telegram settings are missing` → `.env` 의 두 줄 비어있음

### 5-3. user-stream "❌ 끊김"

```powershell
docker compose logs user-stream --tail 30
```
- `MultipleResultsFound` → 거래소 계정 여러 개 active. `is_active=false` 로 일부 비활성화
- `Unauthorized` / `API-key format invalid` → 거래소 계정 키가 잘못됨. 비활성화 후 새 키로 재등록
- `[user-stream] is_testnet=True ... Websocket connected` → 정상 (Grafana 표시는 1분 뒤 갱신)

### 5-4. 전략이 진입 안 됨 (대기 중에서 멈춤)

원인: 거래소 계정 API 키 문제.
```powershell
docker compose exec db psql -U postgres -d binance_auto_trader -c "SELECT id, market_type, is_testnet, is_active, length(api_key_enc) as key_len FROM exchange_accounts;"
```
- `key_len < 50` → 가짜 키. 비활성화: `UPDATE exchange_accounts SET is_active=false WHERE id=X;`

### 5-5. 템플릿 삭제 실패 (사용 중)

대시보드 [🗑] 버튼 → "비활성화됨" 메시지 → 다시 클릭 → "cascade 삭제" 다이얼로그 → [확인]

또는 [🧹 _quick_* 일괄 정리] → cascade 모드 → 일괄 삭제.

### 5-6. 컨테이너 재시작 후 로그인 또 500

```powershell
docker compose down
docker compose up -d
docker compose exec db psql -U postgres -c "ALTER USER postgres WITH PASSWORD 'postgres';"
docker compose restart api
```

---

## 6. DB 백업 / 복구

### 6-1. 자동 백업 위치

`C:\Users\user\바이낸스\binance_auto_trader_project\backend\db_backups\`
- `daily/` 일별 (7일 보관)
- `weekly/` 주별 (4주)
- `monthly/` 월별 (6개월)
- `last/binance_auto_trader-YYYYMMDD-HHMMSS.sql.gz` 가장 최근

### 6-2. 즉시 백업 1회

```powershell
docker compose exec db-backup /backup.sh
```

### 6-3. 백업에서 복구

```powershell
# 1) 최신 백업 파일명 확인
$latest = Get-ChildItem db_backups\last\*.sql.gz | Where-Object { $_.Length -gt 0 } | Sort-Object LastWriteTime -Descending | Select-Object -First 1

# 2) 백업을 db 컨테이너로 복사
docker compose cp $($latest.FullName) db:/tmp/backup.sql.gz

# 3) 압축 풀어서 import
docker compose exec db sh -c "gunzip -c /tmp/backup.sql.gz | psql -U postgres -d binance_auto_trader"

# 4) 복원 확인
docker compose exec db psql -U postgres -d binance_auto_trader -c "\dt"
```

---

## 7. Mainnet 전환 체크리스트

### 7-1. 사전 준비 (mainnet 전환 1주 전)

- [ ] testnet 에서 1주 무사고 운용 (정상 + 크라이시스 + 자동재진입 모두 검증)
- [ ] **SECRET_KEY** / **ENCRYPTION_KEY** 외부 백업 (1Password 등)
  ```powershell
  Get-Content C:\Users\user\바이낸스\binance_auto_trader_project\backend\.env | Select-String "SECRET_KEY|ENCRYPTION_KEY"
  ```
- [ ] DB 백업 1회 + 복구 검증

### 7-2. Binance Mainnet API 키 발급

1. binance.com 로그인 → API Management
2. 새 subaccount 만들기 (자금 격리)
3. API 키 발급:
   - ✅ **Enable Reading**
   - ✅ **Enable Futures**
   - ❌ **Enable Withdrawals** (절대 OFF)
   - ✅ **Restrict access to trusted IPs** (운영 서버 IP)
4. 메인 계정에서 운용 자금만 subaccount 로 이체

### 7-3. 시스템 등록

```powershell
# Mainnet exchange account 추가 (대시보드 또는 Swagger)
# POST /api/v1/exchange-accounts
{
  "exchange_name": "binance",
  "market_type": "usds_m_futures",
  "api_key": "<MAINNET_KEY>",
  "api_secret": "<MAINNET_SECRET>",
  "is_testnet": false,
  "hedge_mode_enabled": true
}
```

### 7-4. 점진적 자금 투입

| 주차 | 자본 | 검증 |
|---|---|---|
| 1주차 | 100 USDT | 단일 전략 / 손절 발동 시 흐름 |
| 2주차 | 500 USDT | 트레일링 / 크라이시스 흐름 |
| 3주차 | 2,000 USDT | 일일 손실 한도 시뮬레이션 |
| 4주차+ | 정식 자금 | |

### 7-5. 안전장치 활성화

- [ ] **일일 손실 한도** 설정 (`account_daily_risk_limits` 테이블 — 자본 5~10%)
- [ ] **Sentry DSN** `.env` 입력 (에러 추적)
- [ ] **Telegram** 정상 동작 (이미 검증됨)
- [ ] **Kill-Switch** 수동 발동 한 번 시연 (`POST /admin/kill-switch/{id}/enable`)

---

## 8. 시스템 재기동

### 8-1. 정상 재기동
```powershell
cd C:\Users\user\바이낸스\binance_auto_trader_project\backend
docker compose restart api scheduler user-stream
```

### 8-2. 완전 재생성 (env 변경 시)
```powershell
docker compose down
docker compose up -d
docker compose exec db psql -U postgres -c "ALTER USER postgres WITH PASSWORD 'postgres';"
docker compose restart api
```

### 8-3. 시스템 완전 정리 (개발 시만, 데이터 손실 ⚠️)
```powershell
docker compose down -v   # 볼륨 같이 삭제
docker compose up -d
docker compose exec api alembic upgrade head
docker compose exec api python scripts/create_admin.py --email herosys1@gmail.com --password Admin1234! --full-name Admin
```

---

## 9. 핵심 URL / 자격증명

### 9-1. URL

| 서비스 | URL |
|---|---|
| 운영 대시보드 | http://localhost:8000/admin-ui |
| API Swagger | http://localhost:8000/docs |
| Grafana | http://localhost:3000 |
| Prometheus | http://localhost:9090 |

### 9-2. 자격증명

| 서비스 | ID | PW |
|---|---|---|
| 운영 대시보드 | herosys1@gmail.com | Admin1234! |
| Grafana | admin | Admin1234! |
| DB (postgres) | postgres | postgres |
| DB 외부 접속 | — | 127.0.0.1:5433 만 (LAN 차단) |

### 9-3. Telegram

- 봇 username: `@herosys1_binance_bot`
- 봇 토큰: `.env` 의 `TELEGRAM_BOT_TOKEN`
- chat_id: `6445185531`

⚠️ **모든 비밀번호 / 토큰은 mainnet 전환 시 강한 값으로 교체 필수.**

---

## 10. 참고 — 코드 위치

```
backend/app/
  ├─ services/
  │   ├─ strategy_calculator.py     단계 트리거 룰 (2/3/4=10%, 5+=20%)
  │   ├─ risk_service.py            크라이시스 모드 + 트레일링 (Redis 피크)
  │   ├─ tp_sl_orchestrator.py      TP/SL 실행 + 크라이시스 액션
  │   ├─ notification_service.py    한국어 알림 10종
  │   └─ strategy_service.py        전략 인스턴스 생성
  ├─ api/v1/
  │   ├─ strategies.py              전략 CRUD + preview-inline + blueprint + timeline
  │   ├─ admin.py                   템플릿 CRUD + cleanup + stats + system-health + recent-activity
  │   ├─ exchange_accounts.py       거래소 계정 CRUD
  │   ├─ symbols.py                 심볼 조회
  │   ├─ market.py                  Binance public API 프록시
  │   ├─ orders.py                  주문 조회
  │   ├─ positions.py               포지션 조회
  │   └─ events.py                  이벤트 조회
  ├─ workers/
  │   ├─ scheduler_runner.py        scheduler 진입점
  │   ├─ run_user_stream.py         user stream 진입점
  │   ├─ binance_user_stream_consumer.py  WebSocket consumer
  │   ├─ auto_reentry_worker.py     ⭐ NEW 자동 재진입
  │   ├─ keepalive_worker.py        listenkey 갱신
  │   └─ reconcile_worker.py        포지션 동기화
  ├─ models/                        SQLAlchemy 모델
  ├─ static/index.html              운영자 대시보드 v3
  └─ alembic/versions/              0001~0007 마이그레이션

기획서:
  DASHBOARD_V2_PLAN.md             대시보드 v2 기획
  CRISIS_RECOVERY_MODE_PLAN.md     크라이시스 모드 기획
  OPERATIONS.md                    이 문서
```

---

## 부록 — 자주 쓰는 SQL

```sql
-- 진행 중 전략 + 모드 확인
SELECT id, symbol, side, status, current_stage, max_loss_pct, max_profit_pct,
       crisis_mode_triggered_at, crisis_first_tp_done_at
FROM strategy_instances
WHERE status NOT IN ('STOPPED','CLOSED','COMPLETED','CLOSED_BY_TP','CLOSED_BY_SL','STOPPING');

-- 최근 24h 손익 합
SELECT SUM(realized_pnl) FROM strategy_instances
WHERE updated_at > NOW() - INTERVAL '24 hours';

-- 가장 손실 큰 전략 5개
SELECT id, symbol, side, max_loss_pct, status FROM strategy_instances
WHERE max_loss_pct IS NOT NULL ORDER BY max_loss_pct ASC LIMIT 5;

-- 활성 거래소 계정 + hedge_mode
SELECT id, market_type, is_testnet, is_active, hedge_mode_enabled FROM exchange_accounts;

-- _quick_* 임시 템플릿 정리
DELETE FROM strategy_templates
WHERE name LIKE '\_quick\_%'
  AND id NOT IN (SELECT DISTINCT strategy_template_id FROM strategy_instances);
```

---

작성: Claude (오늘 세션)
업데이트 권장: 새 기능 추가 / 운영 중 발견된 트러블 추가 시
