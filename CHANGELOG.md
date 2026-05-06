# CHANGELOG — Binance Auto Trader

세션 단위로 변경 이력을 기록합니다.

---

## [2026-05-06] — 운영 정확화 + 사용자 요청 2건 + VPS 배포 패키지 (PR #5~#12, +13 commits)

### 🎯 의도
1차 핸드오프 → 사무실 PR #2 머지 → 집 추가 작업으로 운영 사례 (#103 trailing 미발동,
#96 cascade delete) 영구 방어 + 사용자 요청 2건 (TP10 익절 확장 + 24h/주/월 변동률
순위) + VPS 배포 패키지 (Neon Cloud 유지 + DigitalOcean Singapore + ngrok 폐지) +
SYSTEM-SPEC cross-check + MAINNET-CHECKLIST 신규 항목 통합.

### ✨ 신규 기능 (사용자 요청)
- **익절 5단계 → 10단계 확장** (`fa199ca`, alembic 0012). default 5% 간격
  (TP1=10/.../TP10=55%), 잔량 25% (TP10=100%). 마지막 활성 TP 자동 100% 청산.
  trailing -5% 회귀 그대로 (사용자 명시 — 변경 X).
- **24h/주/월 변동률 순위 검색** (`fe00fda`). 13 period (1d/2d~7d/1w/2w/1m/3m/6m/1y)
  × gainers/losers, Redis 캐시. 빠른 작업 + 새 전략 모달 통합.
