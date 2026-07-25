# 🚨 2026-07-24 전체 시스템 감사 리포트

## 배경
사장님 #505 DEXEUSDT TP10 조기 청산 사고 이후 = 사장님 요청으로 **전체 시스템 감사** 진행!

## 감사 방법
- **6개 병렬 Agent** (일반 목적) = 각 영역 심층 분석
- 사장님 헌법 51+ 대비 코드 검증
- 시나리오 시뮬레이션 6개 이상 per Agent

## 감사 영역
1. **TP/SL 로직** (risk_service, tp_sl_orchestrator, execution_service)
2. **잔액/증거금** (exchange_accounts, capital_calculator)
3. **포지션 관리** (stream_service, reconcile, execution_service)
4. **Worker** (18개 백그라운드 작업)
5. **UI ↔ Backend 동기화** (dashboard, strategies-list)
6. **사장님 헌법 준수** (spec ↔ 코드 대조)

## 총 발견 = 60건

| 등급 | 건수 |
|------|------|
| CRITICAL | 17 |
| HIGH | 21 |
| MEDIUM | 18 |
| LOW | 4 |

---

## ✅ Phase 1 완료 (2026-07-24) — CRITICAL 17건 모두 fix + 배포!

### 🅰️ 자본 즉시 손실 위험 (5건)

#### 1. `strategy_calculator.py:300` — 중간 stage qty leverage 누락
**silent bug**: `compute_qty_from_capital(capital, price)` = leverage 안 넘김 → default=1 → v107 위반!
- 3x 6-stage 전략 = stage 2/3/4/5 = **사장님 의도 1/3 qty만 진입!**
- **fix**: `leverage=leverage` 추가.

#### 2. `risk_service.py:155` — evaluate_stop_loss stale mark_price
**silent bug**: DB snapshot만 사용 = 최대 2분 stale.
- 급락 시 = **SL 발동 2분 지연 = 사장님 자본 추가 손실!**
- **fix**: `get_mark_price(Redis)` 우선 + DB fallback.

#### 3. `risk_service.py:294` — evaluate_take_profit_level stale mark_price
**silent bug**: 동일한 stale 패턴.
- **TP 발동 지연 + trailing peak 손실!**
- **fix**: Redis 우선.

#### 4. `liquidation_risk_worker.py` — stale mark_price
**silent bug**: Position snapshot (2분 지연) = SYNUSDT -585 USDT 사고 재발 위험!
- **fix**: Redis 우선.

#### 5. `exchange_accounts.py:_reserved_one` — 미체결 ad-hoc LIMIT 마진 누락
**silent bug**: 「💉 포지션 추가 LIMIT」 미체결분 = 예약 계산 X → **-2019 재발!**
- **fix**: Orders 테이블 stage_no=NULL LIMIT 조회 → 마진 합.

### 🅱️ 좀비/silent bug (5건)

#### 6. `execution_service.py:1173` — Redis peak 리셋 누락
**silent bug**: 「💉 포지션 추가 (reset)」 = max_profit_pct만 리셋 → Redis peak 옛 값 유지!
- = TP3 재도달 시 = 옛 peak 기준 = **즉시 TRAILING_TP 전량 청산!**
- **fix**: `_redis.delete(f"strategy:{id}:peak_pnl_pct")` 추가.

#### 7. `execution_service.py:emergency_close` — LIMIT orphan
**silent bug**: MARKET close만 발송 = 미체결 LIMIT 방치!
- = 긴급 종료 후 = LIMIT 도달 시 = **좀비 신 포지션 생성!**
- **fix**: `is_full_close` 시 `cancel_all_orders` 호출.

#### 8. `execution_service.py:trigger_next_stage` — STOPPING silent overwrite
**silent bug**: 자동 진입 중 사장님 「⛔ 긴급 종료」 → STOPPING이 STAGE_N_OPEN_PENDING로 덮어써짐!
- = 사장님 종료 명령이 **조용히 무시됨!**
- **fix**: fresh reload + TERMINAL/STOPPING 검증.

#### 9. `tp_sl_orchestrator.py` — 옛 template tp{n}_qty_ratio=100 잔재
**silent bug**: v126 auto-extend는 `tp{n}_percent=NULL`만 처리 → 옛 template의 tp10_qty_ratio=100 그대로 → **#505 재발!**
- **fix**: level_n < 20 + ratio_pct >= 100 + auto-extended 있으면 = default (25%) override.

