# 시스템 정밀 기획서 — Binance Futures Auto Trading Platform

작성일: 2026-05-02
대상: 옵션 C 단계별 자동 거래 시스템 (testnet/mainnet 동일 코드, exchange_account 의 `is_testnet` 으로 분기)

이 문서는 **시스템을 처음부터 다시 개발할 수 있을 정도의 정밀도**로 비즈니스 로직, 데이터 모델, API, 워커, 알림, 보안, 인프라를 정의합니다. 코드 audit 의 기준이 됩니다.

---

## 1. 개요

### 1.1 목적
사용자가 정의한 옵션 C 거래 전략을 Binance Futures (USDⓢ-M Perpetual) 에서 자동 실행. 단계별 분할 진입 + 분할 익절 + 트레일링 + 크라이시스 모드 + 안전 장치.

### 1.2 사용자
- 1인 운영 (single-user multi-account 가능)
- testnet 으로 검증 후 mainnet 운영

### 1.3 운영 환경
- Docker Compose 11개 컨테이너 (api / scheduler / user-stream / postgres / redis / prometheus / grafana / db-backup / nginx-가능)
- DB: PostgreSQL (로컬 docker 또는 Neon Cloud 둘 다 지원)
- Cache: Redis
- 텔레그램 알림
- Sentry / Prometheus 메트릭

---

## 2. 핵심 비즈니스 로직 — 옵션 C 거래 시나리오

### 2.1 단계별 진입 (Stage Entry)

**기획**: 1~10 단계로 동적 자본 분할. 각 단계는 trigger 조건 충족 시 LIMIT 주문으로 진입.

| 단계 | 자본 (capitals[i]) | Trigger Mode | Trigger Percent | 의미 |
|---|---|---|---|---|
| 1 | 사용자 입력 (>0 필수) | `IMMEDIATE` | (없음) | 즉시 LIMIT 주문, 사용자 입력 시작가 |
| 2 ~ N-1 | 사용자 입력 (>0) | `PRICE_UP_PCT` (SHORT) / `PRICE_DOWN_PCT` (LONG) | 직전 단계 trigger_price 대비 % | 가격이 불리한 방향으로 갈 때 추가 진입 |
| N (마지막) | 사용자 입력 (>0) | 사용자가 `last_stage_trigger_mode` 명시 또는 default `PRICE_UP_PCT`/`PRICE_DOWN_PCT` | `last_stage_trigger_percent` (기본 20%) | 마지막 단계도 사용자 입력값으로 진입 (옵션 C 핵심 변경, 2026-04-30) |

- **단계 수 N**: `len(capitals where capitals[i] > 0)`
- 비활성 단계 (자본 0 또는 빈 값) 는 stage_plan 에 row 만들지 않음
- 각 stage_plan 의 `trigger_price` 는 strategy_calculator 가 사전 계산
  - SHORT: 1단계가 base price → 2단계 = base × (1 + p2/100), 3단계 = 2단계 × (1 + p3/100), ...
  - LONG: 반대 방향

#### 2.1.1 단계별 trigger 기본값 (사용자 미지정 시)
- 2~4단계: 직전 대비 +10%
- 5~9단계: 직전 대비 +20%
- 마지막 단계: 직전 대비 +20% (사용자 기획 변경 후, 이전엔 LIQUIDATION_BUFFER 5%)

### 2.2 익절 (Take Profit)

**기획**: TP1~TP5 (1~5 동적 활성). 활성 TP 는 `tp[i]_percent != NULL` 인 레벨.

| TP | 발동 조건 | qty_ratio (default) | qty_ratio (사용자 가능) |
|---|---|---|---|
| TP1 | 평균진입가 대비 +tp1_percent% (SHORT 의 경우 -tp1_percent%) | 25% | 0~100% |
| TP2 | +tp2_percent% | 50% | 0~100% |
| TP3 | +tp3_percent% | 100% | 0~100% |
| TP4 | +tp4_percent% (NULL 가능) | 100% | 0~100% |
| TP5 | +tp5_percent% (NULL 가능) | 100% | 0~100% |

