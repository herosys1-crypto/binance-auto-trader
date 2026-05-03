# TESTNET-VALIDATION-SCENARIOS.md

**testnet 종단간 검증 플레이북 (mainnet 전환 직전)**

> 작성일: 2026-05-04
> 목적: 코드 변경이 누적된 시점에 testnet 에서 한 번에 모든 핵심 시나리오를
> 통과하는지 확인. `MAINNET-CHECKLIST.md` 의 "2-1 testnet 종단간 검증" 항목을
> 실제 실행 가능한 step-by-step 으로 풀어둔 문서.

> 범례:  
> ⚠️ MUST — 통과 못하면 mainnet 금지  
> 🟡 권장 — 가급적 통과  
> ⏱ 예상 소요 — 시나리오마다 최소 시간 (대기 포함)  
> 📊 관찰 — 어디서 결과 확인하나

---

## Phase 0 — Pre-flight (5분, 매 세션마다 실행) ⚠️

각 항목 모두 ✅ 일 때만 다음 단계로 진행.

| 체크 | 명령 / 위치 | 기대 결과 |
|---|---|---|
| Docker 컨테이너 11개 모두 Up | `docker compose ps` | 11/11 running |
| 운영 대시보드 접속 | http://localhost:8000 | 시스템 상태 = 정상 |
| Telegram 도달 | 대시보드 「📱 Telegram 테스트」 버튼 | 메시지 1건 도착 |
| Zombie Guardian 배너 | 대시보드 상단 zg-banner | 좀비 0건 / 정상 |
| `/admin/system-status` | http://localhost:8000/admin/system-status | active strategies + reconcile lock 상태 출력 |
| `pytest tests/ -q` | backend 디렉토리 | 110 passed |
| 거래소 계정 활성 | `select * from exchange_accounts` | testnet row, is_active=true |
| 잔액 확인 | 대시보드 잔액 패널 또는 거래소 직접 | testnet USDT > 200 (시나리오 자본) |

---

## Phase 1 — 옵션 C 6단계 종단간 (3~6시간 시장 변동 대기 포함) ⚠️

**목표**: 1단계 진입 → 2~6단계 자동 트리거 → TP1 부분 청산 → 마지막 TP 전량 청산
→ COMPLETED 의 정상 흐름 한 번 끝까지 통과.

### 1-1. 전략 생성

