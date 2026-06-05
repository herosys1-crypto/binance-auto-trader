# 📐 코드 최적화 기획서 (Phase 4)

> **작성일**: 2026-06-05
> **배경**: mainnet 운영 6일차 (6-01 진입 ~ 6-05) + 53+ task 완료 + Sentry 적용 5분 만에 첫 silent issue (N+1 Query) 자동 발견.
> 이 시점 기준 backend 117 Python 파일 + 18 worker + 87 Redis 호출. 운영 안정성 + 사장님 응답 속도 + DB 비용 최적화 위한 종합 기획.

---

## 🎯 목표 + KPI

| 지표 | 현재 (6-05 기준 추정) | 목표 | 측정 |
|---|---|---|---|
| **사장님 대시보드 응답 시간** | ~500ms (폴링) | < 300ms | Sentry Performance |
| **DB 쿼리 수 / API 호출** | 평균 5~20 (N+1 잔여) | < 5 | Sentry N+1 detection |
| **Redis cache hit rate** | ~60% (추정) | > 85% | Redis INFO |
| **Binance API 호출 / 분** | ~30 (다중 계정) | < 20 | endpoint_health logs |
| **사장님 silent error 발견 시간** | 사장님 수동 확인 (시간) | < 5분 (Sentry 자동) | Sentry alert |
| **N+1 Query 발생** | 1건 (recent-activity) | 0건 | Sentry N+1 |

---

## 📊 현재 시스템 측정 결과 (Sentry + 코드 검토 기반)

### Backend 구조
- **117 Python 파일** (app/)
- **18 Worker** (app/workers/)
- **87 Redis 호출** (services/workers, get_redis_client 등)
- **23개 DB 모델** (app/models/)
- **다수 API endpoint** (FastAPI router)

