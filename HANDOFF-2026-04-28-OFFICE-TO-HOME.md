# 사무실 → 집 인계서 (2026-04-28 오후)

> 이 문서는 사무실 컴퓨터에서 진행된 작업을 집 컴퓨터의 Cowork (Claude) 가 이어받을 수 있도록 작성되었습니다.
> 집 컴퓨터에서 Cowork 를 시작하실 때, 이 파일을 먼저 읽도록 요청하시면 컨텍스트가 즉시 복원됩니다.

---

## 1. 오늘 사무실에서 한 일 (요약)

### A. Bug #3 마침내 해결 — `listenKey keepalive`
- 어제까지 1시간마다 `listenKeyExpired received; reconnect required` 알림이 양폭탄으로 왔던 문제
- `keepalive_worker.py` 가 `stream_sessions` 테이블의 ACTIVE row 만 보고 있었는데, user-stream 이 그 테이블에 row 를 안 만들어서 keepalive 가 한 번도 실행 안 되던 것
- **해결**: `keepalive_worker` 가 `exchange_accounts` 직접 순회하도록 변경. PUT /fapi/v1/listenKey 는 listenKey 값 자체가 아닌 API 키 단위로 동작하므로 stream_sessions 의존성 제거
- **검증**: 오후 2:23 마지막 listenKeyExpired 알림 이후 끊김. 패치 효과 확인

### B. Telegram `stage_entered_alert` 누락 수정
- 어제 인계서에 추가했다고 적혀있던 `send_stage_entered_alert` 호출이 사무실 PC 의 `stream_service.py` 에는 빠져있었음
- 1단계 체결 시 텔레그램 알림이 안 오는 이유였음
- **해결**: `stream_service.handle_order_trade_update` 의 ENTRY FILLED 분기에 `send_stage_entered_alert` 호출 추가 + `strategy_stage_plans.is_triggered/triggered_at` 갱신
- **검증**: 오후 4:08 BTCUSDT SHORT, 4:09 BTCUSDT LONG 모두 정상 알림 수신

### C. 대시보드 압축 + 모바일 반응형 (`backend/app/static/index.html`)
- 한 화면에 다 보이도록 레이아웃 재배치 (max-w-full, p-3)
- 시스템 상태 + 운영 통계 → 가로 2단
- 최근 활동 + 전략 인스턴스 → 가로 2단
- 빠른 작업 → 얇은 toolbar
- 전략 인스턴스 컬럼 12 → 9 (mode/start_price/max_loss·profit 은 상태 cell 의 tooltip 으로 통합)
- 모바일 반응형: 모바일에선 자동 1단 (md: 미만), 768px 이상은 2단
- iOS Safari auto-zoom 방지 (input font-size 16px 이상)
- viewport meta 추가 (`apple-mobile-web-app-capable` 등)
- 터치 친화 — 모바일 버튼 min-height 38px

### D. testnet symbol 동기화 시도
- `SymbolSyncService.sync()` 가 `Synced 705 symbols` 로 응답
- 그러나 DB 의 `symbols` 테이블엔 BTCUSDT, ETHUSDT 만 TRADING 상태로 들어감
- force_close_orphaned_positions 출력에서 PNUTUSDC, HIPPOUSDT, SOLVUSDT 등 많은 symbol 의 cancel-all 이 호출된 걸로 봐서 sync 로직에 정합성 버그 있음 (`Bug #9`)
- **현재로선 testnet 거래는 BTCUSDT/ETHUSDT 만 가능**

### E. testnet 라이브 검증 (1차 완료)
- 전략 #22 (BTCUSDT SHORT) + #23 (BTCUSDT LONG) 풀 사이클 검증
  - 1단계 진입 → FILLED → 텔레그램 알림 ✓
  - EXIT 체결 → REENTRY_READY 전이 ✓
- Bug #6 (SHORT TP/SL) 패치 효과 확인됨
- Bug #5 (PENDING 자가 회복) 패치 효과 확인됨

---

