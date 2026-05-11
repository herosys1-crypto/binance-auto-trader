# 바이낸스 USDⓢ-M Perpetual 자동매매 시스템 — 개발 기획서

| 항목 | 내용 |
|---|---|
| 문서 버전 | v1.0 |
| 작성일 | 2026-05-12 |
| 작성 방식 | Reverse-engineered from current codebase (HEAD = `89cbd1c`) |
| 검증 기준 | `backend/` 코드 베이스 전체 + 527 회귀 테스트 통과 상태 |
| 운영 환경 | Testnet (159.65.137.250) — mainnet 전환 전 |
| 다음 단계 | `CONSISTENCY_CHECKLIST.md` 로 코드 vs 기획서 정합성 점검 |

---

## 1. 시스템 개요

### 1.1 목적
1인 운영자가 Binance Futures USDⓢ-M Perpetual 시장에서 **분할 진입 + 자동 익절/손절 + 위기 복구** 전략을 24시간 자동 실행하는 트레이딩 시스템.

### 1.2 사용자
- **1인 운영자 (admin role)** — 단일 계정 모델 (FK 없음, 멀티 user 미지원).
- 한국어 UI, 한국 시간(KST) 운영, GitHub 웹 UI 만 사용 (gh CLI X), 사무실↔집 핸드오프.

### 1.3 운영 환경
- **VPS**: DigitalOcean SGP1 General Purpose 8GB (159.65.137.250).
- **DB**: Neon Cloud PostgreSQL (Singapore).
- **Repo**: `https://github.com/herosys1-crypto/binance-auto-trader`.
- 배포: `git pull` + `docker compose restart api scheduler` (수동).

### 1.4 기술 스택
| 계층 | 기술 |
|---|---|
| Backend | Python 3.12 + FastAPI + SQLAlchemy 2.0 + Pydantic v2 |
| DB | PostgreSQL 16 (Neon Cloud) + Alembic migrations |
| Cache/Lock | Redis 7 |
| 백그라운드 | APScheduler `BlockingScheduler` (Asia/Seoul) |
| Stream | Binance User Data WebSocket (별도 컨테이너) |
| Frontend | Single-page HTML + vanilla JS + Tailwind CSS (CDN) |
| 컨테이너 | Docker Compose (8 services) |
| 관측 | Prometheus + Grafana + Telegram heartbeat |

---

## 2. 핵심 비즈니스 룰

### 2.1 단계 진입 (Stage Entry, 1~10 동적)

| 단계 | trigger_mode | trigger_percent | 동작 |
|---|---|---|---|
| 1 | `IMMEDIATE` | NULL | start_price 에 LIMIT 즉시 발사 |
| 2~N-1 | `PRICE_UP_PCT` (SHORT) / `PRICE_DOWN_PCT` (LONG) | 사용자 입력 (default: 2~4=10%, 5~10=20%) | 직전 단계 anchor × (1±%) 가격에 LIMIT |
| N (마지막) | `last_stage_trigger_mode` (default 동일) | `last_stage_trigger_percent` (default 20%) | 사용자 입력값 (legacy: `LIQUIDATION_BUFFER` 옵션) |

- **2026-04-30 변경**: SHORT 마지막 단계 default 가 `LIQUIDATION_BUFFER` → `PRICE_UP_PCT` 로 변경.
- 단계 수: `StrategyTemplate.stages_config["capitals"]` 길이 (1~10), 또는 stage_plan row count.
- **추가 증거금** (`StrategyStagePlan.additional_margin_usdt`, **alembic 0014**, 2026-05-11): 단계 진입 LIMIT fill 후 자동 add_position_margin API 호출.

### 2.2 익절 정책 (TP1~TP10)

**Default qty ratios (template `tp{n}_qty_ratio` 가 우선, NULL 이면 fallback):**

| TP | default 잔량 비율 | 비고 |
|---|---|---|
| TP1 | 25% | |
| TP2 | 50% | |
| TP3 | 100% | (이전엔 TP3 만으로 종료 가능) |
| TP4 | 100% | |
| TP5 | 100% | |
| TP6~9 | 25% | (10단계 확장, 2026-05-06) |
| TP10 | 100% | |

**Default thresholds (template 의 tp{n}_percent 가 우선)**: TP1=10%, TP2=15%, TP3=20% (사용자 안내 기준).

