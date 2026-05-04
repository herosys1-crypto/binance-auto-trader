# HANDOFF — 2026-05-04 (집 → 사무실)

집에서 5-04 종일 작업한 26개 commit 을 사무실에서 이어받기 위한 인계서입니다.
**branch: `claude/loving-rhodes-52788c` (PR #1, origin/main 대비 26 commits ahead).**

---

## 📌 한 줄 요약

(1) 좀비 6패턴 회귀 방어 + Sentry 관측성 + 옵션 C 5+단계 status 매핑 fix
(2) 일일 손실 한도 v3 (계정별 override) + Kill Switch 사각지대 fix + 증거금 추가 + -50% ROI 알림
(3) 트레일링 TP / TP 중간 단계 silent skip — risk_service evaluate_take_profit_level 정렬 + 우선순위 버그 fix (CRITICAL)
(4) 「↻ 설정만 수정」 in-place + 「▶ 다음 단계」 수동 진입 + 다음 stage trigger_percent 부분 갱신
(5) 사용자 #96 다단계 manual trigger 시 NEW LIMIT 중복 + reconcile auto-promote 오작동 양쪽 fix
**테스트 292 통과 (이전 110 → +182), 코드 동작 변경 모두 회귀 테스트 동반.**

---

## 🛠️ 이 세션에 origin 에 들어간 26개 commit (최신 → 과거)

```
f9bbe16 fix(api): trigger_next_stage_manually 가 NEW LIMIT 중복 차단 (사용자 #96 사례)
787709c fix(reconcile): PENDING→OPEN 자동 승격이 stage_plan.is_triggered 검증 (사용자 #96 사례)
e5da3d7 fix(ui): 액션 버튼 컴팩트화 — 「▶ 다음 단계」 줄바꿈 → 행 높이 비대
074619f fix(ui): 모달 시세 로드 후 시작가 input 자동 채움 (TAGUSDT 422 사용자 보고)
3d96d89 feat: 다음 단계 트리거율 in-place 수정 + 수동 다음 단계 진입 + 증거금 추가 가시성
3c57bb2 feat(ui+api): 수정 모드에 「↻ 설정만 수정」 in-place 버튼 (포지션/단계 유지)
5bbda50 fix(risk_service): TP 중간 단계 silent skip 버그 (사용자 #98 사례 #2)
534c690 fix(risk_service): 트레일링 TP 가 직전 TP threshold 위에 있을 때 무력화되던 버그
27bc852 fix(audit): get_first_active_binance user 필터 + RiskEventResponse Optional schema
6de84a4 fix(audit): TERMINAL_STATUSES 공통 상수 통일 + kill-switch 소유권 검증
9611304 feat(ui): 거래소 계정 + 일일 손실 한도 관리 모달 (P)
d88f41d feat(safety): 전략별 증거금 추가 + -50% ROI 손실 임계 알림 (사용자 요청)
10dd208 fix(audit): idempotency 2xx-only 캐시 + encryption_key startup 검증 + ExchangeAccount daily_limit API 노출
4ca52d8 feat(safety): 일일 손실 한도 v3 — 계정별 override + STOPPING UI 숨김 (200 tests)
9c0ef1f feat(safety): daily_loss_limit v2 — realized_pnl 일일 누적 (stream_service hook)
016b678 feat(safety): daily_loss_aggregator worker — 일일 손실 한도 자동 발동 (CRITICAL #2)
c79f3aa fix(safety): Kill Switch 사각지대 (stage 2+, create) + keepalive Sentry capture
12d47d5 fix(auto_reentry): 실패 시 REENTRY_FAILED status persist + Sentry capture + tz 방어
b40401f fix(ui): PnL/ROI 셀에 포지션 ROI (Binance 일치) + 전략 ROI 분리 표시
8b521a3 fix(ux+api): STOPPING 가시성 + 중복 방지 가이드 + COMPLETED 행 「🔄 다시 시작」 버튼
b28c92f fix(option-c-5+): 1~10 단계 동적 status 매핑 + STATUS_MAP 누락 라벨 보강
89f779d fix(ui+api): COMPLETED/REENTRY_READY 가 종료 분류에서 빠져 액션 버튼 오노출
8917103 test+docs: tp_sl_orchestrator 종단간 5건 + CHANGELOG + testnet 검증 시나리오
a937e27 test(integration): reconcile_worker 종단간 회귀 11개 + sqlite/Binance mock 스캐폴드
852d378 feat+observability: crisis_qty_ratios template override + Sentry capture 확장
11cf6fd test+observability: zombie_guardian 회귀 테스트 16개 + Sentry 구조화 캡처
```

---

## 🐛 이 세션에 fix 한 핵심 버그 (사용자 사례 기반)

### 🔴 CRITICAL — 사용자 #98 (LABUSDT, 트레일링 TP 미발동)
| ID | 제목 | 영향 | Fix |
|---|---|---|---|
| 1 | **트레일링 TP 가 TP loop 뒤에 있어 무력화** | 피크 +30% 후 -10% 회귀했는데 잔량 청산 안 됨 (+193 USDT 미실현 미잠금) | `534c690` — `risk_service.evaluate_take_profit_level` 에서 trailing 체크를 TP loop **이전**으로 이동 |
| 2 | **TP 중간 단계 silent skip** | TP1 처리 후 TP3 도달했는데 TP2 가 한 번도 발동 안 되고 건너뜀 | `5bbda50` — TP loop 를 ascending sort + `cur_done_idx` 비교로 변경 |

### 🔴 CRITICAL — 사용자 #96 (TSTUSDT, 다단계 수동 진입 시 잘못된 status / 중복 LIMIT)
| ID | 제목 | 영향 | Fix |
|---|---|---|---|
| 3 | **reconcile auto-promote 가 stage_plan 검증 없이 발동** | STAGE4_OPEN_PENDING + 거래소 (이전 stages 합) 만 보고 잘못 promote → status 오염 | `787709c` — `_PENDING_TO_OPEN` 발동 전에 `plan.is_triggered=True` 검증 |
| 4 | **「▶ 다음 단계」 중복 클릭 = 같은 stage 의 LIMIT 다중 발송** | 가격 도달 시 동시 체결 → 포지션 더블링 | `f9bbe16` — `trigger_next_stage_manually` 에서 `Order.status='NEW'` 중복 가드 |

### 🟡 운영 가시성 / 안전망
| ID | 제목 | Fix |
|---|---|---|
| 5 | 옵션 C 5+ 단계 status 매핑 누락 (5 모듈) | `b28c92f` — stream/execution/reconcile/zombie/stage_trigger 모두 `range(1,11)` 동적 매핑 |
| 6 | COMPLETED/REENTRY_READY 종료 분류 누락 → 액션 버튼 오노출 | `89f779d` + `6de84a4` 공통 `TERMINAL_STATUSES` 상수 통일 |
| 7 | STOPPING 좀비 가시성 + 행 클릭 「🔄 다시 시작」 | `8b521a3` |
| 8 | PnL/ROI 셀 = Binance 일치 (포지션 ROI 별도 표시) | `b40401f` |
| 9 | Kill Switch 사각지대 (stage 2+ 진입, create) | `c79f3aa` |
| 10 | auto_reentry 실패 시 REENTRY_FAILED status persist | `12d47d5` |

### ✨ 신규 기능
| ID | 제목 | Commit |
|---|---|---|
| 11 | **일일 손실 한도** (계정별 override + 자동 발동 + UI 모달) | `016b678` → `9c0ef1f` → `4ca52d8` → `9611304` |
| 12 | **전략별 증거금 추가** + **-50% ROI 손실 임계 알림** (텔레그램) | `d88f41d` |
| 13 | **「↻ 설정만 수정」 in-place** (포지션/단계 유지하고 TP/SL/trigger% 만 갱신) | `3c57bb2` → `3d96d89` |
| 14 | **「▶ 다음 단계」 수동 진입** | `3d96d89` |
| 15 | **다음 stage trigger_percents 부분 갱신** (PATCH /settings 확장) | `3d96d89` |
| 16 | **「💼 계정」 모달** — daily_loss_limit_usdt 관리 | `9611304` |
| 17 | **Sentry 구조화 캡처** (DSN 미설정 시 no-op) | `11cf6fd` + `852d378` |
| 18 | **crisis_qty_ratios** template override (alembic 0009) | `852d378` |

---

## 🗂️ 새로 생성된 파일

### Backend
- `backend/app/core/strategy_status.py` — 공통 `TERMINAL_STATUSES` frozenset
- `backend/app/core/sentry.py` — `capture_strategy_event` 헬퍼
- `backend/app/services/account_daily_loss_limiter.py` — 계정별 한도 발동
- `backend/app/workers/daily_loss_aggregator.py` — 1분 주기 일일 손익 집계
- `backend/alembic/versions/0009_template_crisis_qty_ratios.py`
- `backend/alembic/versions/0010_exchange_account_daily_loss_limit.py`

### Tests (110 → 292, +182)
**Integration (신규 카테고리)**
- `conftest.py` — sqlite + JSONB→JSON + factory fixtures + FakeBinance/Trade/Redis
- `test_reconcile_zombie_cleanup.py` (5)
- `test_reconcile_orphan_position.py` (4)
- `test_reconcile_duplicate_active.py` (2)
- `test_reconcile_5plus_stages.py` (13) — 5~10단계 PENDING→OPEN + orphan
- `test_tp_sl_orchestrator_lifecycle.py` (5)
- `test_tp_intermediate_skip.py` (5) — TP2 silent skip 회귀 방어
- `test_trailing_tp_priority.py` (5) — trailing 우선순위 회귀 방어
- `test_strategy_settings_inplace.py` (8)
- `test_trigger_next_stage_and_inplace_stages.py` (8) — 수동 진입 + 부분 갱신
- `test_add_margin_and_loss_alert.py` (7)
- `test_daily_loss_aggregator.py` (10)
- `test_daily_loss_per_account_limit.py` (8)
- `test_daily_loss_realized_accumulation.py` (7)
- `test_exchange_accounts_daily_limit.py` (6)
- `test_kill_switch_coverage.py` (6)
- `test_kill_switch_endpoint_ownership.py` (5)
- `test_auto_reentry_worker.py` (8)
- `test_create_strategy_duplicate_prevention.py` (5)
- `test_audit_repos_schemas.py` (4)
- `test_strategies_endpoint_terminal_handling.py` (8)

**Unit (신규)**
- `test_zombie_guardian.py` (16)
- `test_crisis_qty_ratios_resolver.py` (13)
- `test_strategy_status_constants.py` (5)
- `test_audit_fixes.py` (7)
- `test_stream_service_dynamic_stages.py` (5)

---

## 📊 Live 운영 현재 상태 (2026-05-04 03:58 KST)

### Docker
3개 backend 컨테이너 (api / scheduler / user-stream) 모두 **Up** + pycache 청소 후 재시작 완료.
worktree 코드 ↔ main backend 동기화 (ff merge `787709c..f9bbe16`) 완료.

### 사용자 #96 (TSTUSDT) 복구 후 상태
- Binance: 중복 stage 3 LIMIT 2개 + stage 4 LIMIT 1개 모두 cancel
- DB: Order #139/140/143 = `CANCELED`
- StrategyInstance #96: `STAGE2_OPEN`, `current_stage=2`
- 「▶ 다음 단계」 가드 활성화 — 같은 stage 의 NEW LIMIT 가 있으면 400 으로 차단

### 알려진 미해결 의문점
- 재시작 직전 RiskEvent #247 (`RECONCILE_RECOVERED_PENDING`) 의 메시지 형식이 **신규 fix 메시지와 다름**
  - 컨테이너 내부 `grep "stage_plan triggered"` 는 1 hit 으로 신규 코드 적재 확인됨
  - 가설: pycache stale → 재시작 시 청소했으니 이후 사이클부터는 새 메시지로 기록될 것
  - **사무실에서 첫 확인**: `RiskEvent` 테이블에서 `event_type='RECONCILE_RECOVERED_PENDING'` 최신 row 의 `details` 필드를 보고 신 메시지 형식 (`"stage_plan triggered, position={amt}"`) 인지 확인

---

## 🎯 사무실에서 이어받을 작업 (우선순위 순)

### A. 즉시 확인 (5분)
1. `git pull origin claude/loving-rhodes-52788c` — 26개 commit 받기 (최신 = `f9bbe16`)
2. `cd backend && pytest -q` — **292 passed, 0 warnings** 가 나오는지 확인
3. PR #1 GitHub UI — review 코멘트 확인 (없으면 진행)

### B. 운영 검증 (testnet, 30분)
- `RiskEvent` 최신 row 메시지 형식 확인 (위 의문점)
- Live 화면에서 다음 시나리오 1회씩:
  - 「▶ 다음 단계」 클릭 → 「▶」 다시 클릭 = "이미 거래소에 미체결" 400 (기대)
  - 「↻ 설정만 수정」 → trigger_percents 수정 → 미발동 stage 만 plan 갱신 (기대)
  - 「💰 증거금 추가」 100 USDT → margin call 위험 회피 (기대)
  - 한 전략 -50% ROI 도달 → 텔레그램 알림 1회 (one-time 크로싱)

### C. mainnet 직전 마지막 점검 (1시간)
참고: `MAINNET-CHECKLIST.md` 가 가장 권위 있음. 5-04 변경 추가 확인:
- 일일 손실 한도 = 계정별 override 가 settings 보다 우선
- crisis_qty_ratios = template NULL 이면 default 25/25/50/100 적용
- Sentry DSN 환경변수 설정 (production 만)

### D. 보류 중 작업 (mainnet 후 검토)
- AUDIT-FINDINGS.md A14/A15/A16 — audit 자체가 deferred 권장
- ngrok offline 이슈는 worktree dev 환경 한정 (production 무관)
- DASHBOARD_V2_PLAN.md — Phase 4 시각화 (chart.js) 보류 중

---

## 🔧 환경 설정 (오피스 컴퓨터 처음 set up 인 경우만)

```bash
# 1. clone + 브랜치 체크아웃
cd ~/work
git clone https://github.com/herosys1-crypto/binance-auto-trader.git
cd binance-auto-trader
git checkout claude/loving-rhodes-52788c

# 2. backend venv
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
pytest -q  # → 292 passed

# 3. .env 복사 (testnet) — 별도 채널로 전달받은 testnet 키 사용
cp .env.example .env
# 필수: BINANCE_API_KEY/SECRET, ENCRYPTION_KEY, DATABASE_URL (Neon), TELEGRAM_BOT_TOKEN

# 4. docker (선택 — 사무실에서 단순 코드 작업만이면 불필요)
cd ..
docker compose up -d db redis
docker compose up -d api scheduler user-stream
```

---

## 📚 권위 있는 문서 (변경 없음, 그대로 유효)

| 문서 | 역할 |
|---|---|
| `SYSTEM-SPEC.md` | 시스템 정밀 기획서 (14 섹션) — **신규 작업 전 반드시 참조** |
| `AUDIT-FINDINGS.md` | A01~A17 audit 결과 (이번 세션에 일부 ✅ 추가됨) |
| `RUNBOOK.md` (backend/) | 운영 매뉴얼 (긴급/정기/트러블슈팅) |
| `DEPLOYMENT-DIGITALOCEAN.md` | mainnet VPS 배포 가이드 |
| `MAINNET-CHECKLIST.md` | mainnet 전환 체크리스트 |
| `TESTNET-VALIDATION-SCENARIOS.md` | testnet 검증 시나리오 (이번 세션에 보강) |
| `CHANGELOG.md` | 세션 단위 변경 이력 (이 핸드오프와 같은 5-04 항목 보강 필요 — 아래 참조) |

---

## ✅ 이번 세션 commit 메시지 컨벤션 (참고)

- `feat:` 신규 기능 (사용자 가시)
- `fix(<scope>):` 버그 수정. scope = api/ui/risk_service/reconcile/audit/option-c-5+/safety/auto_reentry/...
- `test:` 테스트 추가 (코드 동작 변경 없음)
- `docs:` 문서만 변경
- 본문에 사용자 사례 번호 (#96, #98) 명시 → 추적성 ↑

---

**작성: 2026-05-04 04:00 KST 집 PC. 다음 작업: 사무실 Pull → testnet 운영 검증 → mainnet 보안 로테이션.**