- **시장 순위 별도 페이지** (`3ea79c6`, 사용자 요청 #2 의 「별도 페이지」 부분).
  헤더 nav + URL hash routing (#dashboard / #ranking). 「↑ 새 전략」 → 모달 자동 +
  심볼/시작가 자동 채움.

### 🔴 CRITICAL fix (운영 사례)
- **트레일링 peak DB fallback** (`0620805`, 사용자 #103 FHEUSDT). Redis 휘발 시
  `_update_peak_pnl` 가 현재 PnL 을 새 peak 로 reset → trailing 무력화. fix:
  `db_max_profit_pct` fallback 인자 추가 + `true_peak = max(current, redis, db)`.
  Redis 자가 회복.
- **Soft delete (DELETE → archive)** (`559ef95`, 사용자 #96 TSTUSDT). cascade
  hard delete 로 +867 USDT realized_pnl 이 통계 합계에서 누락. fix: DELETE 가
  `is_archived=True` 마킹만 (alembic 0011). row + cascade orders 보존.
- **C-full archive UI 완성** (`cbd1968`). PR #7 후속 — 7 active query 에
  `WHERE NOT is_archived` filter (repository / 5 worker / strategy_service /
  zombie_guardian) + `POST /strategies/{id}/restore` endpoint + UI 「📦 보관 보기」
  토글 + 「↻ 복원」 버튼. archived strategy 가 background process 에서 자동 제외.

### 🟡 운영 정확화 / UX
- **승률 strategy 단위** (`5adb538`). 알림 기반 (이전) → realized_pnl 부호 기반.
  실제 88.46% 였던 게 100% 잘못 표시되던 사용자 보고 fix.
- **운영 통계 셀 클릭 → modal** (`aaaada2`). 6 셀 모두 「🔍」 + 신규 endpoint
  `GET /admin/stats/breakdown?view=` (3 view: strategies/realized/losses).
- **자동번역 차단** (`aaaada2`). `<html translate="no">` + meta google notranslate.
  「확정 손익」 → 「안녕 손익」 같은 Chrome 번역 부작용 영구 해소.
- **「확정 손익 (Realized)」 라벨** (`98f5dbb`). 「실현손익」 자동번역 회피.
- **tiny price 시작가** (`98f5dbb`). tick_size scientific notation (1e-8) 처리.
  사용자 보고 — 가격 0.00006304 심볼에서 「현재가」 클릭 시 input 빈칸 됐던 fix.

### 🛡️ VPS 배포 패키지 (mainnet 직전, 사용자 결정)
- **사용자 결정**: Neon Cloud 유료 plan 유지 (이미 결제) + DigitalOcean Singapore
  VPS 신규 + ngrok 폐지.
- `deploy/vps-bootstrap.sh` (`0aa85c7`) — Phase 1 자동화 (Ubuntu 24.04 root 1회):
  ufw / fail2ban / unattended-upgrades / swap 4GB / Docker / log rotation 등.
- `deploy/generate-secrets.sh` — SECRET_KEY/ENCRYPTION_KEY/POSTGRES/REDIS 자동 생성
  + 외부 자격증명 가이드.
- `VPS-DEPLOY-CHECKLIST.md` — 단계별 (Phase 0~5).
- `backend/.env.production.template` (`55276e1`) — DAILY_LOSS_LIMIT_USDT 등 5-04
  신규 변수 추가 + .gitignore exception (`!backend/.env.production.template`).

### 📚 문서 보강
- **SYSTEM-SPEC** (`8f3436c`) — 5-06 cross-check 결과 (9 영역 + 회귀 inventory) +
  본문 fix (TP1~10, peak fallback, status 표 STAGE1~10/TP1~10/ARCHIVED) + 14절
  체크리스트 5-06 신규 5항목 + 「📜 리비전 노트」 5-06 절.
- **HANDOFF-2026-05-06-HOME-TO-OFFICE.md** (`2266225` → `e8afec7`) — 1차 (7 PR)
  → 최종 (13 commits, VPS + ranking page + C-full + SPEC 통합) 갱신.
- **MAINNET-CHECKLIST** (`24ce791`) — 5-04 9항목 + 5-06 10항목 신규 통합. pytest
  카운트 60+ → 383 passed. 24/7 운영 = DigitalOcean Singapore + ngrok 폐지 명시.

### 🧪 테스트 (329 → 383, +54 신규)
- **신규 6 파일** (모두 sqlite 호환 통합/단위 테스트):
  - `test_admin_stats_winrate.py` (6) — 승률 strategy 단위
  - `test_admin_stats_breakdown.py` (6) — breakdown endpoint
  - `test_strategy_soft_delete.py` (7) — archive 동작
  - `test_peak_pnl_redis_fallback.py` (7) — peak DB fallback (#103 회귀 가드)
  - `test_tp10_stages.py` (18) — TP1~10 확장 + 모델 컬럼 검증
  - `test_symbol_ranking_route_order.py` (4) — `/ranking` route 등록 순서
  - `test_archive_active_filter_and_restore.py` (6) — C-full filter + restore
- 기존 4 파일 update — `test_strategies_endpoint_terminal_handling.py` (PR #7 archive
  동작 일치).

### 🚦 운영 사용 예시
```bash
# 시장 순위 — 24h 상승 top 30 (cache 미사용 첫 호출)
curl https://api/symbols/ranking?period=1d&direction=gainers&limit=30
# 1주 하락 top — top 50 거래대금 심볼만 정확 계산 (cache TTL 5m)
curl https://api/symbols/ranking?period=1w&direction=losers&limit=20

# soft delete + restore
curl -X DELETE https://api/strategies/123          # archive
curl -X POST https://api/strategies/123/restore    # 되돌림

# 운영 통계 detail
curl https://api/admin/stats/breakdown?view=losses # 손실 strategy 만
```

### 🔖 Reviewer notes
- 5-06 변경 모두 backward-compat (alembic 0011/0012 additive only, 기존 strategy
  TP6~10 NULL → 5단계 동작 그대로).
- archived 도 통계 합계 (`/admin/stats` 의 `realized_pnl_total`) 에 포함 — 거래소
  history 일치 유지 (#96 사례 영구 방어 의도).
- ranking endpoint 의 1d 외 기간은 24h 거래대금 top 50 만 정확 계산 (Binance API
  호출 수 제한). cache TTL 은 period 별 적절히 조정 (1d=60s, 1y=4h).
- VPS 셋업은 사용자 직접 작업 — DigitalOcean 계정 + SSH 키 + 도메인 + 외부 자격증명
  발급이 사전 결정 사항. 자동화는 Phase 1 (OS hardening + Docker) 까지.

---

## [2026-05-04] — Option B + C 회귀/관측성 강화 (PR #1)

### 🎯 의도
mainnet 직전 시점에 (1) 좀비 6패턴 fix 의 회귀 방어를 만들고 (2) 운영 가시성을
높이고 (3) 전략 튜닝 유연성을 추가. 코드 동작 변경 없는 보강 위주 (default 보존).

### ✨ 신규
- **`crisis_qty_ratios` JSONB 컬럼** (`alembic 0009`) — 전략별 크라이시스 모드 TP qty
  override. NULL 또는 일부 키만 채워도 안전 fallback (default 25/25/50/100 보존).
- **`_resolve_crisis_qty_ratios` 헬퍼** + `_CRISIS_QTY_RATIO_DEFAULT` 상수 — invalid
  값/범위 밖/비숫자/non-dict 모두 default 폴백.
- **`capture_strategy_event` 헬퍼** (`app/core/sentry.py`) — sentry-sdk 2.x `new_scope`,
  DSN 미설정 시 no-op. tag (strategy_id/symbol/side/account_id/event_type) 로
  Sentry 알림 필터링 가능.
- **integration test 스캐폴드** (`backend/tests/integration/`) — sqlite in-memory +
  JSONB→JSON compiles directive + factory fixtures + FakeBinanceClient/FakeTradeClient/
  FakeRedis. postgres 없이도 종단간 시나리오 실행 가능.

### 🔧 코드 변경
- `services/tp_sl_orchestrator.py` — `crisis_qty_ratio` 가 hardcoded → template override.
- `services/execution_service.py` — `emergency_close_position` place_market_order 실패
  시 Sentry capture (level=error).
- `services/zombie_guardian.py` — `escalate_stuck_strategy` (level=fatal) +
  `detect_orphan_exchange_positions` (level=fatal) Sentry capture.
- `workers/binance_user_stream_consumer.py` — reconnect crash + WS error capture
  (5회 미만은 warning, 이상은 error).
- `workers/reconcile_worker.py` — Phase 1 (pre_pass_dedup, enforce_terminal_qty_zero,
  detect_orphan_exchange_positions) 실패 + per-strategy 실패 capture.

### 🧪 테스트 (110 passed, 0 warnings)
**Unit (99)** — 기존 70 + 신규 29:
- `test_zombie_guardian.py` (16) — Phase 1 자동 회복 + escalation 안전망
- `test_crisis_qty_ratios_resolver.py` (13) — JSONB override 머지 + invalid fallback

**Integration (11) — 신규 카테고리:**
- `test_reconcile_zombie_cleanup.py` (5) — STOPPING 좀비 / orphan / 정상 sync /
  PENDING 자가 회복 / terminal qty 잔재
- `test_reconcile_orphan_position.py` (4) — orphan + Kill-Switch / matched 정상 /
  amt=0 무시 / STOPPED + 거래소 포지션
- `test_reconcile_duplicate_active.py` (2) — 중복 active dedup / 다른 account 격리
- `test_tp_sl_orchestrator_lifecycle.py` (5) — TP1 부분 청산 종단간 / 임계 미달 /
  마지막 활성 TP COMPLETED / 낮은 TP refire 방지 / Redis lock skip

### 📚 문서
- `AUDIT-FINDINGS.md` — A01~A17 상태 모두 ✅/DEFERRED 표기 + 신규 row 2개
  (zombie_guardian tests, sentry observability).
- `CHANGELOG.md` — 이 항목 추가.

### 🚦 운영 사용 예시
```sql
-- 보수적 회복 (TP1 에서 더 많이 청산)
UPDATE strategy_templates SET crisis_qty_ratios = '{"TP1":40,"TP2":30,"TP3":30}'
WHERE name = 'aggressive_recovery';
```
production 에서 `SENTRY_DSN` env 만 설정하면 알림 자동 활성. 알림은
`strategy_id` / `symbol` / `side` / `event_type` / `is_testnet` tag 로 필터링.

### 🔖 Reviewer notes
- reconcile_worker 의 STOPPING 자동정리는 **matched=None 경로**에만 1사이클로 발동.
  Binance hedge mode 가 `amt=0` placeholder 를 보내는 케이스는 **5사이클 stuck
  escalation** 으로 처리됨 (별도 코드 경로) — integration test 가 두 경로의 차이를 명시.
- A14/A15/A16 은 audit 자체가 deferred 권장 (변경 가치 낮음), mainnet 후 재검토.

---

## [2026-05-04] (보강) — 운영 사례 fix + UX 보강 + 안전망 강화 (PR #1, +18 commits)

위 5-04 항목이 Option B+C 회귀/관측성 (전반부 8 commits) 만 다뤘다면, 이 항목은
같은 날 후반부에 운영 사례 (#96/#98) fix 와 신규 사용자 요청 기능 18개 commit 을 정리.

### 🔴 CRITICAL — 사용자 #98 (LABUSDT 트레일링 미발동)
- **`fix(risk_service)` 트레일링 TP 가 TP loop 뒤에 있어 무력화** (`534c690`)
  - 증상: 피크 +30% 후 -10% 회귀했는데 잔량 청산 안 되어 +193 USDT 미실현 미잠금.
  - 원인: `evaluate_take_profit_level` 에서 TP loop 가 먼저 평가 → trailing 까지 도달 X.
  - Fix: trailing 체크를 TP loop **이전** + `TRAILING_ARMED_STATUSES` 에 모든
    `TP{N}_DONE_PARTIAL/TP{N}_DONE` 포함.
  - 회귀 방어: `test_trailing_tp_priority.py` 5건.
- **`fix(risk_service)` TP 중간 단계 silent skip** (`5bbda50`)
  - 증상: TP1 부분 청산 후 가격이 TP3 까지 점프 시 TP2 한 번도 발동 안 되고 건너뜀.
  - 원인: TP loop 가 descending 정렬로 가장 높은 임계 일치하는 라벨만 발동.
  - Fix: ascending sort + `TP_DONE_INDEX[status]` 비교로 한 단계씩만 발동.
  - 회귀 방어: `test_tp_intermediate_skip.py` 5건.

### 🔴 CRITICAL — 사용자 #96 (TSTUSDT 다단계 수동 진입)
- **`fix(reconcile)` PENDING→OPEN 자동 승격이 stage_plan 검증 없이 발동** (`787709c`)
  - 증상: STAGE4_OPEN_PENDING + 거래소 (이전 stages 합) → reconcile 가 promote → 잘못된 status.
  - 원인: `_PENDING_TO_OPEN` 가 `exchange_position_amt != 0` 만 보고 promote.
  - Fix: promote 전에 해당 stage 의 `StrategyStagePlan.is_triggered=True` 검증.
    `is_triggered` 는 stream_service 가 FILLED 시점에 atomic UPDATE 하는 ground truth.
  - 회귀 방어: `test_reconcile_zombie_cleanup.py::test_pending_NOT_promoted_when_stage_plan_not_triggered` +
    `test_reconcile_5plus_stages.py` parametrized 5~10단계.
- **`fix(api)` trigger_next_stage_manually NEW LIMIT 중복 차단** (`f9bbe16`)
  - 증상: 「▶ 다음 단계」 중복 클릭 → 같은 stage 의 LIMIT 이 거래소에 다중 발송 →
    가격 도달 시 동시 체결 → 포지션 더블링.
  - 원인: `is_triggered` 는 FILLED 시점에만 True, NEW 상태에선 False → plan 검증으론
    중복 차단 불가능.
  - Fix: `Order.stage_no == next_stage_no AND Order.status == 'NEW' AND purpose='ENTRY'`
    중복 가드. 메시지에 Order id/qty/price 포함.
  - 회귀 방어: `test_trigger_next_stage_and_inplace_stages.py::test_existing_pending_limit_blocks_duplicate`.

### ✨ 신규 기능 (사용자 요청)
- **「↻ 설정만 수정」 in-place** (`3c57bb2` + `3d96d89`)
  - 포지션/단계 보존. TP/SL/trigger_percents 만 갱신 → 새 strategy_template 생성 후
    `strategy.strategy_template_id` 교체. 미발동 stage 의 `StrategyStagePlan.trigger_price`
    재계산. 이미 진입한 stage 의 trigger_percent 변경 시도는 400.
  - API: `PATCH /strategies/{id}/settings` 가 `tp1~5_percent / sl_percent /
    trailing_tp_*  / trigger_percents` 모두 받음.
- **「▶ 다음 단계」 수동 진입** (`3d96d89`)
  - `POST /strategies/{id}/trigger-next-stage` — 옵션 A 유지 (사용자 입력 trigger_price
    위치에 LIMIT 발송, 시장가 즉시 진입 X).
  - 거부 케이스: terminal status / 다른 user / 모든 단계 진입 완료 / plan 없음 / NEW LIMIT 중복.
- **「💰 증거금 추가」** (`d88f41d`)
  - `POST /strategies/{id}/add-margin` — 포지션 변경 없이 isolated margin 만 증가.
  - margin call 회피용. UI 에서 수량/마진 컬럼에 노출.
- **-50% ROI 손실 임계 알림** (`d88f41d`)
  - `_maybe_send_loss_threshold_alert` 가 `prev_max_loss > -50 AND new_max_loss <= -50`
    one-time crossing 검출 → 텔레그램 + 푸시.
- **일일 손실 한도 v3** — 계정별 override (`016b678` → `9c0ef1f` → `4ca52d8` → `9611304`)
  - `daily_loss_aggregator` worker (1분 주기) 가 활성 strategy 의
    `unrealized + 일일 누적 realized` 합 → 한도 초과 시 자동 STOPPING + Kill Switch.
  - `exchange_accounts.daily_loss_limit_usdt` (alembic 0010) — 계정별 override.
  - UI 「💼 계정」 모달에서 관리.
- **Kill Switch 사각지대 fix** (`c79f3aa`) — stage 2+ 진입 + create 양쪽 모두 차단.
- **auto_reentry 실패 persist** (`12d47d5`) — REENTRY_FAILED status + Sentry capture + tz 방어.

### 🔧 UX 개선
- **STOPPING 가시성 + COMPLETED 「🔄 다시 시작」** (`8b521a3`)
- **PnL/ROI 셀 = Binance 일치** (`b40401f`) — 포지션 ROI + 전략 ROI 분리 표시.
- **COMPLETED/REENTRY_READY 종료 분류 누락 fix** (`89f779d` + `6de84a4`) —
  `app/core/strategy_status.py` 공통 frozenset.
- **옵션 C 5+ 단계 status 매핑 보강** (`b28c92f`) — 5 모듈 모두 `range(1, 11)` 동적.
- **모달 시세 로드 후 시작가 자동 채움** (`074619f`) — TAGUSDT 422 사용자 보고.
- **액션 버튼 컴팩트화** (`e5da3d7`) — 「▶」 icon-only + nowrap.

### 🛡️ Audit fixes
- `27bc852` — `get_first_active_binance` user 필터 + `RiskEventResponse` Optional schema.
- `10dd208` — idempotency 2xx-only 캐시 + ENCRYPTION_KEY startup 검증 + ExchangeAccount
  daily_limit API 노출.

### 🧪 테스트 (110 → 292, +182)
**신규 integration 카테고리 (15개 파일)** — `tests/integration/conftest.py` (sqlite +
JSONB→JSON + factory + FakeBinance/Trade/Redis), `test_reconcile_5plus_stages.py`,
`test_strategy_settings_inplace.py`, `test_trigger_next_stage_and_inplace_stages.py`,
`test_add_margin_and_loss_alert.py`, `test_daily_loss_aggregator.py`,
`test_daily_loss_per_account_limit.py`, `test_daily_loss_realized_accumulation.py`,
`test_exchange_accounts_daily_limit.py`, `test_kill_switch_coverage.py`,
`test_kill_switch_endpoint_ownership.py`, `test_auto_reentry_worker.py`,
`test_create_strategy_duplicate_prevention.py`, `test_audit_repos_schemas.py`,
`test_strategies_endpoint_terminal_handling.py`, `test_tp_intermediate_skip.py`,
`test_trailing_tp_priority.py`, `test_tp_sl_orchestrator_lifecycle.py`,
`test_reconcile_orphan_position.py`, `test_reconcile_duplicate_active.py`,
`test_reconcile_zombie_cleanup.py`.

**신규 unit (5개 파일)** — `test_strategy_status_constants.py`, `test_audit_fixes.py`,
`test_stream_service_dynamic_stages.py` 외 기존 보강.

### 🚦 운영 사용 예시
```bash
# 일일 손실 한도 — 계정별 override
psql $DATABASE_URL -c "UPDATE exchange_accounts SET daily_loss_limit_usdt = 1000
                       WHERE id = (SELECT id FROM exchange_accounts WHERE label='메인');"
# settings 의 글로벌 한도보다 우선 적용됨
```

```bash
# 「▶ 다음 단계」 중복 차단 검증 (testnet)
curl -X POST .../strategies/96/trigger-next-stage  # 1번 → 200 OK
curl -X POST .../strategies/96/trigger-next-stage  # 2번 → 400 "이미 거래소에 미체결"
```

### 🔖 Reviewer notes
- 「▶ 다음 단계」 = 옵션 A (LIMIT 발송) 유지 — 사용자 명시 결정. 옵션 B (즉시 시장가
  진입) 는 보류. 중복 클릭 방지 가드만 추가.
- 모든 fix 가 회귀 테스트 동반 — 다음 회귀 발생 시 테스트 추가만으로도 spec 보강 가능.
- 자세한 commit hash + 시간순 정리는 `HANDOFF-2026-05-04-HOME-TO-OFFICE.md` 참조.

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
