# 다음 세션 인계서 (2026-04-29 PM)

> 이 문서는 2026-04-29 오후까지의 작업 상태를 정리하고, 다음 Cowork (Claude) 세션에서 이어받을 수 있도록 작성되었습니다.
> 사용자가 "이어서 진행해주세요" 라고 하시면 이 파일의 우선순위 섹션부터 진입하시면 됩니다.

---

## 1. 사용자 의도 (다음 단계)

**메인넷 진입 직전. testnet 에서 실전 테스트를 충분히 한 후, 기본 시스템을 한 번 더 보완하고 메인넷으로 이동.**

구체적으로:
- 단계별 주문(stages 1~5) 정상 작동 검증
- 익절(TP1~5) + 손절(SL) 자동 발동 검증
- 시스템 안정성 추가 보완 (mainnet 자금 운용 안전)
- 메인넷 전환

---

## 2. 오늘 (2026-04-29) 완료된 작업

### 2.1 발견 + 수정한 critical 버그 8개

| # | 버그 | 패치 위치 |
|---|---|---|
| 3 | listenKey keepalive 미작동 | `backend/app/workers/keepalive_worker.py` |
| 8 | emergency_close 빈 포지션 -2022 | `backend/app/services/execution_service.py` |
| 9 | symbol_sync 705 vs DB 2 미스매치 | `backend/app/services/symbol_sync_service.py` |
| 10 | reconcile DB-only 잔재 자동 정리 안 함 | `backend/app/workers/reconcile_worker.py` |
| 11 | TP/SL precision -1111 | `backend/app/services/tp_sl_orchestrator.py` |
| 12 | 전략 시작 실패 시 orphan WAITING | `backend/app/api/v1/strategies.py` |

### 2.2 인프라 + UX 개선

- JWT 401 자동 로그아웃 완화 (1회 → 3회 임계)
- GET /orders 통합 엔드포인트 추가 (거래 실적 모달용)
- 메트릭 카드 클릭 → 섹션 이동 + 하이라이트
- 거래 실적 상세 모달 (기간 필터 + 일별 합계 + 거래 내역)
- 일별 row 클릭 → 그 날짜 거래만 필터링
- 실현 PnL 자동 계산 (LONG/SHORT 방향 적용)
- 심볼 datalist 200 → 1000 (인기 코인 자동완성 누락 해결)
- 한국어 에러 힌트 (-4016 PERCENT_PRICE, -1111 Precision, -4131 MIN_NOTIONAL)
- **NEW**: 전략 시작 즉시 Telegram 알림 (체결 무관, "전략 시작" 메시지)

### 2.3 데이터 + 환경

- NEON DB 705개 심볼 동기화 (TRADING 586개)
- Account #2 NEON 비활성화 (invalid API key 알림 차단)
- 활성 전략 0건 (깨끗한 상태)
- 거래소 testnet 포지션 0
- Git 최신 commit: `5867abe` (모든 변경 GitHub 반영)

---

## 3. 알려진 미완 사항 + TODO

### 3.1 새 발견 사항 (사용자 보고 2026-04-29 1:45 PM)

**전략 #35 SKYAIUSDT 숏 @ 0.23, 217 units**
- 1단계 LIMIT 주문 거래소 발송됨 (status: STAGE1_OPEN_PENDING)
- 시작가 0.23 이 현재 시세 대비 멀어 미체결로 대기 중일 수 있음
- **방금 수정한 "전략 시작" 알림** — 이번 push 후 컨테이너 재시작 시부터 적용됨
- 다음 세션 시작 시: SKYAIUSDT 상태 먼저 확인 (아직 미체결이면 정리 또는 시작가 -1% 로 재시작)

### 3.2 Mainnet 전 권장 작업

| # | 작업 | 예상 시간 | 우선순위 |
|---|---|---|---|
| A | **NEON 비밀번호 회전** (채팅 노출됨) | 5분 | 🔴 필수 |
| B | testnet stages 2~5 라이브 검증 | 1~2시간 | 🟠 권장 |
| C | TP1~TP5 자동 익절 + SL 자동 손절 풀 사이클 검증 | 1~2시간 | 🟠 권장 |
| D | 실현 PnL 정확 계산 (Binance Income API) | 1시간 | 🟡 선택 |
| E | VPS 마이그레이션 (24/7 가동) | 의사결정 + 2~3시간 | 🟠 권장 |
| F | 외부 모바일 접속 (ngrok 영구 도메인) | 30분 | 🟡 선택 |

