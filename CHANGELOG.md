# CHANGELOG — Binance Auto Trader

세션 단위로 변경 이력을 기록합니다.

---

## [2026-04-30] — 마지막 단계 트리거 + 트레일링 -5% 기획 반영 (Option C)

### 🎯 운영자 의도 반영
- **마지막 단계 진입 로직 변경** — 사용자 기획: "마지막까지 금액이 있으면 정한 20% 상승에 진입".
  - SHORT 마지막 단계 default 가 `LIQUIDATION_BUFFER` → `PRICE_UP_PCT` 로 변경.
  - 기본 % 도 `5%` → `20%` 로 변경 (LONG 과 동일).
  - 사용자가 명시적으로 `last_stage_trigger_mode=LIQUIDATION_BUFFER` 지정 시에만 청산가 기반 동작 (호환성 유지).
- **트레일링 익절 -5% 변경** — 사용자 기획: "익절을 단계별로 진행하는 중에 -5% 하락하면 모두 청산익절".
  - 기존: 절대 임계 (피크 ≥ 20% AND 현재 ≤ 20%) → 신규: 피크 대비 -5% 회귀 시 발동.
  - 활성 조건: 피크 ≥ +5% (TP1 임계 도달) AND 현재 ≤ 피크 - 5%.
  - 활성 status 에 `TP1_DONE_PARTIAL` 추가 (이전엔 TP2 부터만 활성).

### 🔧 코드 변경
- `services/strategy_calculator.py` — `DEFAULT_LAST_TRIGGER_MODE_SHORT`, `DEFAULT_LAST_SHORT_TRIGGER_PCT` 변경.
- `services/risk_service.py` — `TRAILING_TP_RETRACE_TRIGGER` (절대) → `TRAILING_TP_RETRACE_AMOUNT` (피크 대비) 로 의미 변경. 임계 5% 로 하향.
- `static/index.html` — `_collectDirectInputs` 가 마지막 단계의 사용자 입력값을 `last_stage_trigger_percent` 로 분리 전달. 미리보기/생성 API 양쪽에서 사용.
- `models/strategy_template.py`, `api/v1/admin.py` — 문서/필드 설명 업데이트.
- `tests/unit/test_strategy_calculator_v2.py` — `test_10_stage_short_default_pct` 가 신규 default 에 맞게 갱신.

---

## [2026-04-25 ~ 2026-04-26] — Phase B + C + D 풀 구현

### 🎯 운영자 의도 반영
- **동적 1~10단계 진입** — 단계별 capital + trigger % 모두 가변
- **5단계 익절 분할** — TP1~5 임계 + 청산 수량 % 가변
- **트레일링 익절** — 피크 +20% 후 +20% 회귀 시 전량 청산
- **크라이시스 복구 모드** — 5+ 단계 + -30% 손실 → TP1 +5% / -1% SL / -5% 트레일
- **자동 재진입** — SL 후 delay 경과 시 자동 새 전략 시작

### ✨ 신규 기능

#### Phase B — 동적 N단계
- 알embic 0004 — `stages_config` JSONB 컬럼
- StrategyCalculator V2 — `_default_middle_trigger_pct(stage_no)` 함수 (2/3/4단계=10%, 5+=20%)
- StrategyService — `_resolve_stages_config()` 어댑터 (구 4단계 호환)
- POST /admin/strategy-templates — 운영자 입력 admin API
- Seed 템플릿 3종 — short_3stage_v2, short_5stage_v2, short_10stage_v2
- 단위 테스트 6 클래스

#### Phase C — 운영자 친화 대시보드 v3
- **C-1** 한국어화 + 신호등 색상 시스템
  - 13가지 상태 영문 코드 → 한국어 매핑
  - 단계 진행 바 (━━○○○ 1/4) + 펄스 애니메이션
  - 위험 알림 띠 자동 표시
- **C-2** 신규 전략 시작 모달 (Swagger 졸업)
  - 직접 입력 (1~10단계 자유) / 템플릿 선택 / 이전 전략 불러오기
  - 시세 패널 + 24h 미니 차트 + 시작가 자동 채움 7버튼
  - ⚙️ TP1~5 + SL 가변 (▲▼ 1씩 스피너)
  - 전략 수정 (✏️) — 기존 종료 → 새 설정 재시작
