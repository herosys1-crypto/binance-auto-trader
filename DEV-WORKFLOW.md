# binance-auto-trader — 사무실/집 두 PC 개발 워크플로우 기획서

작성일: 2026-04-27  
배경: 오늘 사무실 PC 에서 집 PC DB 를 복원하는 과정에서 줄바꿈 인코딩, ENCRYPTION_KEY 형식, alembic 버전 불일치, listenKey FK 위반 등 다양한 문제가 발생. 이 기획서는 같은 사고가 반복되지 않도록 두 PC 사이의 개발/운영 규칙을 정한다.

---

## 1. 핵심 원칙

### 1.1 단일 소스 — GitHub 가 코드의 진실
- 코드 변경은 항상 commit + push 로 GitHub 에 반영
- 다른 PC 는 git pull 로만 받음 (수동 복사 금지)
- 직접 파일 수동 옮기기는 마지막 수단

### 1.2 한 번에 한 PC 만 작업
- 같은 시각에 양 쪽 PC 에서 동시 작업 안 함
- 한쪽이 작업 중일 땐 다른 쪽은 docker compose down 권장
- 진짜 동시 작업이 필요하면 브랜치 분리 필수 (예: `office-XXX`, `home-XXX`)

### 1.3 DB 는 PC 별 독립
- 양 PC 의 PostgreSQL 컨테이너는 독립 운영
- 거래소 API 키가 양쪽 DB 에 동시 등록되어 있으면 양쪽이 같은 mainnet 계정에 거래 신호를 보낼 수 있어 위험
- **mainnet 운영 시: 한 시점에 한 PC 에서만 docker compose up 한다**
- 두 PC 의 DB 는 정기적으로 한쪽에서 다른쪽으로 dump/restore 동기화 (오늘 한 절차)

### 1.4 비밀 키는 1Password 등 신뢰 저장소에 보관
- `SECRET_KEY`, `ENCRYPTION_KEY` 는 양쪽 PC 가 동일해야 함
- ENCRYPTION_KEY 잃으면 DB 의 거래소 API 키 영영 복호화 못 함 — Mainnet 운영자는 백업 필수
- 채팅, 이메일, 카톡으로 절대 전송 금지

---

## 2. 일일 워크플로우

### 2.1 작업 시작 (사무실/집 어느 쪽이든)

```
cd C:\Users\user\바이낸스\binance-auto-trader
git pull origin main
cd backend
docker compose up -d
docker compose exec api alembic upgrade head
docker compose ps
```

체크: 모든 컨테이너 Up + alembic_version 최신.

### 2.2 작업 종료

```
REM 진행 중 전략 정리 (필요 시) — testnet 이면 cleanup 스크립트
docker compose exec api python /app/cleanup_testnet_strategies.py

REM DB 백업 (다른 PC 로 옮길 거면)
backup-db-for-home.bat

REM 코드 변경사항 커밋/푸시
cd ..
git add <변경된파일들>
git commit -m "feat/fix/docs: 의미 있는 메시지"
git push origin main

REM (선택) 컨테이너 종료 — 거래 중이면 그대로 두기
cd backend
docker compose down
```

### 2.3 다른 PC 로 옮길 때

**한쪽에서 종료 → 다른 쪽에서 시작 절차:**

| 단계 | 사무실 PC | 집 PC |
|---|---|---|
| 1 | 코드 push, DB 백업 | 대기 |
| 2 | docker compose down | 대기 |
| 3 | 백업 파일을 클라우드/USB 로 복사 | (받음) |
| 4 | — | `home-pc-sync-from-office.bat <파일명>` |
| 5 | — | 작업 시작 |

**역방향(집 → 사무실)도 동일.** 단지 백업 파일 이름만 `home-to-office-*` 로 두면 헷갈리지 않음.

---

## 3. 비상 대응

### 3.1 두 PC 가 동시에 다른 코드를 commit 한 경우 (충돌)

```
git fetch origin
git status        ← 어느 파일이 양쪽 다 변경됐는지 확인
git pull --rebase origin main
REM 충돌 파일 수동 수정
git add <수정한파일>
git rebase --continue
git push origin main
```

### 3.2 ENCRYPTION_KEY 가 양쪽 PC 에서 다른 경우

증상: `ValueError: Fernet key must be 32 url-safe base64-encoded bytes` 또는 `cryptography.fernet.InvalidToken`

해결: 1Password 의 마스터 키로 양쪽 .env 통일 → 컨테이너 **재생성** (`docker compose up -d --force-recreate`).
참고: 단순 restart 로는 .env 가 다시 안 읽힘.

### 3.3 alembic 버전 불일치

증상: `Can't locate revision identified by '0008_xxxxx'`

해결: 양쪽 alembic_version 일치시키기.
```
docker compose exec -T db psql -U postgres -d binance_auto_trader -c "SELECT version_num FROM alembic_version;"
```
값이 다른 마이그레이션 파일을 가리키면 코드 sync 후:
```
docker compose exec -T db psql -U postgres -d binance_auto_trader -c "UPDATE alembic_version SET version_num = '<현재가지고있는마지막리비전>';"
docker compose exec api alembic upgrade head
```