**`close_ratio` 계산 (각 TP 발동 시 청산 비율)**:
1. **TRAILING_TP** 발동: `close_ratio = 1.00` (전량 청산)
2. **마지막 활성 TP** 발동 ⭐: `close_ratio = 1.00` (사용자 기획 "4/4 익절 모두 종료 = 전략 종료", 2026-05-02 fix `0e3d119`)
3. **크라이시스 모드 + TP1~4**: crisis_qty_ratio 사용 (25/25/50/100)
4. **일반 중간 TP**: 사용자 `tp[i]_qty_ratio` (또는 default) / 100

**`close_qty` 계산**:
- `current_qty = abs(strategy.current_position_qty)` — 잔량 기준
- `raw_qty = current_qty × close_ratio`
- 심볼의 `step_size` 단위로 floor: `close_qty = (raw_qty // step_size) × step_size`
- `close_qty <= 0` 면 skip

**TP 후 status 전환**:
- `is_final = (level == TRAILING_TP) OR (close_ratio >= 1.00)`
- TP1 + 부분: `TP1_DONE_PARTIAL`
- TP1 + 전량: `COMPLETED`
- ... TP5 발동: `COMPLETED`
- TRAILING: `COMPLETED`

`COMPLETED` 시 `reentry_ready = False`, peak_pnl Redis cache 리셋.

### 2.3 트레일링 익절 (Trailing TP)

**기획 (2026-04-30 변경)**: 절대 임계 → **피크 대비 -5% 회귀**.
- TP1 발동 후부터 활성화 (피크 ≥ +5% 도달 시점)
- 매 PnL 평가 시 Redis 의 peak 값 갱신 (0~PEAK)
- `peak - 현재 ≥ TRAILING_TP_RETRACE_AMOUNT (5%)` 이면 `TRAILING_TP` 발동

### 2.4 손절 (Stop Loss)

**기획**:
- 발동 조건: **모든 단계가 진입 완료된 상태** + 현재 PnL ≤ -50% (사용자 설정 `stop_loss_percent_of_capital`)
- 액션: 잔량 100% 청산 + status `CLOSED_BY_SL` (또는 `COMPLETED`)
- 텔레그램: `[손절 체결]` 알림 + 누적 PnL

### 2.5 크라이시스 복구 모드 (Crisis Mode)

**기획**:
- 진입 조건:
  - `max_loss_pct ≤ -30%` (CRISIS_MAX_LOSS_THRESHOLD)
  - 현재 PnL > 0% 로 회복됨
  - 단계 요구 사항 제거 (이전엔 5+ 단계 필요)
- 진입 시:
  - `crisis_mode_triggered_at` 채움
  - TP1 임계가 5% 로 하향 (CRISIS_TP1_THRESHOLD)
  - 알림 발송
- 진입 후 청산:
  - 첫 TP +5% 도달 → `crisis_first_tp_done_at` 채움 + 첫 TP 청산 (qty_ratio crisis 기준)
  - 첫 TP 후 피크 추적 → 피크 -5% 회귀 시 잔량 전부 청산 (`CRISIS_TRAIL_FULL`)
  - 첫 TP 후 PnL ≤ -1% (CRISIS_HARD_SL_THRESHOLD) 시 잔량 전부 손절

### 2.6 재진입 (Reentry)

**상태**: `REENTRY_READY`
- 트리거: TP/SL/트레일링 등으로 잔량 0 도달 + 사용자 정지가 아닌 경우
- 정책 (`reentry_policy`):
  - `manual_ready`: 사용자 수동 시작 대기 (default)
  - `auto`: `reentry_delay_seconds` 후 새 strategy_instance 생성 + 진입 가격은 마지막 진입가 기준 `reentry_offset_pct%` 떨어진 가격 (기획)

### 2.7 통합 포지션 정책 (Hedge Mode 충돌 방지)

**기획**:
- Binance hedge mode 는 `(symbol, position_side)` 단위 단일 포지션 — 같은 심볼+측면 다중 strategy 시 TP/SL 충돌
- 새 strategy 생성 시 활성 strategy 와 `(symbol, side)` 중복이면 거절 (HTTP 400)
- 활성 = `status NOT IN ('STOPPED','COMPLETED','REENTRY_READY','CLOSED','CLOSED_BY_TP','CLOSED_BY_SL','KILL_SWITCH_TRIGGERED')`