- **C-3** 활동 타임라인
  - /strategies/{id}/timeline — orders + risk_events + notifications 통합
  - 단계별 계획 시각화 (✅ 발동됨 / ⏳ 대기)
- **C-4** 메트릭 가교
  - Redis heartbeat → API 폴링 → Prometheus gauge
  - user_stream_connected, scheduler_leader_status 정상 표시
- **C-5** 운영 통계 + 활동 피드 + 시스템 상태 패널
  - 전체/완료/손절/승률/누적 PnL/크라이시스 발동
  - 메인 화면 최근 활동 피드 (5초 자동 갱신)
  - 8개 컴포넌트 신호등 (API/DB/Redis/Scheduler/UserStream/Telegram/Sentry/DBBackup)

#### Phase D — 크라이시스 복구 모드
- **D-1** 데이터 추적
  - Alembic 0006 — 5 컬럼 (max_loss/profit_pct, crisis_*, peak_pnl_*)
  - risk_service: `_update_pnl_extremes`, `_should_trigger_crisis_mode`, `_enter_crisis_mode`
- **D-2** TP/SL 룰
  - `_eval_crisis_mode_tp_sl` — Stage1 (+5% TP) / Stage2 (-5% 트레일 + -1% SL)
  - orchestrator: `_execute_crisis_action` (CRISIS_TP1 / CRISIS_TRAIL_FULL / CRISIS_HARD_SL)
  - notification 4종 추가
  - 단위 테스트 5종 (시나리오 A/B/C + 우선순위 + 가드)
- **D-3** 대시보드 표시
  - 모드 배지 (정상/🚨크라이시스/🛡크라이시스 보호)
  - 최대손실/이익 컬럼 추가
  - 위험 알림 띠 자동 (크라이시스 활성)

#### 자동 재진입
- Alembic 0007 — `reentry_delay_seconds`, `reentry_offset_pct` 컬럼
- `auto_reentry_worker.py` — 30초 주기 검사
- scheduler 통합
- Telegram 자동 재진입 알림

#### 거래소 계정 / 시세 / 심볼 API
- Exchange Account CRUD (POST + GET) — api_key/secret 자동 Fernet 암호화
- /api/v1/symbols — 심볼 자동완성용
- /api/v1/market/ticker24h, /klines — Binance public API 프록시 (CORS 회피)

#### 알림 (Telegram 한국어 10종)
- 단계 진입 / TP1~5 / SL / Kill-Switch / 일일 한도 / 청산 임박
- 크라이시스: 진입 / 첫 TP / 트레일링 청산 / 빠른 손절 / 자동 재진입

#### 관리툴
- 미리보기 인라인화 (DB 미생성)
- 템플릿 삭제 + cascade 옵션
- _quick_* 자동 숨김 + 일괄 정리
- 종료된 전략 숨김 토글
- 전략 강제 정지 (DB-only, 거래소 호출 없이)

#### 데이터 내보내기
- /admin/export/strategies — CSV (한글 헤더 + UTF-8 BOM, Excel 호환)
- /admin/export/orders — CSV
- 대시보드 다운로드 버튼

### 🔒 인프라 / 보안
- DB 자동 백업 (postgres-backup-local) — 일/주/월 (7/4/6 보관) — 실전 검증 (한 번 살림)
- DB 보안: priv_esc superuser 정리 + 5433 포트 127.0.0.1 바인딩
- POSTGRES_PASSWORD `${POSTGRES_PASSWORD:-postgres}` 환경변수 분리
- Grafana env 비번 (`GF_SECURITY_ADMIN_PASSWORD=Admin1234!`)
- python-multipart 추가 (Swagger Authorize 호환)
- OAuth2 form-data 로그인 엔드포인트 `/auth/token`

### 📊 모니터링
- Grafana 대시보드 12 패널 — User Stream / Scheduler / Kill-Switch / 활성포지션 / TP/SL 24h / 단계 트리거 / TP 레벨 / API 요청률 / API 지연 p95 / Stream 이벤트 / 단계 실패
- Prometheus 메트릭 14종