대시보드 「🟢 새 전략 시작」:
- 거래소 계정: **testnet**
- 심볼: **BTCUSDT** 또는 **ETHUSDT** (변동성 + 고유동성)
- 방향: **SHORT** (변동성 큰 시간대 권장)
- 단계 입력 (직접 입력 6단계, 기획 #75 기준):

| 단계 | capital | trigger |
|---|---|---|
| 1 | 200 | 즉시 |
| 2 | 300 | +10% |
| 3 | 500 | +10% |
| 4 | 700 | +10% |
| 5 | 900 | +20% |
| 6 | 1200 | +20% |

- 레버리지: **5x** (계산이 쉬움)
- TP: TP1=5% / TP2=10% / TP3=15% / TP1_qty=25% / TP2_qty=50% / TP3_qty=100%
- SL: -50%

### 1-2. 미리보기 검증 ⚠️

「미리보기」 클릭 → 다음 모두 일치하는지 확인:

| 관찰 | 기대 | ✅/❌ |
|---|---|---|
| 단계 6개 표시 | 1~6 모두 표 | ☐ |
| 6단계 trigger | "+20% 도달 시" | ☐ |
| 잔액 vs 필요 마진 카드 | 필요 마진 = (200+300+...)/5x = 760 USDT, 잔액 충분 표시 | ☐ |
| 단계별 직전/직후 ROI | 누적 손실% 표시 | ☐ |

### 1-3. 시작 → 1단계 진입

| # | 관찰 포인트 | 기대 동작 | ✅/❌ | 메모 |
|---|---|---|---|---|
| 1 | 상태 전이 | WAITING → STAGE1_OPEN_PENDING → STAGE1_OPEN | ☐ | |
| 2 | Telegram 알림 | "1단계 진입" 1건 (중복 없음) | ☐ | dedup gate 검증 |
| 3 | DB position row | 1건 생성 (source=POSITION_RISK_SYNC 또는 STREAM) | ☐ | |
| 4 | 활동 타임라인 | "1단계 진입 (200 USDT)" 표시 | ☐ | |
| 5 | 차트 마커 | 진입가 위치에 마커 표시 | ☐ | |

### 1-4. 2~6단계 자동 트리거 (시장 변동 대기) ⏱ 1~6시간

가격 변동 따라:
- SHORT: 가격이 위로 올라야 추가 진입
- 각 단계 trigger 가격 도달 시 자동 LIMIT 주문 발송

| # | 관찰 포인트 | 기대 동작 | ✅/❌ | 메모 |
|---|---|---|---|---|
| 6 | 2단계 자동 진입 | mark >= trigger (SHORT) → LIMIT BUY 발송 → FILLED → STAGE2_OPEN | ☐ | |
| 7 | Telegram | "2단계 진입" 알림 | ☐ | |
| 8 | 3~6단계 동일 | 각 단계 trigger 도달 시 자동 진입 | ☐ | 시장 따라 일부만 발동 가능 |
| 9 | 평균 진입가 갱신 | 각 단계마다 strategy.avg_entry_price 자동 갱신 | ☐ | |
| 10 | reconcile sync | 30초마다 거래소 ↔ DB sync (qty mismatch 알림 없어야 함) | ☐ | |

### 1-5. TP 발동 (역방향 가격 변동 대기) ⏱ 1~3시간

| # | 관찰 포인트 | 기대 동작 | ✅/❌ | 메모 |
|---|---|---|---|---|
| 11 | TP1 도달 (5% PnL) | reduceOnly MARKET 주문 (qty = 25% × current_qty) → FILLED | ☐ | |
| 12 | 잔량 보존 | strategy.current_position_qty 가 0 이 아니라 75% 잔량 유지 | ☐ | **`0da0f55` 회귀 방어** |
| 13 | status 전이 | STAGE_X_OPEN → TP1_DONE_PARTIAL | ☐ | |
| 14 | Telegram TP1 | 손익 + ROI + 잔량 표시 | ☐ | |
| 15 | TP2 도달 | 동일 흐름 (50% 청산) → TP2_DONE_PARTIAL | ☐ | |
| 16 | TP3 (마지막 활성 TP) | **사용자 ratio 무시, 잔량 100% 청산** → COMPLETED | ☐ | **`0e3d119` 회귀 방어** |
| 17 | reentry_ready | COMPLETED 시 reentry_ready=False | ☐ | |
| 18 | 차트 마커 | 각 TP 청산가에 마커 + 손익 라벨 | ☐ | |

### 1-6. 종료 검증

| # | 관찰 포인트 | 기대 | ✅/❌ |
|---|---|---|---|
| 19 | 거래소 포지션 0 | Binance UI 에서 BTCUSDT SHORT amt = 0 | ☐ |
| 20 | DB qty 0 | strategy.current_position_qty = 0 | ☐ |
| 21 | reconcile orphan 무발생 | 다음 30초 사이클에 orphan 알림 없음 | ☐ |
| 22 | realized_pnl 정확 | 각 청산 부분 합 = 누적 realized_pnl (±0.01) | ☐ |

---

## Phase 2 — 만성 좀비 6패턴 자동 회복 검증 ⚠️

**목표**: 6638177/6133072 commit 의 좀비 자동 회복 + Zombie Guardian 안전망이
실제 운영 환경에서 작동.

### 2-1. STOPPING 좀비 자동 정리 ⏱ 30초~5분

시나리오: 「수동 정지/청산」 후 stream 누락 시 STOPPING stuck 좀비 발생.

| # | 단계 | 기대 동작 | ✅/❌ |
|---|---|---|---|
| 1 | active strategy 1건에서 「수동 정지/청산」 클릭 | 거래소 reduceOnly MARKET 주문 발송 | ☐ |
| 2 | status 즉시 STOPPING 으로 표시 | UI 30초 polling 으로 갱신 | ☐ |
| 3 | EXIT FILLED stream 도착 (정상) | status STOPPING → STOPPED 전환, qty=0 | ☐ |
| 4 | reentry_ready=False | 사용자 정지 의도 보존 (REENTRY_READY 가 아님) | ☐ |
| 5 | (옵션) stream 누락 시뮬 | reconcile_worker 가 30초 사이클에 STOPPED 자동 승격 | ☐ |
| 6 | RECONCILE_STOPPING_ZOMBIE_CLEANUP RiskEvent | DB / 활동 타임라인에 INFO 이벤트 1건 | ☐ |

### 2-2. *_OPEN orphan 자동 정리 (외부 청산)

시나리오: 거래소 직접 UI 에서 포지션 강제 청산 → 시스템엔 STAGE_X_OPEN 잔재.

| # | 단계 | 기대 동작 | ✅/❌ |
|---|---|---|---|
| 1 | testnet 새 전략 시작 후 STAGE1_OPEN 진입 | 정상 active | ☐ |
| 2 | Binance testnet UI 에서 그 포지션 직접 청산 | 거래소 포지션 0 | ☐ |
| 3 | 30~60초 대기 (reconcile 사이클 1~2회) | RECONCILE_AUTO_STOP_ORPHAN RiskEvent + status STOPPED | ☐ |
| 4 | Telegram 알림 | "외부 청산된 전략 자동 정리" | ☐ |

### 2-3. 거래소 orphan 포지션 → Kill-Switch ⚠️

시나리오: 시스템 외부에서 testnet UI 직접 진입 → 시스템엔 매칭 strategy 없음.

| # | 단계 | 기대 동작 | ✅/❌ |
|---|---|---|---|
| 1 | Binance testnet UI 에서 직접 BTCUSDT LONG 진입 (시스템 미인지) | 거래소 포지션만 존재 | ☐ |
| 2 | 30~60초 대기 (reconcile 사이클) | ZOMBIE_ORPHAN_EXCHANGE_POSITION CRITICAL RiskEvent | ☐ |
| 3 | AccountKillSwitch 자동 발동 | account_kill_switches.is_enabled = true | ☐ |
| 4 | Telegram CRITICAL 알림 | 거래소 포지션 스냅샷 + Kill-Switch 안내 | ☐ |
| 5 | 신규 전략 진입 시도 | "Kill-switch 활성" 으로 차단 | ☐ |
| 6 | (정리) Binance UI 에서 직접 청산 + Kill-Switch 수동 해제 | 정상 복귀 | ☐ |

### 2-4. 중복 active strategy 강등 (race) ⚠️

시나리오: 같은 (acc, sym, side) 로 두 strategy 가 active 가 된 race window
(이전 #89/#90 LABUSDT 사례).

| # | 단계 | 기대 동작 | ✅/❌ |
|---|---|---|---|
| 1 | 정상 strategy A (BTCUSDT SHORT) 운영 중 | active | ☐ |
| 2 | (시뮬) DB 에 직접 같은 키로 두 번째 active row 강제 INSERT | 두 strategy active | ☐ |
| 3 | 다음 reconcile 사이클 (30초) | older 가 STOPPED 강등, ZOMBIE_DUPLICATE_ACTIVE_DEMOTED RiskEvent | ☐ |
| 4 | newer 는 그대로 active | 거래소 포지션 점유 보존 | ☐ |

> 주: 운영 환경에선 이미 `strategy_service.create_strategy_instance` 의 중복 방지가
> 강화돼 있어 (#89/#90 fix) 이 시나리오는 거의 발생 안 함. 시뮬레이션은 안전망 검증용.

### 2-5. terminal qty 잔재 정리

시나리오: STOPPED/COMPLETED 상태인데 qty 가 0 이 아닌 잔재 (이전 #83 XNYUSDT 사례).

| # | 단계 | 기대 동작 | ✅/❌ |
|---|---|---|---|
| 1 | (시뮬) DB 에 STOPPED + qty=-100 row 강제 UPDATE | 잔재 발생 | ☐ |
| 2 | 다음 reconcile 사이클 | enforce_terminal_qty_zero 가 qty=0 으로 정리 + ZOMBIE_TERMINAL_QTY_RESET RiskEvent | ☐ |

---

## Phase 3 — 24시간 운영 안정성 ⚠️ ⏱ 24h+

**목표**: listenKey 갱신, reconcile 누적, peak 추적 메모리 누수, 메트릭 안정성 검증.

24시간 동안 다음 모니터링 (대시보드 + Grafana):

| 항목 | 기대 | ✅/❌ |
|---|---|---|
| user-stream connected gauge | 24h 내내 1 (재연결 카운트는 0~1 허용) | ☐ |
| scheduler leader gauge | 24h 내내 1 (단일 인스턴스) | ☐ |
| listenKey 24h 자동 갱신 | listenKeyExpired 이벤트 시 user-stream 자동 reconnect | ☐ |
| reconcile_total{status="success"} 누적 | 30초 사이클당 +1 (24h ≈ 2880회) | ☐ |
| reconcile_total{status="miss"} | 0 또는 매우 낮음 (PENDING 미체결 외 없어야) | ☐ |
| Zombie Guardian | 좀비 0건 유지 (escalate_total = 0 기대) | ☐ |
| Telegram 알림 누락 | TP/SL/단계 진입 시 모두 1건 도달 (중복 없음) | ☐ |
| 메모리 누수 | container memory 24h 변동 폭 < 100MB (peak Redis key 누적 없는지) | ☐ |
| `/health` 200 OK | 외부 health check (UptimeRobot 등) 24h | ☐ |
| Sentry 이벤트 | (DSN 설정 시) 의도치 않은 ERROR/FATAL 0건 | ☐ |

---

## Phase 4 — 추가 시나리오 (시간 여유 시) 🟡

### 4-1. 트레일링 익절 -5%

| 단계 | 기대 |
|---|---|
| TP1 발동 → 피크 +12% 도달 → -5% 회귀 (현재 +7%) | TRAILING_TP 발동, 잔량 100% 청산 + COMPLETED |

### 4-2. -50% 손절

| 단계 | 기대 |
|---|---|
| 모든 단계 진입 후 손실 -50% 도달 | STOP_LOSS_TRIGGERED RiskEvent + 잔량 100% 청산 + REENTRY_READY |

### 4-3. 크라이시스 복구 모드

| 단계 | 기대 |
|---|---|
| max_loss_pct ≤ -30% 도달 | (자연 발생 어려움, DB 직접 UPDATE 로 시뮬) |
| 그 후 양수 PnL 전환 | CRISIS_MODE_TRIGGERED + TP 임계 5/10/15/20% 로 override |
| TP1 (+5%) 발동 | CRISIS_TP1 (25% 청산) + crisis_first_tp_done_at 기록 |
| TP1 후 -5% 회귀 | CRISIS_TRAIL_FULL (전량 청산) |

### 4-4. 자동 재진입

| 단계 | 기대 |
|---|---|
| reentry_policy=auto 인 template 으로 SL 발동 | reentry_delay_seconds 후 새 strategy 자동 시작 |
| 새 start_price = 현재가 × (1 ± offset/100) | SHORT +offset / LONG -offset |

### 4-5. crisis_qty_ratios template override (신규)

| 단계 | 기대 |
|---|---|
| `UPDATE strategy_templates SET crisis_qty_ratios = '{"TP1":40}' WHERE name=...` | 다음 크라이시스 TP1 발동 시 25% → 40% 청산 |

---

## Phase 5 — 회귀 안전망 ⚠️

| 항목 | 명령 | ✅/❌ |
|---|---|---|
| Unit 테스트 | `cd backend && pytest tests/unit/ -q` → 99 passed | ☐ |
| Integration 테스트 | `cd backend && pytest tests/integration/ -q` → 11 passed | ☐ |
| 전체 | `cd backend && pytest tests/ -q` → 110 passed | ☐ |
| Alembic head | `alembic current` → 0009_template_crisis_qty_ratios | ☐ |

---

## 통과 기준 (mainnet 진행)

- Phase 0/1/2/3/5: **모두 ⚠️ 항목이 ✅** 여야 mainnet 전환
- Phase 4: 🟡, 가급적 통과 (시간 허용 시)

mainnet 전환은 [MAINNET-CHECKLIST.md](MAINNET-CHECKLIST.md) 의 보안 로테이션 +
DigitalOcean 배포 ([DEPLOYMENT-DIGITALOCEAN.md](DEPLOYMENT-DIGITALOCEAN.md)) 와
함께 진행.

---

## 실행 기록 (세션마다 채우기)

| 일자 | 운영자 | Phase 통과 | 발견 이슈 | 후속 commit |
|---|---|---|---|---|
| 2026-05-04 | (예시) | Phase 0 ✅ / 1 진행 중 | — | — |