### 2.8 수동 정지 / 청산

**기획**:
- 모드:
  - `cancel_only`: 미체결 주문만 취소 → status `STOPPING`
  - `close_position_market`: 잔량 reduce-only market + 미체결 취소 → status `STOPPING` → EXIT FILLED 후 `STOPPED`
  - `emergency_stop`: 즉시 + 강제 청산
- status 전환 (오늘 fix `2677aff`):
  - 거래소 청산 후 stream EXIT FILLED → `current_position_qty=0` + `STOPPING → STOPPED` (`stopped_at` 채움)

### 2.9 status 전체 표

| Status | 의미 |
|---|---|
| `WAITING` | 생성 후 시작 전 |
| `STAGE1_OPEN_PENDING` ~ `STAGE4_OPEN_PENDING` | 단계 진입 LIMIT 발송 후 체결 대기 |
| `STAGE1_OPEN` ~ `STAGE4_OPEN` | 단계 진입 체결 완료 (대시보드: 활성) |
| `TP1_DONE_PARTIAL` ~ `TP5_DONE_PARTIAL` | TP 발동 + 잔량 남음 |
| `STOPPING` | 사용자 정지 중 (청산 진행) |
| `STOPPED` | 정지 완료 |
| `REENTRY_READY` | 청산 완료 + 재진입 가능 |
| `COMPLETED` | 모든 TP 완료 또는 트레일링 청산 |
| `CLOSED` | 일반 종료 (legacy) |
| `CLOSED_BY_TP` / `CLOSED_BY_SL` | 자동 종료 reason 명시 |
| `KILL_SWITCH_TRIGGERED` | kill switch 발동 |

---

## 3. 데이터 모델 (DB Schema)

### 3.1 `users`
```
id PK, email UNIQUE, password_hash, is_active, is_admin, created_at
```

### 3.2 `exchange_accounts`
```
id PK, user_id FK, exchange_name (default 'binance'), market_type (default 'usds_m_futures'),
api_key_enc, api_secret_enc, passphrase_enc nullable,
hedge_mode_enabled (default true), is_testnet (default false), is_active (default true),
created_at, updated_at
```
- `api_key_enc`/`api_secret_enc` 는 ENCRYPTION_KEY (Fernet) 로 암호화

### 3.3 `symbols`
```
id PK, symbol UNIQUE, base_asset, quote_asset, contract_type, status,
price_precision, quantity_precision, tick_size, step_size, min_qty, min_notional,
raw_exchange_info JSONB, created_at, updated_at
```

### 3.4 `strategy_templates`
```
id PK, name UNIQUE, strategy_type (DYNAMIC_LONG/DYNAMIC_SHORT 등), side, leverage, total_capital,
stages_config JSONB (capitals, trigger_percents, last_stage_trigger_mode/percent),
stage1~4_capital nullable (legacy), stage2/3_trigger_percent nullable (legacy),
stage4_trigger_mode nullable (legacy), stage4_trigger_percent nullable (legacy),
tp1~3_percent NOT NULL, tp4~5_percent nullable,
tp1~3_qty_ratio NOT NULL, tp4~5_qty_ratio nullable,
stop_loss_percent_of_capital NOT NULL,
reentry_policy (default manual_ready), reentry_delay_seconds (600), reentry_offset_pct (1.0),
is_active (default true), created_at, updated_at
```
- `stages_config` 가 신규. 옵션 C 의 1~10 단계 동적 지원
- legacy `stage1~4_capital` 은 4단계 호환용 — 새 코드는 stages_config 사용

### 3.5 `strategy_instances`
```
id PK, user_id, exchange_account_id, strategy_template_id, symbol_id, symbol, side,
start_price NOT NULL, leverage NOT NULL, total_capital NOT NULL,
current_stage (default 0), avg_entry_price nullable, current_position_qty (default 0),
invested_capital (default 0), realized_pnl (default 0), unrealized_pnl (default 0),
liquidation_price nullable, status (default WAITING) INDEX, reentry_ready (default false),
last_error_code nullable, last_error_message nullable,
started_at nullable, stopped_at nullable,
max_loss_pct nullable, max_profit_pct nullable,
crisis_mode_triggered_at nullable, crisis_first_tp_done_at nullable,
peak_pnl_pct_after_first_tp nullable,
created_at, updated_at
```

