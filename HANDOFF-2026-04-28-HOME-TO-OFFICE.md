# 집 → 사무실 인계서 (2026-04-28)

> 이 문서는 집 컴퓨터에서 진행된 작업을 사무실 컴퓨터의 Cowork (Claude) 가 이어받을 수 있도록 작성되었습니다.
> 사무실 컴퓨터에서 Cowork 를 시작하실 때, 이 파일을 먼저 읽도록 요청하시면 컨텍스트가 즉시 복원됩니다.

---

## 1. 가장 큰 변화: 회사↔집 동기화 방식이 영구히 바뀌었습니다

**이전 (오늘 아침까지):**
- 회사↔집 전환 시 매번 DB 백업 → USB/클라우드 → 대상 컴퓨터에서 DROP/CREATE/import → alembic → 워커 재시작 (양방향 1.5시간 × 2 = 3시간/일)

**지금부터:**
- DB 가 Neon 클라우드로 옮겨졌습니다. 회사와 집이 같은 DB 를 봅니다.
- 컴퓨터 전환 시: `git pull` + `docker compose restart api scheduler user-stream` (5분)
- 백업/복원 사이클이 폐지되었습니다.

### Neon DB 정보

- 프로젝트: `binance-auto-trader` (AWS 아시아 태평양 1, 싱가포르)
- Free tier (0.5GB, 1억 row 까지 무료)
- 현재 사용량: 약 100MB 미만

### Connection String

```
postgresql+psycopg2://neondb_owner:npg_xqsjO9JGp5mF@ep-sparkling-forest-ao116t81.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
```

> 이 URL 은 `.env` 의 `DATABASE_URL` 에만 들어가야 하며, 절대 git 에 commit 되면 안 됩니다.
> `.gitignore` 에 `.env` 가 등재되어 있어 안전하게 보호되고 있습니다.
> 메인넷 전환 전에 Neon 대시보드에서 비밀번호 한 번 회전 권장.

---

## 2. 현재 시스템 상태 (Snapshot)

### 데이터 (Neon 에 적재됨)

| 테이블 | 행 수 |
|--------|------|
| strategy_instances | 11 (`#1`, `#11`~`#20`, 모두 STOPPED 상태) |
| orders | 11 |
| positions | 1731 (ACCOUNT_UPDATE 스냅샷 누적) |
| strategy_templates | 17 |
| strategy_stage_plans | 53 |
| risk_events | 25 |
| notifications | 64 |
| exchange_accounts | 2 (testnet 활성, mainnet 비활성) |
| symbols | 2 |
| users | 2 |
| alembic_version | 1 (`0008_risk_events_sid_nullable`) |

### Alembic 마이그레이션

- 현재 head: `0008_risk_events_sid_nullable`
- 0006: PnL 추적 컬럼
- 0007: auto_reentry 컬럼
- 0008: risk_events.strategy_instance_id NULLABLE 변경 (system 이벤트용)

### Git 상태

- Branch: `main`
- Latest commit: `home-pc-sync-from-office.bat` 추가 + heartbeat thread 등 (오늘 push 완료)
- `git pull` 시 `Already up to date` 가 정상 (이미 push 됨)

---

## 3. 이번 세션 (집 컴퓨터) 에서 한 일

### A. 코드 변경 (모두 git push 완료)

#### `backend/app/workers/run_user_stream.py`
- 30초 주기 heartbeat thread 추가 (`_heartbeat_loop`)
- `health:user_stream:connected` Redis 키를 60s TTL 로 갱신
- 컨슈머가 메시지 못 받아도 worker 자체 생존 신호 유지

#### `backend/app/workers/scheduler_runner.py`
- 동일한 heartbeat thread 추가 (`_scheduler_heartbeat_loop`)
- `health:scheduler:leader` Redis 키 60s TTL 갱신