### Sentry 발견 (적용 5분)
- **N+1 Query** in `/api/v1/admin/recent-activity` (PR #89 fix)
- **N+1 Query** in `/notifications-by-title` (PR #89 선제 fix)

### 운영 부담 추정 (Neon Cloud)
- 사장님 대시보드 폴링 = 5초 주기 = 720 회/시간
- 활성 strategy 2개 = limit 20 = 폴링 당 ~20 쿼리 (N+1 fix 후)
- 24h 폴링 = 17,280 × 5 ~ 86,400 쿼리/일 (수많은 endpoint 합산)

---

## 🚀 최적화 영역 6가지 (우선순위)

### 🔴 영역 1 — DB Query 최적화 (HIGH ROI)

#### 1.1 N+1 Query 잔여 검색 + 선제 fix
**현재 상태**: PR #89 = 2개 fix (recent-activity, notifications-by-title). 더 있을 가능성.

**검색 대상** (lazy load 패턴):
```python
# 의심 패턴 — 매 row 별 추가 SELECT 위험
for x in db.execute(select(SomeModel).limit(N)).scalars().all():
    val = x.some_relationship.attr   # ← 의심!
```

**액션**:
1. backend grep — `.strategy_instance.` `.template.` `.exchange_account.` 등
2. 모든 location 확인 → `selectinload` 또는 `joinedload` 추가
3. Sentry "N+1" 자동 감지 활용 (1주일 모니터링)

**우선순위**: 🔴 HIGH (즉시) — 95% 쿼리 감소 가능 (PR #89 사례)

#### 1.2 DB 인덱스 추가 검토
**현재 인덱스** (alembic 추정):
- `strategy_instances.status` (자주 filter)
- `orders.strategy_instance_id` + `orders.created_at`
- `risk_events.strategy_instance_id` + `created_at`
- `notifications.strategy_instance_id` + `created_at`

**누락 가능성**:
- `notifications.title` (LIKE 검색용 — `/notifications-by-title`)
- `strategy_instances.exchange_account_id` (다중 계정 필터)
- `strategy_instances.is_archived` + `status` 복합 인덱스

**액션**:
1. PostgreSQL `EXPLAIN ANALYZE` 로 slow query 발견
2. 필요한 인덱스 추가 (alembic migration)
3. Sentry Performance 의 P95 응답 시간 모니터링

**우선순위**: 🟡 MEDIUM — Sentry P95 측정 후 결정

#### 1.3 Batch Query (반복 호출 한 번에)
**예시 패턴**:
```python
# 비효율 — 각 account 별 1번 호출
for account_id in active_account_ids:
    balance = api.get_balance(account_id)

# 효율 — 한 번에 모두
balances = api.get_balances_batch(active_account_ids)
```

**적용 대상**:
- Binance positions fetch (현재 = 계정별 호출)
- Strategy 별 unrealized_pnl 갱신

**우선순위**: 🟢 LOW — 다중 계정 (10개) 시 효과 큼, 현재 2-3개 = 부담 작음

---

### 🟡 영역 2 — Redis 캐싱 전략

#### 2.1 현재 캐시 사용 패턴 (PR #46 + others)
- `mark_price:{symbol}` (TTL 60s) — mark price stream
- `balance:{account_id}` (TTL 15s) — accountInfo
- `binance_positions:{account_id}` (TTL 30s) — 비교 행
- `ensure_isolated_margin:{strategy_id}` (TTL 1h) — weight 절감
- `api_backoff:account:{id}:ban_until_ms` — ban 마커
- `binance_changelog:hash:{name}` (TTL 30d) — docs 모니터
- `health:user_stream:connected` (TTL 60s) — heartbeat

#### 2.2 추가 캐싱 대상
| 대상 | 현재 | 권장 TTL | 영향 |
|---|---|---|---|
| **`/strategies` 응답** | 매 폴링 = DB query | 3초 (사장님 5초 폴링) | DB 부담 ↓ 90% |
| **`/admin/stats`** | 매 호출 = aggregate query | 30초 | DB 부담 ↓ |
| **Binance symbol filters** | 매 strategy 생성 = API 호출 | 1h (변경 거의 X) | Binance weight ↓ |
| **Account info (account_kill_switch)** | 매 평가 사이클 | 5초 | 동시성 안전 |

#### 2.3 캐시 invalidation 패턴
- Strategy 변경 시 = 관련 cache 즉시 삭제
- order fill 시 = unrealized_pnl cache invalidate
- 자본 추가 시 (PR #56) = balance cache invalidate

**우선순위**: 🟡 MEDIUM — `/strategies` 캐싱 = 즉시 가치

---

### 🟢 영역 3 — API 응답 속도

#### 3.1 응답 압축 (gzip)
**현재**: FastAPI 기본 (압축 X 가능)
**권장**: middleware 추가
```python
from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=1000)
```
**효과**: JSON 응답 70% 압축 (사장님 모바일 사용 시 효과 큼)

#### 3.2 응답 페이지네이션
- `/strategies` = limit 없이 모두 반환?
- 사장님 strategy 32건 = 작음, 다만 늘어나면 부담

#### 3.3 Cache-Control 헤더
- Static JS/CSS = NoCacheStaticFiles (PR #40) — 정확
- API 응답 = `Cache-Control: no-store` 명시 (브라우저 캐시 방지)

**우선순위**: 🟢 LOW — 현재 응답 속도 OK, 미래 대비

---

### 🟠 영역 4 — 동시성 / Race Condition

#### 4.1 현재 락 사용 패턴
- `redis_lock(RECONCILE_LOCK_KEY)` — reconcile worker
- `idempotency_key` — emergency_close
- `current_position_qty` race fix (PR #45)

#### 4.2 추가 검토 대상
- **Multi-Sub-Account 운영 시** = 여러 계정 동시 처리
  - sync_health_monitor → 계정별 병렬 fetch (현재 = 순차)
  - daily_summary_worker → 계정별 통계 (현재 = 순차)
- **stage_trigger_worker** = race (이미 PR #26 fix)

**액션**:
1. asyncio 또는 concurrent.futures 적용 검토
2. lock 범위 최소화 (read 시 락 X, write 만)

**우선순위**: 🟡 MEDIUM — 사장님 Sub-Account 늘어날수록 효과 ↑

---

### 🔵 영역 5 — 메모리 사용량

#### 5.1 Worker 메모리 (Docker stats)
**예상**:
- api: ~200MB
- scheduler: ~150MB
- user-stream: ~100MB
- mark-price-stream: ~100MB
- 총 backend: ~550MB / VPS 8GB

#### 5.2 메모리 leak 검토
- SQLAlchemy session 누수 (db.close() 호출 누락)
- WebSocket connection 누적
- Pandas DataFrame 사용 (있다면)

**액션**:
1. `docker stats` 24h 모니터링 (메모리 증가 추세)
2. `tracemalloc` 또는 `memory_profiler` 사용 시 진단

**우선순위**: 🟢 LOW — VPS 8GB 여유 충분

---

### 🟣 영역 6 — Sentry 모니터링 활용 (지속)

#### 6.1 자동 발견 활용
- N+1 Query (PR #89 사례)
- Slow query (P95 > 1초)
- silent exception (capture_strategy_event)
- Worker crash (재시도 횟수)

#### 6.2 사장님 알림 룰
**현재 (Sentry default)**: 모든 issue = email
**개선**:
- Critical (오류율 > 5%) = Telegram 즉시
- Warning (slow + N+1) = 일 1회 summary
- Info = 주 1회 summary

#### 6.3 Custom 측정
```python
# 사장님 핵심 endpoint 응답 시간 측정
with sentry_sdk.start_transaction(name="dashboard.refresh"):
    ...
```

**우선순위**: 🔴 HIGH — Sentry 가치 극대화 (이미 적용됨)

---

## 📊 우선순위 매트릭스 (영향 × 비용)

```
                  영향 ↑
                  │
         🔴 N+1 잔여 검색
              │
   🔴 Sentry 활용 강화
              │
         🟡 /strategies 캐싱
              │
   🟡 DB 인덱스 추가
              │
         🟡 Multi-Sub 병렬
              │
   🟢 gzip 압축
              │
         🟢 메모리 모니터링
              │
   🟢 Batch query (Multi-Sub)
              ───────────────→
                            비용 ↑
```

### 우선순위 정리
1. **🔴 즉시 (다음 세션)**:
   - N+1 잔여 검색 + 선제 fix
   - Sentry custom transaction 추가 (사장님 핵심 endpoint)
2. **🟡 중기 (다음 주)**:
   - `/strategies` Redis 캐싱 (3초 TTL)
   - DB 인덱스 검토 (Sentry P95 측정 후)
   - Multi-Sub 병렬 처리
3. **🟢 장기 (필요 시)**:
   - gzip 압축
   - Batch query
   - 메모리 모니터링

---

## 🎬 실행 계획 (단계별)

### Step 1 — N+1 잔여 검색 (다음 세션 우선)
```bash
# backend 전체 grep
grep -rn "\.strategy_instance\.\|\.template\.\|\.exchange_account\." backend/app/api backend/app/services backend/app/workers
```
- 발견된 모든 위치 = `selectinload` 추가
- PR 작성 + 머지 + 배포

### Step 2 — Sentry Custom Transaction (다음 세션)
- 사장님 핵심 endpoint (dashboard 폴링) 측정
- P95 응답 시간 추적
- 1주일 후 = baseline 결정 + 최적화 우선순위

### Step 3 — /strategies Redis 캐싱 (다음 주)
- TTL 3초 (사장님 폴링 5초 < TTL = cache miss 적음)
- invalidation: strategy 변경 시 (생성/수정/종료)
- 효과: 사장님 폴링 시 DB query 90% 감소

### Step 4 — DB 인덱스 (다음 주)
- Sentry Performance 의 slow query 발견
- `EXPLAIN ANALYZE` 분석
- alembic migration 작성

### Step 5 — Multi-Sub 병렬 (사장님 Sub 증가 시)
- asyncio.gather 적용
- 계정별 병렬 fetch
- 효과: N 개 계정 → 1× 응답 시간 (현재 N×)

---

## 🛡 사장님 안전 마진 (최적화 시 준수)

### 절대 변경 X
1. **사장님 사상** (TP/SL 정책, 자본 의미)
2. **6-layer 안전망** (9-layer 까지 확장됨, 절대 비활성 X)
3. **mainnet API 호출** (rate limit 신중)

### 신중 변경
1. **DB schema** (alembic migration + 사장님 백업)
2. **cache TTL** (너무 길면 stale data 위험)
3. **Worker 주기** (변경 시 사고 가능)

### 자유 변경
1. **UI 표시** (사장님 의도 일치 시)
2. **로깅** (Sentry 캡쳐 강화)
3. **테스트** (회귀 방지)

---

## 📋 다음 세션 시작 시 우선순위 (자동 로드)

### 코드 최적화 우선
1. ⭐ **N+1 잔여 검색** (위 Step 1) — 30분
2. **Sentry custom transaction** (위 Step 2) — 30분
3. **/strategies Redis 캐싱** (위 Step 3) — 1시간

### 운영 작업
4. 사장님 직접: PR #89 머지 + Sentry DSN 회전
5. 큰 작업: #21 메인 계정 「읽기 전용 모드」 or #22

---

## 🎯 KPI 측정 일정

- **1주일 후**: Sentry P95 응답 시간 baseline 설정
- **2주일 후**: N+1 잔여 0건 확인 + Redis cache hit rate 80%+
- **1개월 후**: 다중 Sub-Account 5+ 운영 시 = 응답 시간 < 500ms 유지

---

> 이 기획서 = 6-05 시점 backend 117 파일 + 18 worker + 87 Redis 호출 기준.
> 사장님 mainnet 운영 안정성 + 응답 속도 + DB 비용 최적화 종합 계획.
> 우선순위 따라 단계별 진행 + Sentry 측정 + 사장님 검증.