### 🐛 Critical Bug Fixes
1. **DB 인증 반복 깨짐** → `ALTER USER postgres WITH PASSWORD 'postgres';` + DB 백업/복구로 안정화
2. **priv_esc Superuser 백도어** → DROP USER + 127.0.0.1 바인딩
3. **Telegram chat_id 혼동** → update_id (338330188) 가 chat_id 자리에 들어감, 정정 (6445185531)
4. **Telegram parse_mode 400** → HTML mode 제거, plain text 로 변경
5. **HTML JS 템플릿 리터럴 깨짐** — TP1~5 행이 `${...}.map().join()` 으로 텍스트 출력 → 5행 직접 풀어 작성
6. **openCreateModal 트리거 기본값 덮어쓰기** — buildCapitalsGrid 후 초기화 루프가 trigger 도 비움 → 트리거 라인 제거
7. **user-stream MultipleResultsFound** → `.order_by(id).limit(1)` + 가짜 키 #3 비활성화
8. **calculator NameError** — `DEFAULT_MIDDLE_TRIGGER_PCT` 잔재 사용처 수정 → `_default_middle_trigger_pct(stage_no)` 함수로

### 📁 신규 파일
```
backend/alembic/versions/
  0005_more_tp_levels.py
  0006_pnl_tracking_crisis_mode.py
  0007_auto_reentry.py

backend/app/api/v1/
  exchange_accounts.py    Exchange Account CRUD
  symbols.py              심볼 조회
  market.py               Binance public API 프록시

backend/app/workers/
  auto_reentry_worker.py  자동 재진입

backend/app/static/
  index.html              운영자 대시보드 v3 (단일 HTML, ~1500 줄)

backend/tests/unit/
  test_strategy_calculator_v2.py
  test_crisis_recovery_mode.py

문서:
  DASHBOARD_V2_PLAN.md           대시보드 v2 기획서
  CRISIS_RECOVERY_MODE_PLAN.md   크라이시스 모드 기획서
  OPERATIONS.md                  운영 매뉴얼
  CHANGELOG.md                   이 문서
  binance_auto_trader_deploy_*.zip  배포 압축
```

### 📈 통계
- **총 task 수**: 74 (#11~#74)
- **commit 수**: ~10 (이번 세션)
- **신규 엔드포인트**: 20+ (admin / strategies / exchange-accounts / market / symbols)
- **신규 알림**: Telegram 10종
- **신규 DB 컬럼**: 11 (Phase D-1 5 + tp4/5 4 + reentry 2)
- **마이그레이션 추가**: 0005, 0006, 0007

### 🚧 보류 (다음 세션 대상)
- testnet 1주 라이브 검증 (운영자 수동 검증 필요)
- Sentry DSN 입력 (외부 가입)
- Mainnet 100 USDT 시작 (testnet 1주 후)
- 백테스팅 모듈 (1~2일 작업)
- PnL 시계열 차트 (Recharts/Chart.js, 데이터 누적 후)
- prometheus_client multiprocess mode (Phase C-4 제대로된 fix)

---

## [이전 세션] — Phase A 인프라 구축

(요약)
- Docker Compose 8 컨테이너 구성
- Alembic 0001~0004
- FastAPI + SQLAlchemy + JWT 인증
- Binance Futures 클라이언트 + WebSocket User Stream
- BinanceTestnet 검증 (Stage 1 LIMIT 주문 발송 + exchange_order_id 13074939145)
- Scheduler + APScheduler + Distributed Leader Lock
- TP/SL 오케스트레이터 + Risk Service
- 기본 4단계 전략 템플릿 + Seed
- GitHub private repo (herosys1-crypto/binance-auto-trader) 동기화

---

## 작성 규칙

- 새 세션 시작 시 이 파일 상단에 새 섹션 추가
- 각 변경은 의도 / 영향 범위 / 신규 파일 / 버그 픽스 분류
- mainnet 전환 후 `[YYYY-MM-DD] vX.Y MAINNET` 식으로 버전 태그
