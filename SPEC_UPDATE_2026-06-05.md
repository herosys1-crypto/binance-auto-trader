# 📝 2026-06-05 — Spec 통합 Update (6-01 mainnet ~ 6-05 = 53+ task)

> 이 파일 = 기존 spec (SYSTEM-SPEC.md + DEVELOPMENT_SPEC.md + TP_TRAILING_LOGIC_FINAL.md) 의 
> 마지막 update 이후 (5-15) 추가된 모든 변경 사항을 한 곳에 통합 정리.
> 옛 spec 내용 = 그대로 유지 (audit 보존). 본 파일 = 신규 사항만 명시.

---

## 📊 운영 진행 (시간 순)

| 시점 | 작업 |
|---|---|
| **6-01** | mainnet 진입 (Sub-Account API key + USDT 이체 + 8 critical fix) |
| **6-02** | 17 PR (sync_health, Binance 비교, 자본 자동 갱신, qty race fix 등) |
| **6-03** | 20 PR + Neon DB credentials 회전 (보안 사고 즉시 대응) |
| **6-05** | 15 PR + HTTPS + Sentry + 사장님 사상 옵션 A + TP 청산 정확화 |

**총 53+ task — 모두 main 머지 + VPS 배포 + 사장님 검증 완료.**

---

## 🛡 6-layer 안전망 → 9-layer 통합 (운영 자동 모니터링)