#### `backend/app/workers/binance_user_stream_consumer.py`
- `_set_user_stream_health` 의 silent fail 제거 → `logger.warning` 로 로그 남김
- `start_user_stream` 직후에도 heartbeat set (이중 안전장치)

#### `backend/app/services/stream_service.py`
- ENTRY 주문이 FILLED 됐을 때:
  - `strategy.status` 를 단계별 OPEN 상태로 전환 (기존)
  - **NEW**: `strategy_stage_plans` 의 `is_triggered` / `triggered_at` 갱신
  - **NEW**: `NotificationService.send_stage_entered_alert` 호출 → 텔레그램 알림 발송
- `risk_events` 생성 시 `strategy_instance_id=0` → `None` 으로 변경 (FK violation 방지)

#### `backend/app/models/risk_event.py`
- `strategy_instance_id` 컬럼을 NULLABLE 로 변경 (system 이벤트가 특정 전략에 묶이지 않을 수 있음)

#### `backend/alembic/versions/0008_risk_events_strategy_nullable.py`
- 새 마이그레이션: `risk_events.strategy_instance_id` ALTER → nullable
- down_revision: `0007_auto_reentry`

### B. 인프라 변경 (이번 세션)

- **`backend/.env`** 의 `DATABASE_URL` 을 Neon 으로 변경 (이전 로컬 URL 은 주석으로 보존)
- 로컬 docker-compose 의 `db` 컨테이너는 여전히 실행 중이지만, **앱은 더 이상 사용하지 않음**
  - `TEST_DATABASE_URL` 만 로컬 db 를 사용 (단위 테스트 격리)
  - 향후 정리 시 `db` 컨테이너 제거 가능

### C. 검증 결과

- `docker compose exec api python -c "...StrategyInstance count..."` → `strategies: 11` ✓
- `/health` → 200 OK ✓
- API 로그: `Application startup complete`, DB 에러 없음 ✓
- DROP SCHEMA / 재import 로 Neon 데이터 정합성 확인 ✓

---

## 4. 사무실 컴퓨터 인계 절차 (Cowork 가 따라할 것)

> **참고:** 사무실 PC 의 프로젝트 경로는 `C:\Users\user\바이낸스\binance-auto-trader\` 입니다 (집 PC 와 폴더명 다름).

### Step 1 — 코드 동기화

```powershell
cd C:\Users\user\바이낸스\binance-auto-trader
git pull origin main
```

→ `Already up to date` 또는 `Updating ...` 둘 다 정상.

### Step 2 — `.env` 의 DATABASE_URL 만 교체

`backend\.env` 파일을 열고 다음과 같이 변경:

```bash
# 기존 줄을 주석 처리
# DATABASE_URL=postgresql+psycopg2://postgres:postgres@db:5432/binance_auto_trader