**비즈니스 룰**:
- **마지막 활성 TP** (`last_active_tp` = template 의 NOT NULL TP 중 가장 큰 번호) 발동 시 사용자 ratio 무시 → **잔량 100% 청산 + COMPLETED** (2026-04-30 #80 사례 fix).
- **한 cycle 1단계만 발동** — ascending sort + `cur_done_idx` 보다 큰 첫 TP (TP skip 방지, #98 LABUSDT fix).
- **부분 청산 step_size floor**: `close_qty = (raw_qty // step) * step` (Bug #11, 2026-04-29).

### 2.3 트레일링 청산 (Trailing TP) — v4 (= v2 revert, 2026-05-12 저녁)

```python
TRAILING_TP_PEAK_THRESHOLD = Decimal("5")    # peak ≥ +5%
TRAILING_TP_RETRACE_AMOUNT = Decimal("5")    # 회귀 -5%
TRAILING_MIN_TP_INDEX = 3                    # TP3 부터 armed (v4 = v2 revert)
```

**4가지 발동 조건 (AND)**:
1. `status` ∈ {`TP3_DONE_PARTIAL`, `TP4_DONE_PARTIAL`, ..., `TP10_DONE_PARTIAL`, `TRAILING_ARMED`}
2. peak ≥ +5% (leveraged ROI)
3. 현재 pnl_ratio ≤ peak - 5%
4. 현재 pnl_ratio < peak

**발동 시**: `close_ratio = 1.00` → 잔량 100% 청산 → `status = COMPLETED` → Redis peak key 삭제.

**개정 이력**:
- v1 (2026-04-30): TP1+ armed
- v2 (2026-05-07, PR #20): TP3+ armed
- v3 (2026-05-12 새벽): TP4+ armed — 너무 보수적
- **v4 (2026-05-12 저녁): TP3+ armed (v3 → v2 revert)** — 사용자 본래 의도 「3단계 후」 회복

**Redis peak fallback** (#103 FHEUSDT fix): Redis 휘발 시 `strategy.max_profit_pct` 를 fallback 으로 사용.

### 2.4 손절 (SL)

```python
threshold = total_capital × 0.50 / leverage  # USD 손실 한도
is_stop = (realized + unrealized) ≤ -threshold  # ROI -50% (leveraged)
```

**가드**:
- `current_stage < total_stages` 면 발동 안 함 (모든 단계 진입 후만).
- 크라이시스 Stage 2 (`crisis_first_tp_done_at` 있음) 인 경우 -1% hard SL 우선 (`evaluate_stop_loss_crisis_aware`).

**발동 시**: 전량 emergency_close → `status = STOPPING` → stream FILL 수신 후 → `STOPPED` 또는 `REENTRY_READY` (template 정책).

### 2.5 크라이시스 복구 모드 (Phase D)

```python
CRISIS_MAX_LOSS_THRESHOLD = Decimal("-50")  # 진입 임계
CRISIS_TP1_THRESHOLD = Decimal("5")         # 첫 TP +5%
CRISIS_TRAILING_DROP = Decimal("5")         # 첫 TP 후 -5% 회귀
CRISIS_HARD_SL_THRESHOLD = Decimal("-1")    # 첫 TP 후 -1%
```

**진입 조건** (v2, 2026-05-07):
1. `crisis_mode_triggered_at IS NULL` (이미 진입 X)
2. `current_stage == total_stages` (모든 단계 진입 완료)
3. `max_loss_pct ≤ -50%` (충분히 깊은 손실)

**진입 후 흐름** (Stage 1):
- `+5%` 도달 → `CRISIS_TP1` (잔량의 25% 청산) + `crisis_first_tp_done_at` 시각 기록 + `peak_pnl_pct_after_first_tp` 초기화 → status `CRISIS_TP1_DONE`.

**Stage 2 (첫 TP 발동 후)**:
- `pnl ≤ -1%` → `CRISIS_HARD_SL` (잔량 전량 손절) → STOPPING → mark_reentry_ready.
- `peak ≥ +5% & pnl ≤ peak - 5%` → `CRISIS_TRAIL_FULL` (잔량 전량 청산) → COMPLETED.
- `pnl ≥ +10%` → 정상 TP2~5 룰 폴스루.

**TP 임계 override (크라이시스 모드 시)**: TP1=5%, TP2=10%, TP3=15%, TP4=20% (TP5+ 미사용).

**TP qty ratio 크라이시스 default** (`StrategyTemplate.crisis_qty_ratios` JSONB override 가능, alembic 0009): TP1=25%, TP2=25%, TP3=50% (잔량의), TP4=100% (잔량의).

### 2.6 PnL 추적 (alembic 0006)

- `max_loss_pct` (음수만 갱신, 더 깊은 손실로만)
- `max_profit_pct` (양수만 갱신, 더 큰 이익으로만)
- `realized_pnl` (TP/SL 체결 누계, 통계 합계의 단일 소스)
- `unrealized_pnl` (마지막 평가 시 미실현, 워커가 주기 갱신)
- 사용처: 크라이시스 진입 판정 (max_loss), trailing peak fallback (max_profit), 손실 임계 알림.

### 2.7 자동 재진입 (Auto Reentry, alembic 0007)

- `reentry_policy = "auto"` 인 template 만 적용 (default `manual_ready`).
- 조건: status=REENTRY_READY + `stopped_at + reentry_delay_seconds` 경과 (default 600s).
- 새 start_price = fapi 현재가 × (1 ± `reentry_offset_pct/100`) (default offset 1.0%).
- 실패 시 `REENTRY_FAILED` 마킹 + Sentry.

---

## 3. 안전성 정책

### 3.1 Kill-switch

| 측면 | 동작 |
|---|---|
| 차단 지점 (5곳) | `execution_service.start_stage1`, `trigger_next_stage`, `enter_stage_at_market`, `add_position_now` + `strategy_service` 신규 생성 |
| 자동 발동 | 일일 손실 한도 breach + 좀비 strategy 5회 escalate + Phase 2 orphan 감지 |
| 수동 enable | `POST /admin/kill-switch/{account_id}/enable` (소유 검증) |
| 수동 disable | `POST /admin/kill-switch/{account_id}/disable` + 오늘 daily_risk_limit row TRIGGERED→ACTIVE 리셋 |
| 알림 | edge detect (이전 disabled → enabled 일 때만) `send_kill_switch_alert` 1회 |

### 3.2 일일 손실 한도 (per account)

- `ExchangeAccount.daily_loss_limit_usdt` (NULL = global default, 양수 = override, 0/음수 = 비활성).
- `daily_loss_aggregator.py` 매 1분 평가 (lock 50s).
- breach 시: `AccountDailyRiskLimit` row 상태 ACTIVE→TRIGGERED + kill-switch 자동 발동 + 텔레그램.
- 임계치 도달 (kill-switch 직전) 시: `send_daily_loss_warning` 1회.

### 3.3 ISOLATED 마진 강제 (2026-05-06 사용자 결정)

- `ensure_isolated_margin(strategy)` **3개 진입점**에서 호출 (각 「신규 entry」 경로):
  - `start_stage1` (execution_service.py:73)
  - `enter_stage_at_market` (execution_service.py:395)
  - `add_position_now` (execution_service.py:463)
  - `trigger_next_stage` 는 호출 안 함 — 같은 strategy 의 stage 1 에서 이미 ensure 됨
- -4046 (이미 ISOLATED) idempotent — warning 없이 통과.
- -4048 (포지션 보유 중) — warning 만, 강제 진행.
- 실패 시: 거래는 진행되지만 「💰 증거금 추가」 만 작동 안 함 (CROSS 에선 add_position_margin 불가능, -4046).

### 3.4 Stream Idempotency (delta-based, #92 fix 2026-05-04)

- `delta_executed = new_executed_qty - prev_executed_qty`
- `delta ≤ 0` 면 ledger skip (status 만 갱신).
- PARTIAL→FILLED 흐름에서도 같은 trade 두 번 차감 방지.
- realized_pnl 누적: `delta × (exit - entry)` (LONG) 또는 `delta × (entry - exit)` (SHORT).

### 3.5 Emergency Close 안전장치 (#120 fix)

- Redis lock TTL 5s — 동시 다발 호출 차단 → `EmergencyCloseInProgress` raise → 다음 cycle 재시도.
- 거래소 실 포지션 0 이면 reduceOnly 발사 안 함 + cancel_all + STOPPED (Bug #8).
- 부분 청산 cap: `req_qty > actual_position` 일 때만 actual 로 줄임.
- status 선커밋 (#79 race): `STAGE_X_OPEN` 류 → `STOPPING`. `TP_DONE_PARTIAL`/`COMPLETED`/`REENTRY_READY`/`STOPPED` 는 보존.

### 3.6 Binance API Rate Limit Backoff (Layer 4, 2026-05-09)

- `parse_rate_limit_error(exc)` — 메시지에서 status=418/429, code=-1003, "too many requests", "banned" 감지.
- `banned until <ms>` 정규식 추출 → Redis 키 `api_backoff:account:{id}:ban_until_ms` 마킹 (TTL = 만료 + 5s).
- `check_api_ban()` — reconcile worker 가 사전 체크 → ban 중이면 cycle skip.
- 1회 Telegram 알림 (`api_backoff:account:{id}:notified` 키로 dedup).

### 3.7 Client Order ID 35자 cap (-4015 fix, 2026-05-12)

```python
MAX_LEN = 35              # Binance < 36
PREFERRED_UUID = 18       # 충분한 충돌 방지 (72bit)
MIN_UUID = 8              # 최소 (32bit)
base_len = len(symbol) + len(suffix) + 2
uuid_len = max(MIN_UUID, min(PREFERRED_UUID, MAX_LEN - base_len))
```

### 3.8 동시 동일 strategy 중복 차단

- 같은 (account, symbol, side) 의 활성 strategy 중복 생성 차단 토글 (system_setting `block_duplicate_strategy`, 2026-05-10).

### 3.9 화이트리스트 (mainnet/testnet 분리)

- `system_settings.whitelist_enabled` (DB 토글).
- `settings.allowed_symbols` (env, comma-separated).
- 둘 다 켜져있고 symbol 미등재면 strategy 생성 거부.

---

## 4. 데이터 모델

### 4.1 모델 14개

| 모델 | 테이블 | 핵심 책임 |
|---|---|---|
| `User` | `users` | 운영자 계정 (single admin) |
| `ExchangeAccount` | `exchange_accounts` | API 키 묶음 (Fernet 암호화) |
| `Symbol` | `symbols` | 거래 가능 심볼 메타 (Binance exchangeInfo 동기화) |
| `StrategyTemplate` | `strategy_templates` | 전략 청사진 (1~10단계 + TP1~10) — `stages_config` JSONB |
| `StrategyInstance` | `strategy_instances` | 운영 중 전략 1건 — status/PnL/크라이시스 모드 컬럼 |
| `StrategyStagePlan` | `strategy_stage_plans` | 단계별 계획 (UNIQUE strategy+stage_no) |
| `Order` | `orders` | 거래소 주문 1건 |
| `Position` | `positions` | 포지션 스냅샷 (싱크 워커 결과) |
| `RiskEvent` | `risk_events` | 위험 이벤트 로그 (strategy_id nullable — 시스템) |
| `Notification` | `notifications` | 텔레그램 발송 큐 + 기록 (dedup 60s) |
| `StreamSession` | `stream_sessions` | listenKey 세션 |
| `AccountKillSwitch` | `account_kill_switches` | 계정별 거래 차단 토글 |
| `AccountDailyRiskLimit` | `account_daily_risk_limits` | 일일 손실 한도 일자별 누계 |
| `SystemSetting` | `system_settings` | 운영자 런타임 토글 (key/value) |

### 4.2 마이그레이션 이력 (14건)

| # | revision | 날짜 | 변경 |
|---|---|---|---|
| 0001 | initial_schema | 2025-01-01 | 11개 테이블 일괄 생성 |
| 0002 | account_kill_switches | | KS 테이블 |
| 0003 | daily_risk_limits | | 일일 손실 누계 테이블 |
| 0004 | dynamic_stages | 2026-04-25 | `stages_config` JSONB — 1~10단계 동적 |
| 0005 | more_tp_levels | | TP4/TP5 추가 (nullable) |
| 0006 | pnl_tracking_crisis | | max_loss/profit_pct + crisis_* 5개 컬럼 |
| 0007 | auto_reentry | | reentry_delay/offset 추가 |
| 0008 | risk_events_sid_nullable | | listenKeyExpired FK 위반 fix |
| 0009 | template_crisis_qty_ratios | | 크라이시스 TP 비율 override |
| 0010 | ex_acc_daily_loss_limit | 2026-05-04 | 계정별 일일 한도 override |
| 0011 | strategy_archived | 2026-05-06 | soft delete (#96 fix) |
| 0012 | template_tp6_to_tp10 | 2026-05-06 | TP6~10 nullable |
| 0013 | system_settings | 2026-05-07 | 운영자 토글 테이블 |
| 0014 | stage_addmargin | 2026-05-11 | 단계별 추가 증거금 |

### 4.3 핵심 비즈니스 컬럼 정의

**`StrategyInstance.status` (string, enum 미정의)**:
- 진입 전: `WAITING`
- 진행 중: `STAGE{1..10}_OPEN_PENDING` / `STAGE{1..10}_OPEN`
- TP 부분 체결: `TP{1..10}_DONE_PARTIAL`
- 종료: `STOPPING`, `STOPPED`, `COMPLETED`, `CLOSED`, `REENTRY_READY`
- 크라이시스: `CRISIS_TP1_DONE`
- UI 전용 표시: `TRAILING_ARMED`, `LIQUIDATION_IMMINENT`, `KILL_SWITCH_TRIGGERED`

**TERMINAL_STATUSES (UI 「종료 숨김」 토글 기준)**: `STOPPED, STOPPING, COMPLETED, CLOSED, CLOSED_BY_SL, CLOSED_BY_TP, REENTRY_READY, KILL_SWITCH_TRIGGERED`.

**단계 산출**:
- `current_stage` (Integer, default 0) — 0=미진입, N=N단계 체결.
- `total_stages` 컬럼 없음 — `stages_config["capitals"]` 길이 또는 `StrategyStagePlan` row count 로 산출.

---

## 5. 서비스 계층

### 5.1 RiskService (`app/services/risk_service.py`)

**책임**: TP/SL 평가, trailing armed 판정, crisis mode 진입/Stage 2 평가, peak PnL 추적, 손실 임계 알림.

**주요 메서드**: `evaluate_stop_loss`, `evaluate_take_profit_level`, `_update_pnl_extremes`, `_should_trigger_crisis_mode`, `_enter_crisis_mode`, `_eval_crisis_mode_tp_sl`, `_update_peak_pnl`, `reset_peak_pnl`, `_maybe_send_loss_threshold_alert`, `evaluate_stop_loss_crisis_aware`, `compute_short_stage4_trigger_price`, `mark_reentry_ready`.

**정책 상수** (값은 §2 참조).

### 5.2 TPSLOrchestratorService (`app/services/tp_sl_orchestrator.py`)

**책임**: TP/SL 워커 진입점. RiskService 평가 결과 → ExecutionService 청산 발사 → status 전이 + 알림.

**주요 메서드**: `run_for_strategy(id)` (Redis lock TTL 20s 하), `_execute_take_profit`, `_execute_stop_loss`, `_execute_crisis_action`, `_resolve_crisis_qty_ratios`.

**상태 전이 표**:
| 발동 level | close_ratio | new status |
|---|---|---|
| TP1~TP9 (활성 TP 중) | template ratio (default 25/50/100/...) | `TP{n}_DONE_PARTIAL` |
| 마지막 활성 TP | 100% | `COMPLETED` |
| TRAILING_TP | 100% | `COMPLETED` + reset peak |
| CRISIS_TP1 | 25% | `CRISIS_TP1_DONE` + crisis_first_tp_done_at |
| CRISIS_TRAIL_FULL | 100% | `COMPLETED` + reset peak |
| CRISIS_HARD_SL | 100% | `STOPPING` → mark_reentry_ready |

### 5.3 ExecutionService (`app/services/execution_service.py`)

**책임**: 거래소 주문 발사 (entry/exit/margin), kill-switch 차단 검사, isolated margin 강제.

**주요 메서드**: `apply_leverage`, `ensure_isolated_margin`, `start_stage1`, `trigger_next_stage`, `enter_stage_at_market`, `add_position_now`, `add_position_margin`, `emergency_close_position` (Redis lock TTL 5s), `_place_stage_entry_order`, `_place_market_entry`, `_place_limit_entry`, `_new_client_order_id` (35자 cap).

### 5.4 StrategyCalculator (`app/services/strategy_calculator.py`)

**책임**: 단계별 자본/수량 계산, trigger price 산출, 미리보기 응답 생성.

**주요 메서드**: `calculate_preview`, `compute_short_last_stage_trigger_from_liquidation`, `compute_tp_prices`, `compute_qty_from_capital`, `_normalize_stages_config`.

**상수**: `DEFAULT_EARLY_TRIGGER_PCT=10`, `DEFAULT_LATE_TRIGGER_PCT=20`, `EARLY_STAGE_THRESHOLD=4`, `MAX_STAGES=10`, `MIN_STAGES=1`.

### 5.5 StreamService (`app/services/stream_service.py`)

**책임**: Binance UserData stream 이벤트 처리 — Order status/qty 갱신, Position snapshot, strategy.status 전이, realized_pnl 누적.

**주요 메서드**: `handle_order_trade_update`, `handle_account_update`, `_fetch_actual_position_qty` (#120 defensive), `handle_listen_key_expired`.

### 5.6 NotificationService (`app/services/notification_service.py`)

**책임**: Telegram + DB 발송 (15종 메서드 — §11 참조). dedup 60s.

---

## 6. REST API (52 endpoints, prefix `/api/v1`)

| 라우터 | endpoint 수 | 핵심 |
|---|---|---|
| `/auth` | 2 | login (JSON), token (form-data) |
| `/strategies` | 17 | preview-inline, calculate, CRUD, start/stop/restore/timeline/stage-plans/blueprint, settings (in-place), trigger-next-stage, add-margin, add-position, force-stop |
| `/orders` | 2 | 본인 모든 주문 + by-strategy (PnL/ROI 자동 계산) |
| `/positions` | 1 | latest snapshot |
| `/events` | 1 | by-strategy + severity 필터 |
| `/admin` | 19 | templates CRUD, CSV export, system-health, **stats**, **stats/breakdown**, **recent-activity**, **notifications-by-title**, kill-switch enable/disable, whitelist 토글, symbol-sync, test-telegram, system-status, health-dashboard |
| `/exchange-accounts` | 5 | CRUD + credentials 회전 + 일일 한도 + balance |
| `/symbols` | 4 | list, whitelist-info, ranking (24h/주/월), 단일 (add_api_route) |
| `/market` | 3 | ticker, ticker24h, klines (public 프록시) |

### 6.1 핵심 endpoint 응답 명세

**`GET /admin/stats`**:
```
{
  total, active, completed (익절 알림 누계),
  stop_loss (손절 알림), manual_stop (STOPPED+STOPPING),
  win_rate_pct (strategy 단위), win_rate_alert_based_pct,
  profit_strategy_count, loss_strategy_count, decided_strategy_count,
  realized_pnl_total, crisis_total, crisis_active,
  avg_max_loss_pct, avg_max_profit_pct,
  status_breakdown,
  tp_breakdown: { TP1..TP10: count, TRAILING_TP: count }  // 2026-05-12 확장
}
```

**`GET /admin/stats/breakdown?view=...`**:
- `strategies` (default): 모든 strategy
- `realized`: realized_pnl ≠ 0
- `losses` (감사): realized_pnl<0 OR max_loss_pct<-10 OR status IN (STOPPED, STOPPING) OR crisis_mode_triggered_at IS NOT NULL — **2026-05-12 확장 (수동정지 포함)**

**`GET /admin/recent-activity?limit=N`**: 1~1000건 (default 20). orders + risk_events + notifications 통합. **「매도/매수」 → 「SHORT/LONG 포지션 진입/청산」** 한국어화 (2026-05-12).

**`GET /admin/notifications-by-title?title_like=...&limit=200`**: 제목 LIKE 매칭 알림 목록 (운영통계 TP/TRAIL 셀 클릭용, 2026-05-12 신규).

**`GET /strategies/{id}/blueprint`**: 이전 전략 모든 설정 반환 — `capitals[], trigger_percents[], additional_margins[], last_stage_trigger_*, tp1~10_*, sl, start_price`.

---

## 7. UI 화면

### 7.1 페이지 구조 (3 페이지, hash 라우팅)

```
#dashboard (default)  — 대시보드
#ranking              — 시장 순위 (USDT/USDC Perpetual 변동률)
#health               — 운영 점검 (1h/6h/24h/3d/7d 거래 요약)
```

### 7.2 「+ 새 전략」 모달 (3 모드)

```
1️⃣ 거래소 계정 (radio)
2️⃣ 심볼 (datalist + 화이트리스트 검증) + 방향 toggle
⚖️ 레버리지 (default: SHORT 2x / LONG 1x)
3️⃣ 전략 구성 — 3 모드:
    📝 직접 입력 — 단계별 grid (12-col):
        단계(1) | 자본(1) | 트리%(1) | 증거금(1) | 단계 진입가(2) | 평균(2) | 청산가(1) | 손실율(1) | 손실$(2)
        + 라이브 계산 (입력 즉시 갱신)
        + ⚙️ 익절/손절: TP1~3 필수 + TP4~10 선택 + SL%
    📋 템플릿 선택
    📂 이전 전략 불러오기 — blueprint API → 모든 필드 자동 채움
        (마지막 단계 trigger% 는 last_stage_trigger_percent fallback, 2026-05-12 fix)
시세 정보 + 시작가 자동 (현재가 / -0.1% / +0.1%)
4️⃣ 시작가 + 미리보기 → 미리보기 테이블 (8 컬럼: 단계/조건/트리거가/투입자본/💰증거금/수량/평균진입/예상청산가)
🚀 전략 시작
```

### 7.3 운영 통계 패널 (전체 누적)

**상단 6 셀** (3×2, 모두 클릭 가능):
- 전략 수 🔍 → strategies 모달
- 익절 알림 🔍 → realized 모달
- 손절/수동 🔍 → losses 모달
- 승률 (전략) 🔍 → strategies 모달 (수익/손실 카운트 표시)
- 확정 손익 🔍 → realized 모달
- 크라이시스 🔍 → losses 모달

**하단 11 셀** (TP1~10 + TRAIL, 2026-05-12 클릭 활성):
- 각 TP 셀 클릭 → 「📜 알림 상세」 모달 (`notifications-by-title?title_like=%[TPx 익절%`)

### 7.4 활동 피드 (페이지네이션, 2026-05-12)

- 「📡 최근 활동 (최신순 N건)」 — N = select dropdown (20/50/100/200/500, default 50).
- 「🔄」 버튼 + 갱신 시각 표시.
- max-height 480px, overflow-y auto.
- 표시: 타임스탬프 / 아이콘 / 전략 링크 (#ID 클릭 → selectStrategy) / kind 컬러 (ORDER 파랑 / RISK 빨강 / NOTIFY 회색) / title / detail (200자 truncate).
- **용어 변경 (2026-05-12)**: 「매도 📉」 → 「📉 SHORT 포지션 진입/청산」.

### 7.5 선택 전략 상세 패널 (`#detail-section`)

- 📈 차트 — 캔들 + BB + 단계별 진입가 + 청산가 가로선, 1h/4h/1d toggle, RSI/MACD/OBV 보조지표.
- 📜 활동 타임라인 — `/strategies/{id}/timeline?limit=100`.
- 📋 단계별 계획 — 7 컬럼 + **헤더에 「— #ID SYMBOL 📉SIDE」 동적 표시 (2026-05-12)**.
- 📦 주문 내역 — 11 컬럼 (#/단계/유형/방향/주문타입/가격/수량/체결/상태/손익/ROI%) + 동일 헤더 표시.

### 7.6 모달 카탈로그 (동적 생성)

- `#stats-breakdown-modal` — 운영 통계 상세 (3 view 탭)
- `#tp-notif-modal` — TP/TRAIL 알림 상세 (2026-05-12 신규)
- `#accounts-modal` — 거래소 계정 + 일일 한도 인라인 수정
- `#ap-modal` — 💉 포지션 추가 (ad-hoc 진입)
- `#create-modal` — 새 전략 (위 7.2)
- `openTradeHistoryModal()`, `openSymbolRankingModal()` — 동적 생성

### 7.7 클릭 가능 표시 (2026-05-12)

```css
[onclick] { cursor: pointer; }
[onclick]:not(button):not(.row-clickable):hover { filter: brightness(1.15); }
div.row-clickable:hover { background: rgba(59,130,246,0.10); transform: translateY(-1px); }
```

---

## 8. 워커 + 스케줄러

### 8.1 9개 scheduled jobs (APScheduler `BlockingScheduler` Asia/Seoul)

| Job | 트리거 | Lock TTL | 책임 |
|---|---|---|---|
| `listenkey_keepalive` | 매 30분 | 120s | Binance `PUT /listenKey` 갱신 |
| `position_reconcile` | 매 2분 | 110s | 거래소-DB 정합성 + 자가회복 + orphan kill-switch (2026-05-09 1m→2m, rate limit 80% 감소) |
| `tp_sl` | 매 10초 | 8s | TPSLOrchestrator 호출 (2026-05-06 lock 20s→8s, #103 fix) |
| `symbol_sync_daily` | KST 매일 12:00 | 3600s | exchangeInfo 갱신 |
| `auto_reentry` | 매 30초 | 25s | REENTRY_READY + auto policy + delay 경과 시 재진입 |
| `stage_trigger` | 매 10초 | 8s | 다음 단계 LIMIT 발사 + additional_margin 자동 투입 |
| `daily_loss_check` | 매 1분 | 50s | 일일 손실 한도 평가 + breach 시 kill-switch |
| `heartbeat` | settings.heartbeat_interval_hours (default 6h) | 60s | 활성 strategy/KS/CRITICAL/알림 요약 텔레그램 |
| `daily_report` | UTC 00:00 (KST 09:00) | 300s | 직전 24h 리포트 |

### 8.2 분산 스케줄러 + Leader Election

- `DistributedSchedulerGuard`:
  - `node_id = f"{hostname}-{timestamp}"`.
  - `try_become_leader()`: `SET sched:leader <id> NX EX 30` → 첫 노드만 leader.
  - 매 job 호출 직전 `refresh_leader()` (TTL 갱신 또는 skip).
  - `acquire_job_lock(name, ttl)`: `SET sched:job:<name> <id> NX EX <ttl>`.
- `_scheduler_heartbeat_loop` daemon thread: 30s 마다 `health:scheduler:leader` 키 60s TTL 갱신 → Prometheus `scheduler_leader_status` gauge.

### 8.3 Reconcile 자가회복 매트릭스

| 거래소 매칭 | strategy.status | 동작 |
|---|---|---|
| None | STOPPING | → STOPPED qty=0, RiskEvent INFO `RECONCILE_STOPPING_ZOMBIE_CLEANUP`, metric `zombie_stopped` |
| None | STAGE_OPEN/TP_DONE_PARTIAL | → STOPPED, RiskEvent WARN `RECONCILE_AUTO_STOP_ORPHAN`, metric `orphan_stopped` |
| None | *_PENDING 등 | stuck inc, ≥5 면 `escalate("PENDING_STUCK_NO_EXCHANGE_POSITION")` → kill-switch |
| 있음 | qty 일치 | Position 기록, avg/qty/PnL/liq 갱신, stuck clear |
| 있음 | qty 불일치 | sync + `position_qty_mismatch_total` inc, ≥5 면 escalate |
| 있음 + STAGE_PENDING + is_triggered | — | → STAGE_OPEN 자가회복 (stream 누락 보호) |

---

## 9. 컨테이너 인프라 (docker-compose.yml, 8 services)

| 컨테이너 | 이미지 | 포트 | 책임 |
|---|---|---|---|
| `db` | postgres:16 | 127.0.0.1:5433 | (Neon 사용 시 dev only) |
| `redis` | redis:7 | 6380 | lock + cache |
| `api` | build:. (uvicorn) | 8000 | FastAPI |
| `scheduler` | build:. | — | APScheduler |
| `user-stream` | build:. | — | Binance WebSocket |
| `prometheus` | prom/prometheus | 9090 | 메트릭 수집 |
| `grafana` | grafana/grafana | 127.0.0.1:3000 | 대시보드 |
| `db-backup` | prodrigestivill/postgres-backup-local:16 | — | 일일 백업 (KEEP_DAYS=7, WEEKS=4, MONTHS=6) |

- DB/Redis/Grafana 는 127.0.0.1 바인딩 (외부 차단).
- `restart: unless-stopped` 모든 서비스.
- `.env` 주입 (Fernet key, Binance API, Telegram 등).

---

## 10. 관측성

### 10.1 Prometheus 메트릭 (18개 = 13 Counter + 4 Gauge + 1 Histogram)

**Counter (13)**:
- `strategy_runs_total{side,status}`
- `strategy_stop_loss_total{symbol,side}`
- `strategy_take_profit_total{symbol,side,level}`
- `strategy_stage_trigger_total{symbol,side,stage_no}`
- `strategy_stage_order_fail_total{symbol,side,stage_no,reason_code}`
- `user_stream_events_total{event_type}`
- `user_stream_reconnect_total`
- `listen_key_keepalive_total{status}`
- `position_reconcile_total{status}` (success/miss/error/zombie_stopped/orphan_stopped)
- `position_qty_mismatch_total{symbol,side}`
- `kill_switch_trigger_total{exchange_account_id,reason_code}`
- `binance_algo_order_total{order_type,status}`
- `binance_api_requests_total{endpoint,method,status}`

**Gauge (4)**: `kill_switch_enabled`, `strategy_active_positions`, `user_stream_connected`, `scheduler_leader_status`.

**Histogram (1)**: `binance_api_request_latency_seconds`.

### 10.2 헬스 신호 키 (Redis)

- `health:scheduler:leader` — 60s TTL (스케줄러 daemon thread 가 갱신)
- `health:user_stream:connected` — 60s TTL (consumer + worker daemon thread 가 갱신)
- `api_backoff:account:{id}:ban_until_ms` — Binance ban 마킹

---

## 11. 알림 시스템 (Telegram-only)

### 11.1 기본 정책
- **채널**: `TELEGRAM` 만 실제 발송. 다른 channel 값은 DB 만 기록 (`local-only`).
- **Dedup**: 60s 내 동일 (strategy_id, title) SENT/PENDING 있으면 차단.
- **Format**: 한국어 + 이모지 + 천단위 콤마 + plain text (parse_mode 미사용, 4000자 cutoff).

### 11.2 15종 send_xxx 메서드

| 메서드 | Title prefix | 발송 시점 |
|---|---|---|
| `send_system_alert` | (자유) | 시스템 일반 |
| `send_margin_added_alert` | `🛡 [증거금 추가]` | 증거금 추가 후 |
| `send_position_added_alert` | `💉 [포지션 추가]` | ad-hoc 진입 |
| `send_loss_threshold_alert` | `⚠️ [손실 -50% 도달]` | -50% ROI 첫 교차 1회 (단계 컨텍스트 포함, 2026-05-08) |
| `send_strategy_started_alert` | `📈/📉 [전략 시작]` | 1단계 LIMIT 발송 직후 |
| `send_stage_entered_alert` | `📈/📉 [N단계 진입]` | 단계 LIMIT FILLED |
| `send_take_profit_alert` | `✅ [{level} 익절 체결]` | TP1~10 / TRAILING_TP 체결 |
| `send_stop_loss_alert` | `🛑 [손절 발동]` | SL 발동 (-50%) |
| `send_kill_switch_alert` | `⚠️🔴 [Kill-Switch 발동]` | KS 활성 (edge detect) |
| `send_daily_loss_warning` | `⚠️ [일일 손실 한도 임계치 도달]` | KS 직전 |
| `send_liquidation_warning` | `🚨 [청산 임박]` | 마지막 단계 trigger 곧 발동 |
| `send_crisis_mode_entered` | `🚨 [크라이시스 모드 진입]` | 크라이시스 활성화 |
| `send_crisis_first_tp` | `⚡ [크라이시스 첫 TP +5%]` | +5% 체결 (25%) |
| `send_crisis_trailing_full` | `🛡 [크라이시스 트레일링 청산]` | 첫 TP 후 -5% 회귀 |
| `send_crisis_hard_sl` | `🚨 [크라이시스 빠른 손절 -1%]` | 첫 TP 후 -1% |

---

## 12. 거래소 통합 (Binance Futures USDⓢ-M)

### 12.1 사용 endpoints

**Public**: `/exchangeInfo`, `/time`, `/ping`, `/klines`, `/ticker/24hr`.

**Account/Position (signed)**: `/account`, `/balance`, `/positionRisk`, `/leverage`, `/marginType`, `/positionSide/dual` (hedge mode), **`/positionMargin`** (2026-05-06 fix: `/modify` suffix 제거).

**Orders (signed)**: `/order` (POST/GET/DELETE), `/allOpenOrders` (DELETE), `/openOrders` (GET).

**User data stream**: `/listenKey` POST/PUT/DELETE.

### 12.2 Signing
- HMAC-SHA256(api_secret, query_string) → hex digest.
- `timestamp` (ms) + `recvWindow=30000ms` 자동 주입 (Docker on Windows VM 시계 드리프트 대응).
- `X-MBX-APIKEY` 헤더, GET/DELETE 는 query, POST/PUT 은 form body.

### 12.3 Mainnet/Testnet 전환
- `ExchangeAccount.is_testnet` 플래그.
- `BinanceClient` 가 base URL 라우팅 (`https://fapi.binance.com` vs `https://testnet.binancefuture.com`).
- Credentials 회전: `PATCH /exchange-accounts/{id}/credentials` — 활성 strategy 가드 + 인증 검증 후 전환.

---

## 13. QA + 테스트

| 카테고리 | 파일 수 | 테스트 수 (추정) |
|---|---|---|
| `tests/unit/` | 22 | ~150 |
| `tests/integration/` | 45 | ~287 |
| **합계** | **67** | **437~ 함수, 527 테스트 케이스 (parametrize 포함)** |

**회귀 정책**: 모든 PR/배포 전 전체 통과 필수. 1개 known-flaky deselect (`test_reconcile_5plus_stages.py::test_stage_n_pending_recovers_to_open[9]`).

---

## 14. 운영 정책

### 14.1 배포
```bash
cd ~/binance-auto-trader/backend
git pull origin <branch>
docker compose restart api scheduler  # 코드 변경 영역에 따라
```
- **static 만 변경**: api 재기동 + 브라우저 Ctrl+Shift+R.
- **워커/orchestrator 변경**: scheduler 도 재기동.
- **migration 추가**: `docker compose exec api alembic upgrade head` 먼저.

### 14.2 백업 태그
- 형식: `backup/YYYY-MM-DD-<topic>` (예: `backup/2026-05-12-policy-stats-clientid`).
- 매 작업 세션 종료 시 생성 + GitHub push.

### 14.3 일일 자동 보고
- 매일 KST 09:00 텔레그램 발송 (`daily_report` job).
- 직전 24h: 거래활동/손익/RiskEvent severity·top3·자동권장조치.

### 14.4 Heartbeat
- `settings.heartbeat_interval_hours` (default 6h).
- 활성 strategy/KS/CRITICAL/알림 SENT/FAILED 요약.

### 14.5 DB 백업
- `db-backup` 컨테이너 매일 자동 (gzip -Z6).
- KEEP_DAYS=7, WEEKS=4, MONTHS=6.
- 마운트: `./db_backups`.

---

## 15. 개정 이력

| 버전 | 날짜 | 내용 |
|---|---|---|
| v1.0 | 2026-05-12 | 초안 — 전체 코드베이스 reverse-engineering, HEAD `89cbd1c` 기준 |

---

## 부록 A: 주요 외부 참조

- Binance Futures API: https://binance-docs.github.io/apidocs/futures/en/
- Telegram Bot API: https://core.telegram.org/bots/api
- 운영 VPS: 159.65.137.250 (DO SGP1)
- DB: Neon Cloud PostgreSQL (Singapore)
- Repo: https://github.com/herosys1-crypto/binance-auto-trader

## 부록 B: 코드 진입점 맵

| 영역 | 파일 |
|---|---|
| 비즈니스 룰 | `backend/app/services/risk_service.py`, `tp_sl_orchestrator.py`, `execution_service.py`, `strategy_calculator.py` |
| 거래소 통합 | `backend/app/integrations/binance/client.py`, `futures_trade.py`, `mapper.py` |
| 워커 | `backend/app/workers/scheduler_runner.py` (entrypoint) |
| API | `backend/app/api/v1/admin.py`, `strategies.py` (가장 큰 두 파일) |
| UI | `backend/app/static/index.html` (5,291 줄 SPA) |
| 모델 | `backend/app/models/*.py` |
| 마이그레이션 | `backend/alembic/versions/*.py` |