### 3.3 작은 개선 후보

- DB-only 잔재가 REENTRY_READY 상태에도 발생 (Bug #10 fix는 *_OPEN 만 처리). REENTRY_READY 도 자동 정리 필요할 수 있음
- 전략 시작 시 시작가가 거래소 PERCENT_PRICE 필터 위반하면 사전 거절하는 로직 (Bug #12 후속) — 현재는 거래소가 거절한 후 strategy STOPPED 처리됨, 사전 검증이 더 친절
- _quick_ 템플릿 자동 정리 (운영 후 일정 시간 지나면 cleanup_quick 자동 호출)

---

## 4. 시스템 현재 상태 (Snapshot)

### 데이터 (NEON)
- strategy_instances: 23 (모두 종료, 활성 0)
- 단, **#35 SKYAIUSDT** 가 STAGE1_OPEN_PENDING 으로 살아있을 수 있음 (확인 필요)
- exchange_accounts: 2 (id=1 testnet active, id=2 비활성)
- symbols: 705 (TRADING=586)
- alembic_version: `0008_risk_events_sid_nullable`

### Git
- branch: `main`
- latest commit: `5867abe`
- `git pull` 시 `Already up to date` 가 정상

### Docker
- 8 containers Up (NEON 사용 중)
- DATABASE_URL 은 backend/.env 에서 NEON 가리킴
- 로컬 db 컨테이너는 미사용 (TEST_DATABASE_URL 만)

---

## 5. 다음 세션 시작 시 체크리스트

### Step 1 — 환경 확인
```powershell
cd C:\Users\user\바이낸스\binance-auto-trader
git pull origin main
cd backend
docker compose ps
docker compose exec api python -c "from app.core.database import SessionLocal; from app.models.strategy_instance import StrategyInstance; db = SessionLocal(); rows = db.query(StrategyInstance).filter(~StrategyInstance.status.in_(['STOPPED','COMPLETED','CLOSED'])).all(); [print(f'#{r.id} {r.symbol} {r.status}') for r in rows]; print('Total active:', len(rows)); db.close()"
```

→ 활성 전략 확인. #35 SKYAIUSDT 가 남아있으면 다음 단계로.

### Step 2 — #35 SKYAIUSDT 처리
거래소에서 limit 미체결 상태면:
- 시세가 0.23 까지 도달하길 기다리거나
- 정리 후 시작가 -1% 로 재시작

```powershell
docker compose exec api python /app/cleanup_testnet_strategies.py
```

### Step 3 — 우선순위 작업 진입
사용자에게 "다음 우선순위 무엇으로 진행할까요?" 확인:
- A. NEON 비밀번호 회전 (5분)
- B. stages 2~5 + TP/SL 라이브 검증 (1~2시간)
- C. VPS 마이그레이션 (의사결정 + 실행)
- D. 외부 모바일 접속 셋업

---

## 6. testnet 실전 테스트 계획 (Stages 2~5 + TP/SL)

### 6.1 빠른 트리거 템플릿 만들기

자연스러운 가격 변동으로 stages 2~5 트리거하려면 BTC 10%+ 변동 필요 (며칠 걸림). 빠른 검증용 tight trigger:

| 단계 | 자본 | 트리거 (이전 단계 대비) |
|---|---|---|
| 1 | 50 USDT | 시작가 (즉시 또는 -1%) |
| 2 | 100 USDT | +0.5% |
| 3 | 150 USDT | +1.0% |
| 4 | 200 USDT | +1.5% |
| 5 | 250 USDT | +2.0% |

총 자본 750 USDT. BTC 일일 변동성 1~3% 라 30분~수시간 안에 모든 단계 트리거 가능.

### 6.2 검증 시나리오

1. SHORT 진입 (시작가 -1% = 즉시 체결)
2. BTC 가격 ↑ 시 stage 2 자동 트리거 → 텔레그램 "2단계 진입"
3. 더 ↑ → stage 3
4. 더 ↑ → stage 4
5. 더 ↑ → stage 5
6. 그 후 가격 ↓ → TP1 발동 (+5%) → 텔레그램 "TP1 익절"
7. 또는 ↑↑ → SL 발동 → 텔레그램 "손절"

각 단계마다 검증:
- 거래소 주문 발송 + 체결
- DB status 전이
- 평단가 갱신
- 텔레그램 알림
- 대시보드 표시

### 6.3 TP/SL 풀 사이클 검증

별도 LONG 전략을 작은 자본으로 운영:
- TP1 +5% (qty 25%) → 부분 청산
- 가격 ↓ 후 다시 ↑ → TP2 +10% (qty 50%) → 부분 청산
- 더 ↑ → TP3 +20% (qty 100%) → 전량 청산 → COMPLETED
- 또는 가격 ↓↓ → SL -50% → 전량 손절 → REENTRY_READY

---

## 7. Mainnet 전환 체크리스트

다음 세션 또는 그 이후에 진행:

- [ ] testnet stages 2~5 검증 완료
- [ ] testnet TP1~5 + SL 자동 발동 검증 완료
- [ ] NEON 비밀번호 회전
- [ ] mainnet API 키 발급 (Binance 본 계정)
- [ ] mainnet API 키 시스템 등록 (exchange_accounts 신규 row)
- [ ] mainnet 계정 USDT 충전 (testnet 검증 통과 후 작은 금액부터)
- [ ] VPS 마이그레이션 (워커 24/7)
- [ ] 1차 mainnet 거래 — **5~10 USDT 작은 금액**
- [ ] 모니터링 + 검증 후 점진적 자본 확대

---

## 8. Cowork 에게 보내는 메모

**사용자 스타일:**
- 한국어, 존댓말 선호
- 짧고 결정적인 명령 한 줄씩 코드 블록
- PowerShell 페이스트 사고 자주 발생 → 명령은 명확히 분리
- 이미 만들어 둔 helper 스크립트 우선 활용

**시스템 컨텍스트:**
- Binance USDⓈ-M Futures 자동매매 (testnet → mainnet 진행 중)
- N단계 마틴게일 + TP1~TP5 + 트레일링 + 크라이시스 복구 모드
- FastAPI + SQLAlchemy + APScheduler + Redis + Docker compose
- DB: NEON 클라우드 (양 PC 공유) — `DATABASE_URL` 에 NEON URL 필요
- Telegram 알림 한국화 + 이모지

**오늘 누적 검증:**
- 8개 critical 버그 발견 + 8개 모두 수정 완료
- testnet 1단계 풀 사이클 검증 완료 (SHORT, LONG)
- listenKey keepalive 안정화
- stage_entered_alert + strategy_started_alert 정상 발송
- 모든 코드 GitHub 반영

**다음 세션 시작 시 환영 멘트:**
"이어받았습니다. SKYAIUSDT (#35) 상태부터 확인할까요? 또는 우선순위 작업(NEON 비밀번호 회전 / stages 2~5 검증 / VPS 마이그레이션 등) 중 어느 쪽으로 진행하시겠습니까?"

---

## 9. 파일 위치 빠른 참조

| 항목 | 경로 |
|------|------|
| 프로젝트 루트 | `C:\Users\user\바이낸스\binance-auto-trader\` (사무실/집 동일) |
| 환경 변수 | `backend\.env` (NEON URL) |
| Docker compose | `backend\docker-compose.yml` |
| 운영 매뉴얼 | `OPERATIONS.md` |
| 변경 이력 | `CHANGELOG.md` |
| 워크플로우 가이드 | `DEV-WORKFLOW.md` + `WORKFLOW.md` |
| 로직 검증 계획 | `backend/LOGIC-VALIDATION-TEST-PLAN.md` |
| 어제 인계서 | `HANDOFF-2026-04-28-OFFICE-TO-HOME.md` |
| 이 인계서 | `HANDOFF-2026-04-29-NEXT-SESSION.md` |

---

작성: 2026-04-29 오후