### 3.6 `strategy_stage_plans`
```
id PK, strategy_instance_id FK CASCADE INDEX, stage_no, side,
trigger_mode (IMMEDIATE/PRICE_UP_PCT/PRICE_DOWN_PCT/LIQUIDATION_BUFFER),
trigger_percent nullable, trigger_price nullable, planned_capital, planned_qty nullable,
is_enabled (default true), is_triggered (default false), triggered_at nullable,
created_at
```

### 3.7 `orders`
```
id PK, strategy_instance_id FK CASCADE INDEX, stage_no nullable,
purpose (ENTRY/EXIT/TAKE_PROFIT/STOP_LOSS/EMERGENCY_CLOSE),
symbol INDEX, side, position_side, order_type, time_in_force nullable,
client_order_id UNIQUE NOT NULL, exchange_order_id BigInt nullable,
trigger_price nullable, price nullable, orig_qty nullable, executed_qty (default 0),
avg_price nullable, status NOT NULL INDEX,
raw_request JSONB nullable, raw_response JSONB nullable,
created_at, updated_at
```

### 3.8 `positions`
```
id PK, strategy_instance_id FK CASCADE INDEX, symbol, side, position_side,
entry_price/break_even_price/mark_price/liquidation_price/position_amt nullable,
isolated_margin/unrealized_pnl nullable, margin_type nullable, leverage nullable,
source (ACCOUNT_UPDATE/POSITION_RISK_SYNC), snapshot_time
```
- 시계열 — 매 ACCOUNT_UPDATE 또는 reconcile 마다 INSERT (audit log)

### 3.9 `notifications`
```
id PK, strategy_instance_id FK SET NULL nullable INDEX,
channel (TELEGRAM/EMAIL/...), title, body, send_status (PENDING/SENT/FAILED),
external_message_id nullable, sent_at nullable, created_at
```

### 3.10 `risk_events`
```
id PK, strategy_instance_id FK SET NULL nullable INDEX, event_type, severity (INFO/WARN/ERROR/CRITICAL),
title, message, event_payload JSONB, created_at
```
- 0008 마이그레이션에서 strategy_id nullable (시스템 레벨 event 도 기록)

### 3.11 `stream_sessions`
```
id PK, exchange_account_id FK INDEX, listen_key, started_at, last_keepalive_at, expired_at, is_active
```
- user-stream WebSocket 세션 추적

### 3.12 `account_kill_switches`
```
id PK, exchange_account_id FK UNIQUE, is_enabled, reason_code, reason_message,
triggered_at nullable, triggered_by nullable, created_at, updated_at
```

### 3.13 `account_daily_risk_limits`
```
id PK, exchange_account_id FK INDEX, date_utc, total_realized_pnl, daily_loss_limit_pct,
limit_breached_at nullable, created_at, updated_at
```

---

## 4. 서비스 (비즈니스 로직 레이어)

### 4.1 `auth_service`
- 사용자 회원가입/로그인 (이메일+password_hash)
- JWT 발급/검증 (SECRET_KEY 사용)

### 4.2 `strategy_calculator`
- 입력: SymbolRule + StrategyTemplate (또는 stages_config) + start_price + side
- 출력: stages 배열 (1~10), 각 stage 의 trigger_mode/percent/price + planned_capital/qty
- TP/SL 가격도 계산
- 핵심 함수:
  - `_default_middle_trigger_pct(stage_no)` — 2~4=10%, 5+=20%
  - 마지막 단계 default mode SHORT=`PRICE_UP_PCT`/LONG=`PRICE_DOWN_PCT` (사용자 기획 변경 후)

### 4.3 `strategy_service`
- 전략 생성/시작/조회/정지
- **중복 hedge 모드 검증**: 새 strategy 생성 시 active 한 같은 (symbol, side) 검사
- 전략 시작: stage_plan 생성 + 1단계 ENTRY LIMIT 발송 + status STAGE1_OPEN_PENDING