### 3.4 user-stream listenKey 만료 / worker 크래시

**오늘 발견된 문제. 6개 패치 적용 후 자가 회복 가능해짐.**
- listenKey 는 60분 후 만료 → keepalive worker 가 30분마다 갱신 (작동 미검증, 추후 진단 필요)
- 만료 + worker 크래시 발생 시 reconcile worker 가 자가 회복 (Bug #5 패치)
- 그래도 이상하면: `docker compose restart user-stream`

### 3.5 거래소에 살아있는데 DB 는 STOPPED 인 고아 포지션

```
docker compose exec api python /app/force_close_orphaned_positions.py
```

---

## 4. 브랜치 전략 (선택)

기본은 `main` 한 브랜치로 충분. 다음 경우만 브랜치 분리:

- 사무실/집 동시 작업 필수 → `office-feature-X`, `home-feature-Y` 분리 후 PR 머지
- 큰 실험 → `experiment-X` 브랜치
- mainnet 핫픽스 → `hotfix-mainnet-X`

오늘처럼 일상 패치는 main 직접 commit OK.

---

## 5. 오늘 적용된 코드 변경 (2026-04-27)

7개 critical 버그 발견, 6개 수정:

| # | 버그 | 패치 위치 | 상태 |
|---|---|---|---|
| 1 | reduce_only hedge mode 비호환 | execution_service.py | ✅ 되돌림 |
| 2 | listenKeyExpired FK 위반 worker 크래시 | risk_event 모델 + stream_service + alembic 0008 | ✅ |
| 3 | listenKey keepalive 자동 갱신 안 됨 | keepalive_worker.py | 🟡 미수정 (별도 진단) |
| 4 | user-stream 죽으면 체결 이벤트 영구 소실 | (#5 로 보완) | ✅ |
| 5 | reconcile worker 가 PENDING 무시 | reconcile_worker.py | ✅ |
| 6 | SHORT 포지션에서 TP/SL 영원히 안 작동 | tp_sl_orchestrator.py | ✅ |
| 7 | latest_by_strategy LIMIT 누락 | position_repository.py | ✅ |

**Mainnet 진입 전에 #3 (listenKey keepalive) 별도 검증 필요.** 30분마다 도는 job 이 실제 listenKey 를 갱신하는지, 아니면 헛돌고 있는지 코드 리뷰 + 60분 무중단 테스트.

---

## 6. 향후 개선 (TODO)

### 6.1 단기 (1주 이내)
- [ ] Bug #3 listenKey keepalive 진단 + 수정
- [ ] 사무실 PC 의 Account #2 (testnet) API 키 무효 — 비활성화 또는 재발급
- [ ] 운영 대시보드 "User Stream 끊김" 표시 정상화 (Redis health 키 자동 갱신 메커니즘)
- [ ] 알림 정책 검토 — 거래 lifecycle (체결, 단계 진행, TP/SL) 도 Telegram 발송 추가 (현재는 에러만)

### 6.2 중기 (1개월)
- [ ] 자동 sync 스크립트 — 종료 시 자동 push, 시작 시 자동 pull
- [ ] DB 스키마 변경 시 자동 마이그레이션 (alembic upgrade head 를 docker entrypoint 에 통합)
- [ ] Mainnet 진입 전 통합 검증 시나리오 (testnet + 강제 listenKey 만료 시뮬레이션)

### 6.3 장기
- [ ] LONG 전략 템플릿 추가 (현재 모두 SHORT — 시장 약세 베팅에만 적합)
- [ ] Account #2 활용 — 분산 운영 또는 백업 거래소
- [ ] 백테스팅 모듈 — 과거 가격 데이터로 전략 시뮬레이션

---

## 7. 자주 쓰는 명령어 치트시트

```
REM 컨테이너 상태
docker compose ps

REM 로그 실시간
docker compose logs -f api scheduler user-stream

REM 운영 대시보드
start http://localhost:8000

REM Grafana
start http://localhost:3000

REM DB 직접 조회
docker compose exec -T db psql -U postgres -d binance_auto_trader -c "SELECT * FROM strategy_instances ORDER BY id DESC LIMIT 5;"

REM 활성 전략 종료 (testnet 한정)
docker compose exec api python /app/cleanup_testnet_strategies.py

REM 거래소 고아 포지션 청산 (testnet 한정)
docker compose exec api python /app/force_close_orphaned_positions.py

REM Redis 키 살펴보기
docker compose exec redis redis-cli KEYS "*"

REM 컨테이너 재생성 (.env 변경 시)
docker compose up -d --force-recreate api scheduler user-stream
```

---

## 8. 연락 / 도움

문서 업데이트는 이 파일을 직접 편집 후 commit. 운영 절차 변경은 `OPERATIONS.md` 도 같이 갱신.