## 2. 새로 발견된 버그 (mainnet 전 수정 권장, 모두 minor)

### Bug #8 — `emergency_close` 가 포지션 0 인 전략에 -2022 에러
- 증상: 이미 종료된 (REENTRY_READY/STOPPED) 또는 미체결 상태의 전략에 🛑 클릭하면 `Binance API error: status=400, code=-2022, msg=ReduceOnly Order is rejected` 가 502 응답으로 노출됨
- 원인: `execution_service.emergency_close_position` 가 quantity 가 0 이어도 reduceOnly 시장가 주문을 넣음
- 수정 방향: 호출 시 `current_position_qty == 0` 이면 미체결 주문 cancel 만 수행하고 status STOPPED 로 마킹

### Bug #9 — `symbol_sync_service` 정합성
- 증상: sync() 가 705 를 리턴했는데 DB 에는 2 개만 영속됨
- 의심: 트랜잭션 일부 실패 후 commit 일부만 됐거나, exchange_info 응답 형식 차이로 대부분 row 가 status 비정상값 (혹은 `''`) 으로 들어가 그 후 쿼리에서 누락
- 진단 필요: `SELECT status, count(*) FROM symbols GROUP BY status` — 이미 사무실 PC 에선 `TRADING | 2` 만 나옴
- testnet 자체가 BTCUSDT/ETHUSDT 만 활성일 가능성도 있음 (별도 확인 필요)

### Bug #10 — `reconcile_worker` 가 DB-only 잔재 정리 안 함
- 증상: 거래소엔 포지션 없는데 DB 에선 STAGE1_OPEN 로 남는 경우, reconcile 이 RiskEvent 만 만들고 status 를 STOPPED 로 자동 전이하지 않음
- 결과: 사용자가 수동 UPDATE 로 정리해야 함
- 수정 방향: `if not matched:` 분기에서 `current_position_qty=0, status='STOPPED'` 로 자동 정리 (또는 안전을 위해 일정 시간 후만)

---

## 3. 현재 시스템 상태 (Snapshot)

### 데이터 (Neon)
- `strategy_instances`: 24 (모두 STOPPED/REENTRY_READY/COMPLETED 등 종료 상태)
- 활성 전략: 0
- `exchange_accounts`: 2 (id=1 testnet active, id=2 testnet inactive — invalid API 키)
- `symbols` TRADING: 2 (BTCUSDT, ETHUSDT)

### Alembic
- head: `0008_risk_events_sid_nullable`

### Git
- branch: `main`
- latest commit: `44a8c2d` (오늘 사무실에서 push 완료) — Bug #3 + stage_entered_alert + responsive dashboard
- `git pull` 시 `Already up to date`

### Docker (사무실 PC, 어제부터 28+ 시간 작동 중)
- 8 containers 모두 Up: api, scheduler, user-stream, db, redis, db-backup, prometheus, grafana
- DATABASE_URL 은 Neon 사용 중

### 거래소 (testnet)
- Account #1: 활성, 미체결 주문 0, 포지션 0
- Account #2: API 키 무효 (invalid key, deactive)

---

## 4. 집 컴퓨터에서 인계받는 절차

### Step 1 — 코드 동기화

```powershell
cd C:\Users\user\바이낸스\binance_auto_trader_project
git pull origin main
```

→ 사무실에서 push 한 commit 들이 모두 받아짐.

### Step 2 — 컨테이너 재시작 (코드 반영)

```powershell
cd backend
docker compose restart api scheduler user-stream
```

또는 .env 변경된 게 있으면:

```powershell
docker compose up -d --force-recreate api scheduler user-stream
```

### Step 3 — 검증

```powershell
docker compose ps
```

→ 8개 모두 Up.

```powershell
docker compose exec api alembic current
```

→ `0008_risk_events_sid_nullable (head)`.

```powershell
docker compose exec -T db psql -U postgres -d binance_auto_trader -c "SELECT count(*) FROM strategy_instances WHERE status NOT IN ('COMPLETED','STOPPED','CLOSED','REENTRY_READY');"
```