### 4.4 `execution_service`
- Binance API 호출 wrapper
- 주문 발송: ENTRY (LIMIT) / EXIT (MARKET reduce-only)
- `place_market_order`, `place_limit_order`, `cancel_order`, `cancel_all_orders`
- `emergency_close_position` — 거래소 실 포지션 확인 → reduce-only market → status STOPPING (commit 먼저, 2026-05-02 fix)

### 4.5 `tp_sl_orchestrator` ⭐ 핵심
- 30초 사이클 (scheduler)
- 활성 strategy 들 PnL 평가 → TP/SL/트레일링/크라이시스 발동 결정
- `_evaluate_strategy(strategy)`:
  1. 현재 PnL% 계산 (mark_price 기반)
  2. RiskService 의 _update_pnl_extremes 호출 (max_loss/profit 갱신)
  3. 크라이시스 모드 진입 조건 체크
  4. SL 조건 체크
  5. 트레일링 조건 체크
  6. 각 TP 레벨 임계 도달 체크 (가격 도달 시 발동)
- `_execute_take_profit(strategy, level)` ⭐:
  - close_ratio 결정 (위 2.2 의 우선순위)
  - close_qty = floor(current_qty × close_ratio, step_size)
  - emergency_close_position 호출
  - status 전환 (TP[N]_DONE_PARTIAL or COMPLETED)
- 동시성: Redis lock 으로 같은 strategy 동시 평가 차단

### 4.6 `risk_service`
- `_update_pnl_extremes(strategy, pnl_ratio)` — max_loss/max_profit 갱신 (음수만 max_loss, 양수만 max_profit, 2026-04-30 fix `69692d4`)
- `_should_trigger_crisis_mode(strategy, current_pnl_pct)` — 크라이시스 진입 조건
- `evaluate_stop_loss(strategy_id)` — SL 발동 여부
- 트레일링 peak 추적 (Redis cache, key: `peak_pnl:{strategy_id}`, TTL 30일)

### 4.7 `notification_service`
- `send(strategy_instance_id, channel, title, body)`:
  1. **dedup gate**: 60초 윈도우 내 동일 (strategy + title + send_status IN ['SENT','PENDING']) 면 skip + 기존 row 반환
  2. PENDING row 추가 + flush
  3. Telegram API 호출
  4. SENT 또는 FAILED 마킹 + commit
- 알림 종류:
  - `[전략 시작]`, `[N단계 진입]`, `[TPN 익절 체결]`, `[TRAILING_TP 익절 체결]`, `[손절 체결]`, `[크라이시스 모드 진입]`, `[수동 청산]`

### 4.8 `stream_service` ⭐ 핵심
- Binance user-stream 이벤트 수신 처리
- `handle_order_trade_update(payload)`:
  1. client_order_id 로 local Order 조회
  2. unmatched 면 RiskEvent WARN + return
  3. **idempotent gate** ⭐ (2026-05-02 fix): order 의 prev_status 가 이미 FILLED 였으면 후속 이벤트 무시 (중복 누적 방지)
  4. order.status/executed_qty/avg_price 갱신
  5. ENTRY FILLED 분기:
     - status STAGE_N_OPEN 으로 전환
     - stage_plan 의 is_triggered atomic UPDATE WHERE (race-free)
     - rowcount=1 이면 단계 진입 알림 발송
  6. EXIT FILLED 분기:
     - 부분 vs 전체 청산 구분 (잔량 abs 계산)
     - 전체: status 전환
       - COMPLETED → 보존
       - STOPPING → STOPPED + stopped_at (2026-04-30 fix)
       - 그 외 → REENTRY_READY
     - 부분: 잔량 sign 보존 (2026-04-30 fix `0da0f55`)
     - realized_pnl 누적 (LONG: qty × (exit-entry), SHORT: qty × (entry-exit))
- `handle_account_update(payload)`:
  - active strategy 에 대해 position_amt / unrealized_pnl / mark_price 갱신
  - Position row INSERT (snapshot)
  - `_CLOSED_STATUSES = {REENTRY_READY, CLOSED, STOPPING, COMPLETED}` 매칭 제외
- `handle_listen_key_expired` — RiskEvent CRITICAL