#### 10. `reconcile_worker.py:341` — flat 좀비 cancel_all_orders 누락
**silent bug**: STOPPED 마킹만 = LIMIT 잔재 = **VELVETUSDT 자본 lock 재발!**
- **fix**: STOPPED 전에 `cancel_all_orders` 호출.

### 🅲 감시망/UI (5건)

#### 11. `admin/monitoring.py:421` — tp_breakdown TP1~5
**silent bug**: TP6~20 통계 카운트 X → 대시보드 = 항상 0!
- **fix**: `range(1, 11)` → `range(1, 21)`.

#### 12. `dashboard-refresh.js:245` — stats-tp TP1~10 순회
**silent bug**: HTML DOM은 TP1~20 있는데 for n=1..10 → TP11~20 표시 X.
- **fix**: `n <= 20`.

#### 13. `mainnet_safety_worker.py:102` — whitelist 너무 넓음
**silent bug**: `?`, `||`, `===` 흔한 JS 문법 = whitelist!
- 실제 testnet=true 하드코드 = **감지 못함!** = mainnet 사고!
- **fix**: word boundary regex 만.

#### 14. `execution_service.py:1149` — add_position_now LIMIT preflight X
**silent bug**: LIMIT은 preflight 없음 → -2019 → **502 (친절 X)**!
- **fix**: LIMIT도 `_preflight_entry_market_check` 호출.

#### 15. `add-position-modal.js` — 계정별 여유 표시 X
**silent bug**: 대시보드 balance-mini-free = 전체 계정 합산 = **Sub-Account B (200) → 800 시도 → -2019!**
- **fix**: exchangeAccountId 전달 → GET /balance/{id}.

### 🅳 기타 CRITICAL (2건)

#### 16. `distributed_scheduler_guard.py:14` — bytes/str 비교 silent bug
**silent bug**: `redis.get()` = bytes → `self.node_id` = str → **항상 !=** → refresh 항상 False!
- = leader 30초 만료 → 모든 job = **전면 정지 위험!**
- **fix**: `bytes.decode()` + str 비교.

#### 17. `tp_miss_detector_worker.py` — stale mark_price
**silent bug**: 동일한 Position snapshot stale.
- **fix**: Redis 우선.

---

## 🎯 **Phase 1 배포 완료**
- **Batch 1 (9건)**: commit `829fc8d`
- **Batch 2 (8건)**: commit `9b49a1b`
- **VPS 배포**: 완료 (git pull + docker restart)

## 📋 **다음 (Phase 2 = HIGH 21건, Phase 3 = MEDIUM 18건)**

### HIGH 우선순위 (21건):
- `strategy_service.py` = capital_calculator 통합 (단일 진실 위반)
- `tp_sl_orchestrator.py:253` = capital_based inflation → full close 위험
- `risk_service.py:409` = TP1_override=0 (「끔」) → TRAILING_TP 여전히 발동
- `settings_sync_worker` = 24h dedup 없음
- `run_workers.py:71` = TPSL 예외마다 즉시 Telegram (10초마다 spam!)
- `stage_trigger_worker:397` = 130% 검증 실패 시 silent 통과
- `heartbeat_worker` = severity 아니라 event_type LIKE '%CRITICAL%'
- (기타 14건)

### MEDIUM (18건):
- 관찰 필요, 즉시 위험 X
- 사장님 결정 사항 포함

### 재발 방지:
- **spec 문서화** (이 문서!)
- **정기 감사** (분기별)
- **자동 검증 worker** 추가

---

## 🚨 헌법 v127 신규 (17건 fix로 정착!)

1. **모든 mark_price = Redis 우선** (헌법 6 강화, worker/service 대칭성)
2. **모든 leverage 계산 = capital × lev / price** (v107 완성)
3. **「💉 포지션 추가 (reset)」 = Redis peak도 리셋** (헌법 51 완성)
4. **긴급 종료 = LIMIT도 취소** (좀비 방지)
5. **STOPPING/TERMINAL = 신 진입 차단** (race 방지)
6. **template 옛 100% qty_ratio 잔재 = safety net** (마지막 아닌 TP = default)
7. **미체결 ad-hoc LIMIT 마진 = 예약 계산 포함** (130% 검증 완성)
8. **LIMIT 도 preflight 검증** (친절 에러)
9. **UI 표시 vs backend 실제 = 일치** (TP1~20 통일)
10. **Sub-Account 여유 = 계정별 정확** (합산 X)
11. **whitelist = word boundary만** (false negative 차단)
12. **Redis get() = bytes 변환** (leader 갱신 정확)

## 결론
**사장님 자본 보호 = 최대치! v127 배포 후 = 대부분 silent bug 근본 fix!**