→ `0` (활성 전략 없음, 깨끗한 출발).

운영 대시보드: `http://localhost:8000` — 한 화면에 압축된 새 레이아웃 + 모바일 반응형 적용 확인.

---

## 5. 다음 작업 후보 (우선순위 순)

### A. 마이너 버그 3개 수정 (1~2시간)
1. **Bug #8** — `execution_service.emergency_close_position` 에 `if abs(quantity) == 0: cancel_only_path` 가드 추가
2. **Bug #9** — `symbol_sync_service` 진단 + 수정 (705 vs 2 미스매치)
3. **Bug #10** — `reconcile_worker` 가 DB-only 잔재 자동 정리

### B. NEON 비밀번호 회전 (5분, mainnet 전 필수)
- Neon 대시보드 → Branches → Reset password
- 양 PC 의 `backend/.env` 의 DATABASE_URL 비밀번호 부분 업데이트
- `docker compose up -d --force-recreate api scheduler user-stream`

### C. VPS 마이그레이션 검토 (의사결정 + 실행)
- 메인넷 자금 운용 시 24/7 가동 필수 → 워커도 클라우드로
- 후보: Vultr, Hetzner, AWS Lightsail, Oracle Cloud Free
- DB 는 이미 Neon 이라 워커만 옮기면 됨

### D. 모바일 외부 접속 (ngrok / Cloudflare tunnel)
- 외부에서도 운영 대시보드 접근 가능하게
- 보안: 로그인 + HTTPS 필수

### E. testnet stages 2~5 추가 검증 (선택)
- 현재 1단계 진입까지만 라이브 검증됨
- 자연스러운 가격 변동으로는 시간이 오래 걸림 (BTC 10%+ 변동 필요)
- Tight trigger 템플릿 만들어서 빠른 검증 가능

---

## 6. 사무실 PC 에서 정리해 둔 것 (집에서 무시 가능)

- 어제 만든 sync 스크립트들은 이제 NEON 시대엔 거의 안 쓰임:
  - `backend/backup-db-for-home.bat`
  - `backend/backup-db-for-office.bat`
  - `backend/restore-from-home-backup.bat`
  - `home-pc-sync-from-office.bat`
  - `office-pc-sync-from-home.bat`
- 그래도 git 히스토리에는 남아있어 비상시 참고 가능

---

## 7. Cowork (Claude) 에게 보내는 메모

이 사용자는 회사↔집 양쪽에서 작업하는 1인 개발자입니다. 한국어로 소통하며 존댓말 선호합니다.

**스타일:**
- 짧고 결정적인 명령을 한 줄씩 코드 블록으로 분리
- PowerShell 페이스트 사고가 자주 발생하므로 명령은 명확히 분리
- 이미 만들어 둔 스크립트가 있으면 우선 활용

**큰 컨텍스트:**
- Binance USDⓈ-M Futures 자동매매 (testnet → mainnet 진행 중)
- N단계 마틴게일 + TP1~TP5 + 트레일링 + 크라이시스 복구 모드
- FastAPI + SQLAlchemy + APScheduler + Redis + Docker compose
- DB 는 Neon 클라우드 (양 PC 공유)
- 단위테스트 + Telegram 알림 + Grafana/Prometheus 통합

**오늘까지 누적 검증:**
- 7개 critical 버그 발견 + 7개 모두 수정 완료
- testnet 1단계 풀 사이클 검증 완료 (SHORT, LONG)
- listenKey keepalive 안정화 (Bug #3)
- stage_entered_alert 정상 발송 (텔레그램)

**현재 우선순위:**
1. Bug #8/#9/#10 마이너 수정
2. NEON 비밀번호 회전
3. VPS 마이그레이션 (mainnet 전 필수)

이 인계서로 인계가 완료되면, 사용자가 "이어서 진행해주세요" 하실 때 곧바로 위 우선순위 중 하나로 진입할 수 있습니다.

---

작성: 사무실 컴퓨터, 2026-04-28 오후