### 4.9 `symbol_sync_service`
- Binance `/fapi/v1/exchangeInfo` 호출 → symbols 테이블 upsert
- row 단위 try/except + 개별 commit (2026-04-29 fix Bug #9)

### 4.10 `account_kill_switch_service`
- 수동/자동 발동: 모든 active strategy 정지 + 새 진입 차단

### 4.11 `account_daily_loss_limiter`
- 매 strategy 시작 전 일일 한도 체크
- 한도 초과 시 새 진입 거부 + 알림

---

## 5. 워커 (백그라운드 프로세스)

### 5.1 `binance_user_stream_consumer` (run_user_stream)
- Binance WebSocket user-stream 연결
- listenKey 발급 → ws://...binancefuture.com/ws/{listenKey}
- 이벤트 타입별 stream_service 의 handler 호출
- 끊김 시 재연결 + RiskEvent CRITICAL

### 5.2 `keepalive_worker`
- 30분 간격 listenKey ping (Binance 60분 만료 정책)
- 만료 시 새 키 발급 + WebSocket 재연결

### 5.3 `scheduler_runner` (APScheduler)
- 매 30초: tp_sl_orchestrator 평가 + reconcile_worker
- 매 1분: stage_trigger_worker (가격 도달 시 stage 진입 LIMIT 발송)
- 매 일 03:00 UTC: symbol_sync
- distributed_scheduler_guard 로 multi-instance 동시 실행 방지

### 5.4 `reconcile_worker` ⭐
- 활성 strategy 의 거래소 실 포지션 vs DB 동기화
- status filter 에 `STOPPING` 포함 (2026-04-30 fix `2677aff`):
  - 거래소 포지션 0 면 STOPPED 자동 승격 (좀비 정리)
- `_OPEN_STATES` (STAGE_N_OPEN, TP1/2_DONE_PARTIAL): 거래소 매칭 없으면 STOPPED orphan 자동 정리
- `_PENDING_TO_OPEN`: PENDING + 거래소 포지션 있음 → OPEN 전이 (자가 회복)

### 5.5 `stage_trigger_worker`
- 매 1분: 활성 strategy 의 다음 stage 가 trigger_price 도달했나 체크
- 도달 시 LIMIT 주문 발송 + status STAGE_N_OPEN_PENDING

### 5.6 `auto_reentry_worker`
- REENTRY_READY 상태 + reentry_policy=auto + reentry_delay 경과 시 자동 재진입

---

## 6. API 명세

### 6.1 인증 (`/api/v1/auth`)
- `POST /register` (이메일+password)
- `POST /login` → JWT
- `GET /me`

### 6.2 거래소 계정 (`/api/v1/exchange-accounts`)
- `GET /` — 본인 계정 목록
- `POST /` — 추가 (api_key/secret 입력 → ENCRYPTION_KEY 로 암호화)
- `DELETE /{id}`

### 6.3 전략 (`/api/v1/strategies`)
- `POST /preview-inline` — 직접 입력으로 미리보기 (template 만들지 않음)
- `POST /calculate` — template 기반 미리보기
- `POST /` — 전략 생성 (중복 검사)
- `POST /{id}/start` — 시작 (1단계 LIMIT 발송)
- `POST /{id}/stop` — 정지 (cancel_only/close_position_market/emergency_stop)
- `POST /{id}/edit` — 활성 전략 일부 수정
- `GET /` — 목록 (with template 기반 total_active_stages/tps, 2026-05-02 fix)
- `GET /{id}` — 상세
- `GET /{id}/timeline` — 이벤트 timeline
- `GET /{id}/stage-plans` — stage plan 목록

### 6.4 주문 (`/api/v1/orders`)
- `GET /` — 주문 history
- `POST /cancel/{order_id}`

### 6.5 포지션 (`/api/v1/positions`)
- `GET /` — 현재 포지션 (DB)
- `GET /sync` — 거래소에서 강제 동기화

### 6.6 시장 (`/api/v1/market`)
- `GET /price/{symbol}` — 현재가
- `GET /klines/{symbol}` — 차트 데이터

### 6.7 심볼 (`/api/v1/symbols`)
- `GET /` — symbols 테이블 dump

### 6.8 관리자 (`/api/v1/admin`)
- `GET /system-health`
- `GET /stats`, `/recent-activity`
- `POST /symbol-sync`
- `POST /telegram-test`
- `POST /kill-switch/{exchange_account_id}/enable|disable`
- `POST /strategy-templates` — 임시 template 생성

### 6.9 이벤트 (`/api/v1/events`)
- `GET /risk-events`
- `GET /notifications`

---

## 7. 프론트엔드 (`/static/index.html`)

- SPA-like (vanilla JS), Tailwind CSS, lightweight charts
- 대시보드:
  - 시스템 상태 (api/db/redis/scheduler/user-stream/telegram/sentry/db-backup)
  - 진행 중 전략 / 미실현 손익 / 전략 템플릿
  - 전략 인스턴스 테이블 (진입 X/N + 익절 X/M, 동적 분모, 2026-05-02 fix)
  - 빠른 액션: 새 전략, Telegram, Grafana, API
  - 운영 통계 (전체 누적)
  - 최근 활동 (이벤트 시계열)
- 새 전략 모달:
  - 거래소 계정 선택, 심볼, 측면 (LONG/SHORT)
  - 시작가 (LIMIT 1단계)
  - 직접 입력 모드 (stage 1~10 capitals + triggers) 또는 template 모드
  - TP1~5 percent + qty_ratio 입력
  - SL percent
  - 미리보기 → 전략 생성

---

## 8. 알림 (Telegram)

### 8.1 메시지 종류
- `📉 [전략 시작] {symbol} {side}`
- `📉 [{N}단계 진입] {symbol} {side}` — 진입가 + 수량 + 평균진입가
- `✅ [TP{N} 익절 체결] {symbol} {side} 📉` — 청산 단가 + 청산 수량 + 남은 수량 + 손익 + ROI
- `✅ [TRAILING_TP 익절 체결] ...`
- `🛑 [손절 체결] ...`
- `⚠️ [크라이시스 모드 진입] ... max_loss / max_profit`
- `🛑 [수동 청산]`
- `❌ [Kill switch 발동]`

### 8.2 Dedup gate
- `_is_recent_duplicate(strategy_instance_id, title)`:
  - 60초 윈도우 (NOTIFICATION_DEDUP_WINDOW_SECONDS)
  - send_status IN ('SENT', 'PENDING') 면 True
- atomic stage_plan UPDATE WHERE 와 함께 이중 보호

---

## 9. 보안

### 9.1 자격증명
- `.env` 파일 (gitignored, chmod 600 권장)
- 노출 시 즉시 갱신 (SECRET_KEY, DB password, Telegram, ENCRYPTION_KEY)

### 9.2 암호화
- `ENCRYPTION_KEY` (Fernet base64 32-byte) 로 거래소 api_key/secret 암호화
- 키 변경 시 DB 마이그레이션 필요 (`deploy/encryption_key_migration.py`)

### 9.3 인증
- JWT (HS256, SECRET_KEY)
- ACCESS_TOKEN_EXPIRE_MINUTES = 10080 (7일)

### 9.4 거래소 API 권한 최소화 (mainnet)
- ✅ Futures only
- ❌ Spot, Withdrawals, Universal Transfer
- IP whitelist (서버 IP 만)

---

## 10. 인프라

### 10.1 Docker Compose 서비스
- `db` (postgres:16) — local 또는 disabled (Neon 사용 시)
- `redis` (redis:7) — peak cache + lock
- `api` (uvicorn) — FastAPI
- `scheduler` — APScheduler
- `user-stream` — WebSocket
- `prometheus` + `grafana` — 메트릭
- `db-backup` (postgres-backup-local) — 일/주/월 보관

### 10.2 메트릭 (Prometheus)
- `user_stream_events_total{event_type}`
- `position_reconcile_total{status}`
- `position_qty_mismatch_total{symbol, side}`
- `strategy_runs_total{...}`
- `strategy_take_profit_total{symbol, side, level}`
- `strategy_stop_loss_total{...}`

### 10.3 로그
- Docker daemon json-file driver, max-size 100MB, max-file 5

### 10.4 백업
- DB: db-backup 컨테이너 매일 03:00 UTC
- (mainnet 권장) 오프사이트 sync (S3/B2)

### 10.5 Production (DigitalOcean VPS, 옵션)
- Ubuntu 24.04, 8GB / 2 vCPU, Singapore region
- Nginx HTTPS reverse proxy, Let's Encrypt
- Cloud Firewall + ufw (80/443/22 만)
- Backup snapshot 주 1회

---

## 11. 테스트 정책

### 11.1 Unit test
위치: `backend/tests/unit/`

**필수 보장 영역:**
- `test_stream_mapper` — payload 매핑
- `test_stream_service_partial_close` — 부분/전체 청산 + STOPPING + idempotent (2026-05-02)
- `test_risk_service_pnl_extremes` — max_loss/profit 음수/양수 분리
- `test_tp_sl_last_active_tp` — 마지막 활성 TP 발동 시 잔량 100%
- `test_strategy_calculator` (옵션 C 1~10단계 계산)
- `test_crisis_recovery_mode`
- (필요) `test_reconcile_worker_zombie` — STOPPING 좀비 자동 정리
- (필요) `test_execution_service_emergency_close` — race fix 검증

### 11.2 통합 test
- DB session fixture (sqlite in-memory)
- 한 사이클 전체 (생성 → 진입 → TP → 종료)
- 누락 가능성 — 별도 `tests/integration/` 검토 필요

### 11.3 회귀 방지
- 발견된 모든 critical 버그는 unit test 로 잠금
- 65 tests 통과 + 새 fix (2026-05-02) 추가

---

## 12. 의존성

### 12.1 Python 라이브러리 (`requirements.txt`)
- fastapi, uvicorn[standard], starlette
- sqlalchemy >= 2.0, alembic, psycopg2-binary
- pydantic >= 2.0, pydantic-settings
- redis, APScheduler
- requests, websocket-client, httpx
- cryptography (Fernet), bcrypt, PyJWT, passlib[bcrypt]
- email-validator, python-multipart
- prometheus-client, prometheus-fastapi-instrumentator
- sentry-sdk[fastapi]
- pytest

### 12.2 외부 서비스
- Binance Futures API (mainnet + testnet)
- Telegram Bot API (BotFather 발급)
- Neon Cloud Postgres (선택, 또는 local docker)
- Sentry (선택, production 권장)

---

## 13. 알려진 제약 / 안전 가정

1. **Binance hedge mode**: `(symbol, position_side)` 단일 포지션. 같은 심볼+측면 다중 strategy 절대 금지.
2. **Stream 이벤트 중복**: 같은 trade settlement 에 대해 multiple ORDER_TRADE_UPDATE 가능 — idempotent gate 필수 (2026-05-02 fix).
3. **race condition**: status 변경 commit 과 거래소 호출 순서 — STOPPING 먼저 commit (2026-05-02 fix).
4. **realized_pnl 누적**: 같은 EXIT 의 stream event 중복 방지 (위 idempotent gate 와 동일 메커니즘).
5. **DB 가용성**: Neon Cloud 사용 시 외부 망 문제 → reconcile_worker 가 거래소 정합성 보호.
6. **listenKey 만료**: 60분 정책 → keepalive_worker 30분 ping.
7. **strict 가격 정밀도**: step_size / tick_size — 모든 주문 직전 floor 적용.

---

## 14. 운영 검증 체크리스트 (mainnet 가기 전)

- [ ] 옵션 C 종단간 testnet 시나리오 (직접 입력 6단계 + 마지막 TP 잔량 100% 청산)
- [ ] 좀비 STOPPING 자동 정리 (수동 정지 후 STOPPED 자동 전환)
- [ ] dedup gate (단계 진입 알림 1회씩, 12개 메시지 중복 0)
- [ ] 부분 청산 잔량 보존 (TP1 25% 후 잔량 75% 모니터링 계속)
- [ ] max_loss/profit 음수/양수 분리 (#54/#55 같은 패턴 재발 X)
- [ ] EXIT FILLED idempotent (중복 누적 0, #79 사례 재발 X)
- [ ] race condition (수동 정지 후 STOPPED 정확 전환)
- [ ] reconcile worker 30초 사이클 (좀비 자동 회복)
- [ ] kill switch 시뮬레이션
- [ ] 일일 손실 한도 시뮬레이션
- [ ] DB backup 복원 시뮬레이션

---

이 문서가 시스템의 정의입니다. 다음 단계: **이 spec 을 기준으로 실제 코드 cross-check 후 차이/누락/모순 찾기**.