# Neon 클라우드 DB 추가
DATABASE_URL=postgresql+psycopg2://neondb_owner:npg_xqsjO9JGp5mF@ep-sparkling-forest-ao116t81.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
```

`TEST_DATABASE_URL` 은 그대로 두기 (로컬 단위테스트용).

### Step 3 — 컨테이너 재생성 (.env 반영)

`docker compose restart` 만으로는 .env 가 다시 안 읽힘. **반드시 force-recreate**:

```powershell
cd backend
docker compose up -d --force-recreate api scheduler user-stream
```

### Step 4 — 검증

```powershell
docker compose exec api python -c "from app.core.database import SessionLocal; from app.models.strategy_instance import StrategyInstance; db = SessionLocal(); print('strategies:', db.query(StrategyInstance).count()); db.close()"
```

→ `strategies: 11` 가 출력되면 인계 완료.

```powershell
docker compose exec api alembic current
```

→ `0008_risk_events_sid_nullable (head)` 가 출력되어야 함.

### 사무실 컴퓨터의 기존 로컬 DB 처리

- 로컬 `db` 컨테이너의 binance_auto_trader DB 는 더 이상 사용되지 않습니다.
- 데이터는 Neon 으로 모두 이전 완료되었으니, 로컬 DB 데이터는 안전하게 무시해도 됩니다.
- 정리하고 싶으시면 `docker volume rm backend_postgres_data` (재생성됨, 빈 상태로). 단, TEST_DATABASE_URL 이 로컬을 가리키므로 단위 테스트 시 자동 재생성될 것임.

---

## 5. 운영 치트시트

### Neon DB 직접 접근 (psql)

```powershell
$NEON = "postgresql://neondb_owner:npg_xqsjO9JGp5mF@ep-sparkling-forest-ao116t81.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
docker compose exec db psql $NEON -c "SELECT count(*) FROM strategy_instances;"
```

### 새 마이그레이션 추가 시

```powershell
docker compose exec api alembic revision -m "your_message" --autogenerate
docker compose exec api alembic upgrade head
```

→ Neon 에 자동 적용됨. 이전처럼 백업/복원 불필요.

### 자주 쓰는 검증

```powershell
docker compose ps                             # 컨테이너 상태
docker compose logs --tail=50 api             # API 로그
docker compose logs --tail=50 scheduler       # 스케줄러 로그
docker compose logs --tail=50 user-stream     # 유저 스트림 로그
curl http://localhost:8000/health             # 헬스체크
```

### 관리자 UI

- http://localhost:8000/admin-ui (대시보드)
- http://localhost:8000/docs (Swagger)

---

## 6. 최근 컨텍스트 (이전 세션 누적)

### 완료된 주요 단계

- **Phase B**: 동적 N단계 전략 (1~10단계 가변)
- **Phase C**: 한국어 대시보드 + 신호등 시스템 + 신규 전략 모달 + 통계 패널 + 시스템 상태 통합 패널
- **Phase D**: PnL 추적 + 크라이시스 복구 모드 (TP1/TRAIL_FULL/HARD_SL)
- 재진입 자동화 (auto_reentry_worker, scheduler 통합)
- Telegram 알림 한국화 + 이모지
- testnet 라이브 검증 (전략 #16/#17 으로 1단계 진입 + Telegram 알림 확인됨)

### testnet 검증 결과

- 1단계 LIMIT 주문 testnet 거래소 발송 → exchange_order_id 수신 → 체결 → 텔레그램 "[1단계 진입] BTCUSDT SHORT" 알림 (진입가 77,991.90, 수량 0.001) 정상 동작 확인됨
- heartbeat thread 추가 후 user-stream 자체 생존 신호 60s 미만 끊김 없음

### 진행 중 / 대기

- testnet 라이브 검증은 5단계 전체 (1~5단계 진입 시뮬레이션) 까지 더 진행할 여지 있음 — 현재는 1단계 진입까지만 실증
- 메인넷 전환 (옵션 ④) 은 운영 매뉴얼에 체크리스트 작성 완료, 자금 투입 전 한 번 더 검토 필요

### 다음에 할 만한 작업들 (사용자 선택)

1. **testnet 라이브 검증 계속** — 2단계, 3단계 진입까지 시뮬레이션
2. **새 전략 생성 + 모니터링** — Neon DB 에 양쪽 컴퓨터에서 동시 접근 가능
3. **VPS 마이그레이션** (메인넷 전환 시 필수) — 워커도 클라우드로 옮겨 컴퓨터 끄도 24/7 가동
4. **Sentry DSN 입력** (옵션 다 — 기존 pending task)
5. **db-backup 컨테이너 재구성** — 현재 빈 로컬 DB 만 백업하므로 Neon 을 백업하도록 변경 (또는 Neon 의 무료 PITR 24시간으로 충분하면 그대로 둠)

---

## 7. 트러블슈팅 (자주 나올 만한 문제)

### "OperationalError: SSL connection..." 같은 에러
- `.env` 의 DATABASE_URL 끝에 `?sslmode=require` 가 있는지 확인
- Neon 은 SSL 강제

### `alembic current` 가 빈 결과 반환
- DB 연결 실패. `.env` 의 DATABASE_URL 오타 확인
- 컨테이너 재기동: `docker compose down api scheduler user-stream && docker compose up -d api scheduler user-stream`

### "permission denied for schema public" (Neon 에서)
- `neondb_owner` 가 public schema 권한이 없을 때
- 해결: `psql $NEON -c "GRANT ALL ON SCHEMA public TO neondb_owner;"`

### user-stream heartbeat 키가 (nil)
- 이미 이번 세션에서 heartbeat thread 로 해결됨
- 만약 재발하면: `docker compose restart user-stream` 후 30초 안에 `health:user_stream:connected` 가 set 되어야 함

### 로컬 Docker `db` 컨테이너가 꺼져 있어도 OK
- 앱은 Neon 만 사용. 로컬 db 는 단위테스트 시에만 필요.

---

## 8. 중요 보안 사항

1. **`.env` 는 절대 git commit 금지** — `.gitignore` 에 등재되어 있음
2. **Neon 비밀번호는 채팅에 노출되었으므로 메인넷 자금 운용 전 반드시 회전**
   - Neon 대시보드 → Branches → Reset password
   - 새 password 로 양쪽 컴퓨터의 `.env` 업데이트
3. **API key/secret 은 `exchange_accounts` 테이블에 Fernet 암호화로 저장됨** — 이번 마이그레이션에서 그대로 보존됨

---

## 9. 파일 위치 빠른 참조

| 항목 | 집 PC 경로 | 사무실 PC 경로 |
|------|------|------|
| 프로젝트 루트 | `C:\Users\user\바이낸스\binance_auto_trader_project\` | `C:\Users\user\바이낸스\binance-auto-trader\` |
| 환경 변수 | `backend\.env` | `backend\.env` |
| Docker compose | `backend\docker-compose.yml` | `backend\docker-compose.yml` |
| 마지막 백업 (참고용) | `backend\db_backups\last\binance_auto_trader-20260427-121418.sql.gz` | (Neon 으로 이전되어 불필요) |
| 운영 매뉴얼 | `OPERATIONS.md` | `OPERATIONS.md` |
| 변경 이력 | `CHANGELOG.md` | `CHANGELOG.md` |
| 이 인계서 | `HANDOFF-2026-04-28-HOME-TO-OFFICE.md` | `HANDOFF-2026-04-28-HOME-TO-OFFICE.md` |

---

## 10. Cowork (Claude) 에게 보내는 메모

이 사용자는 회사↔집 양쪽에서 작업하는 1인 개발자이며, 한국어로 소통합니다.
존댓말을 선호합니다 (반말 X).

이전 세션의 큰 컨텍스트는:
- Binance USDⓈ-M Futures 자동매매 플랫폼 (testnet → mainnet 진행 중)
- N단계 마틴게일 전략 + TP1~TP5 + 트레일링 + 크라이시스 복구 모드
- FastAPI + SQLAlchemy + APScheduler + Redis + Docker compose 스택
- 단위테스트 + Telegram 알림 + Grafana/Prometheus 메트릭 통합 완료

긴 설명보다 짧고 결정적인 명령을 한 줄씩 주는 편을 선호합니다.
PowerShell 페이스트 사고가 자주 발생하므로, 복사해야 할 명령은 코드 블록 안에 정확히 한 줄씩 분리해서 제공할 것.

지금 시점의 우선순위:
1. testnet 안정화 검증 (이미 1단계 진입까지 확인됨, 2~5단계 추가 검증 필요)
2. 메인넷 전환 준비 (운영 매뉴얼 체크리스트 따라가기)
3. 사용자가 새로 요청하는 기능

이 인계서로 인계가 완료되면, 사용자가 "이어서 진행해 주세요" 라고 하실 때 곧바로 적절한 다음 단계를 제시하실 수 있습니다.

---

작성: 집 컴퓨터, 2026-04-28