| Layer | Worker / Service | 주기 / 트리거 | 통보 / 액션 |
|---|---|---|---|
| **1** | `sync_health_monitor` (PR #38) | 5분 | DB ↔ Binance 차이 (수량 1%, 진입가 0.1%, uPnL 1 USDT) → Telegram |
| **2** | `endpoint_health_monitor` (PR #53+#73) | 30분 | WS/REST/mark-price/API auth 검증 → 실패 시 Telegram |
| **3** | `realized_pnl_sync_worker` (PR #34) | 1분 | user-stream 우회 동기화 (PENDING 머무름 방지) |
| **4** | `daily_summary_worker` (PR #66) | 매일 KST 00:00 | 사장님 운영 요약 텔레그램 |
| **5** | `_maybe_send_sl_progress_alert` (PR #68) | SL 80% 도달 시 (1h dedup) | 사장님 즉시 인지 |
| **6** | `_check_account_auth` (PR #73) | 30분 / 1일 dedup | API key 만료/회수/IP 변경 즉시 알림 |
| **7** | **자본 자동 동기화** (reconcile PR #84) | 30초 | Binance isolated > DB × 1.05 시 = DB total_capital 자동 갱신 |
| **8** | **`binance_changelog_monitor` v2** (PR #54+v2) | 6시간 | Binance docs 자동 감지 + diff + 영향 평가 + dedup 24h |
| **9** | **Sentry silent error** (#9) | 실시간 (자동 capture) | 모든 silent error / N+1 / exception 자동 캡쳐 + 알림 |

---

## 🌟 사장님 사상 핵심 정책 (CORE)

### 1. 잔액 = 전체 단계 예약 모드 (PR #30, #44)
```python
reserved_for_strategies = sum(
    max(s.total_capital, binance_actual_margin)
    for s in active_strategies
)
our_available_balance = total_wallet - reserved_for_strategies
```
- 사장님 입력 자본 (또는 Binance 실 마진 중 큰 값) 모두 예약
- 신규 strategy 생성 시 = `reserved ≤ wallet` 검증 → -2019 사전 차단

### 2. SL = 투자금 대비 손실 % (레버리지 무관) (PR #57)
```python
sl_threshold_usd = total_capital × sl_pct / 100   # 절대 손실 한도
sl_triggered = abs(unrealized_pnl) >= sl_threshold_usd  # pnl 음수 시
```
**사장님 명시 의도**: "투자금에 -80% 일때 실행, 레버리지 상관없이"

### 3. TP 청산 = max(qty 기준, capital 기준) × ratio (PR #87+#88)
```python
effective_margin = max(DB total_capital, latest_position.isolated_margin)
qty_based     = current_qty × close_ratio
capital_based = (effective_margin × close_ratio × leverage) / avg_entry
close_qty     = min(max(qty_based, capital_based), current_qty)
```
**사장님 명시 의도**: "포지션 + 증거금 포함 전체금액의 25%씩 익절, 수동 추가한 금액 모두 기준"

### 4. total_capital = 마진 단위 (옵션 A — PR #79+#80)
- 사장님 입력 자본 = Binance lock 마진 (notional X)
- 거래 규모 = `total_capital × leverage` (별도 표시)
- 모든 계산식 = total_capital (마진 단위) 기준

### 5. 사장님 노력 영구 보호
- 증거금/포지션 추가 (시스템 통과) → total_capital 자동 합산 (PR #56)
- 사장님 Binance UI 직접 추가 → reconcile 30초 자동 동기화 (PR #84)
- SL 한도 + TP 청산 = 자본 변경 자동 반영 (PR #57, #87+#88)

---

## 🔒 보안 강화

| 항목 | PR | 적용 |
|---|---|---|
| HTTPS 자동 적용 | #70 | nginx 1.24 + self-signed (10년) + HTTP→HTTPS redirect + 보안 헤더 |
| Neon DB password 회전 | 6-03 사고 | 옛 password 무효화 + 새 .env + 모든 컨테이너 force-recreate |
| API key 인증 정기 검증 | #73 | 30분 주기 + 실패 시 즉시 Telegram |
| Hedge Mode 자동 가드 | #50 | 신규 계정 등록 시 자동 검증 |
| Frontend testnet 하드코드 제거 | #61 | mainnet 사고 차단 |
| Sentry silent error | #9 | 실시간 자동 capture + 알림 |

---

## ✅ 데이터 정확성 (Critical Fix)

| PR | 변경 | 영향 |
|---|---|---|
| #26 | stage_trigger_worker — STAGE_OPEN_PENDING 인식 | mainnet 첫날 자동 진입 실패 fix |
| #32 | WebSocket `/ws` → `/private/ws` | user-stream ORDER_TRADE_UPDATE 수신 (4-23 deadline) |
| #74 | WebSocket user-stream URL = query string | Binance 신 권장 형식 |
| #75 | mark-price `/stream` → `/market/stream` | Binance 신 endpoint |
| #45 | qty race fix (ACCOUNT vs ORDER_TRADE) | 중복 차감 방지 |
| #47 | commission realized_pnl 즉시 차감 | gross → net 정확 |
| #49 | reconcile Orders 외부 cancel 감지 | DB ↔ 거래소 정합 |
| #82 | StrategyDetailResponse.exchange_account_id 추가 | Binance 비교 행 표시 (사장님 6-02 핵심 해결!) |
| #43 | 통계 분류 fix | 진입실패/수동손절/자동손절 정확 카운트 |

---

## 🎨 UI / UX (사장님 직접 사용)

| PR | 변경 |
|---|---|
| #39+#42+#82 | Binance 비교 인라인 행 (전략 행 아래 실시간 비교) |
| #67 | 「💼 거래소 계정」 모달 (잔액/활성/마진) |
| #69+#71 | 다중 Sub-Account 등록 폼 + 활동/전략 계정 필터 |
| #72+#77 | 잔액 카드 3구간 분해 (🔒 실 / 📦 예약 / 💵 자유) + 다중 계정 합산 |
| #64 | 「전략 인스턴스」 SL 한도 시각화 (회/노/주/빨강 4단계) |
| #65 | 「전략 인스턴스」 정렬 옵션 (7가지) |
| #66 (v2) | 수량/마진 컬럼 바이낸스 스타일 단순화 |
| #48 | TP/SL UI ROI 명시 + 동적 USDT 손실 미리보기 |
| #41 | 심볼 클릭 → Binance 차트 새 탭 |
| #40 | Static cache 영구 해결 (NoCacheStaticFiles + cache buster) |

---

## 🔧 신규 worker / API endpoint (개발 시 참고)

### Worker (scheduler 안)
- `sync_health_monitor` — 5분
- `endpoint_health_monitor` — 30분 (API auth 포함)
- `realized_pnl_sync_worker` — 1분
- `daily_summary_worker` — 매일 KST 00:00
- `binance_changelog_monitor` v2 — 6시간
- `reconcile_worker` — 30초 (자본 자동 동기화 통합)

### API endpoint (신규)
- `GET /api/v1/exchange-accounts/{id}/balance` — 잔액 3구간 (PR #72)
- `GET /api/v1/exchange-accounts/{id}/binance-positions` — Binance 비교용 (PR #39, 30초 캐시)
- `POST /api/v1/strategies/{id}/acknowledge-manual-cleanup` — 수동 청산 ack
- `GET /api/v1/admin/recent-activity` — N+1 fix (PR #89, selectinload)
- `GET /api/v1/admin/notifications-by-title` — N+1 fix (PR #89 v2)

### Schema 변경
- `StrategyDetailResponse.exchange_account_id` 추가 (PR #82) ⭐ 핵심
- `stop_loss_percent_of_capital` 추가 (PR #57)

---

## ⚡ 코드 최적화 발견

### Sentry 자동 발견 (적용 5분 만에)
- **N+1 Query** (recent-activity + notifications-by-title)
- Fix: `selectinload` eager load (PR #89)
- 영향: 폴링 21 쿼리 → 2 쿼리 (95% 감소)

### Sentry 향후 모니터링 대상
- API timeout / 5xx
- WebSocket 끊김 자동 재연결
- Worker 예외 (silent except)

---

## 🌐 다중 Sub-Account 운영 시스템

- Binance Sub 한도: VIP 0 = 200개
- VPS 효율 한도: N = 10개 (2vCPU/8GB)
- 「💼 계정」 모달 — 통합 표시 (PR #67)
- 잔액 카드 = 다중 계정 합산 + tooltip 개별 (PR #72)
- 「전략 인스턴스」 + 「최근 활동」 = 계정 필터 (PR #69, #71)
- 신규 등록 = 모달 내 직접 + PR #50 자동 검증 (Hedge mode + IP whitelist + Futures 권한)

---

## 📋 향후 우선순위 (다음 세션)

### 큰 작업
1. **#21** 메인 계정 「읽기 전용 모드」 (다중 Sub 통합 모니터링)
2. **#22** 심볼별 차트 + Order Book + 수동 거래 UI

### 운영
3. Sentry DSN 회전 (대화 노출)
4. EPICUSDT 자본 결정 (사장님)
5. Sub-Account 추가

### 신규 spec
6. **CODE_OPTIMIZATION_PLAN.md** — Phase 4 작성

---

## 🚨 향후 개발 시 주의사항 (사장님 사상 보존)

1. **사장님 사상 변경 X** — total_capital 의미, SL/TP 정책 등 = 사장님 명시 후만 변경
2. **자본 단위 통일** — 모든 계산 = total_capital (마진 단위) 기준
3. **N+1 패턴 주의** — `.strategy_instance.` 같은 lazy load = `selectinload` 강제
4. **Sentry 자동 모니터링** — silent error 발생 시 Sentry 대시보드 매일 확인
5. **사장님 직접 사용 endpoint** — 신중 (잔액/strategy/account 등 = 사장님 매일 사용)
6. **TP/SL 변경 시 사장님 사상 PR #57+#87+#88 우선** — 코드보다 사장님 의도 우선

---

> 이 spec update = 6-01 mainnet 진입 후 53+ task 의 통합 정리.
> 기존 spec (SYSTEM-SPEC, DEVELOPMENT_SPEC, TP_TRAILING) = audit 보존.
> 다음 세션 = CODE_OPTIMIZATION_PLAN.md 신규 작성 (Phase 4).
