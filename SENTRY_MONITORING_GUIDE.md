# 🔔 Sentry Monitoring 활용 가이드

> **작성일**: 2026-06-05 (Phase 4 Step 2)
> **목적**: Sentry 적용 후 사장님이 활용할 모니터링 + 추가 instrumentation 가이드.

---

## ✅ 현재 자동 적용 (PR #9)

### FastApiIntegration — 모든 HTTP endpoint 자동 측정
- 모든 API 호출 = transaction 자동 생성
- P50 / P95 / P99 응답 시간 자동 추적
- HTTP 에러 (4xx/5xx) 자동 캡쳐
- request URL + method + status code 자동 tag

### SqlalchemyIntegration — 모든 DB query 자동 측정
- 각 query 의 실행 시간
- Slow query 자동 감지 (Sentry Performance Issues)
- **N+1 Query 자동 감지** (PR #89 발견 사례)
- DB connection pool 메트릭

### 샘플링 (.env)
```
SENTRY_TRACES_SAMPLE_RATE=0.1     # 10% 측정 (cost 절감)
SENTRY_PROFILES_SAMPLE_RATE=0.0   # 0% (불필요)
```

---

## 🎯 사장님 매일 확인 권장 (Sentry 대시보드)

### URL: https://binance-auto-trader.sentry.io/issues/

### 1. **Issues** 탭 — silent error 발견
- 신규 issue (New) = 즉시 대응
- Frequency 높은 issue = 우선순위 ↑
- Tag 필터: `event_type:USER_STREAM_CRASH`, `strategy_id:23` 등

### 2. **Performance** 탭 — 응답 속도 모니터링
- 핵심 endpoint = `/api/v1/strategies` (사장님 폴링)
- Slow endpoint (P95 > 500ms) = 최적화 후보
- Throughput 그래프 = 사장님 사용 패턴

### 3. **Performance Issues** 탭 — 자동 발견 (Sentry 특화)
- N+1 Query (이미 PR #89 fix)
- Slow DB query
- Uncached HTTP request
- Consecutive HTTP

---

## 🚀 Worker Custom Transaction (선택 사항 — 다음 PR 후보)

FastAPI Integration = HTTP 만 자동. **Worker cycle** = custom transaction 필요.

### 핵심 Worker (측정 권장):

#### 1. reconcile_worker (30초 주기)
```python
import sentry_sdk

def _do_reconcile(decrypt_func) -> None:
    with sentry_sdk.start_transaction(op="worker", name="reconcile_worker.cycle"):
        # 기존 로직
        ...
```

#### 2. sync_health_monitor (5분 주기)
```python
def run_sync_health_monitor_once() -> None:
    with sentry_sdk.start_transaction(op="worker", name="sync_health_monitor.cycle"):
        ...
```

#### 3. tp_sl_orchestrator (TP/SL 평가 사이클)
```python
def evaluate_tp_sl(strategy: StrategyInstance) -> None:
    with sentry_sdk.start_transaction(
        op="worker", name="tp_sl_orchestrator.evaluate"
    ) as transaction:
        transaction.set_tag("strategy_id", strategy.id)
        transaction.set_tag("symbol", strategy.symbol)
        ...
```

#### 4. stage_trigger_worker (단계 진입 평가)
```python
def run_stage_trigger_once() -> None:
    with sentry_sdk.start_transaction(op="worker", name="stage_trigger.cycle"):
        ...
```

### 효과
- Sentry Performance 에 worker 별 응답 시간 표시
- worker 의 slow 사이클 자동 감지
- 사장님 운영 안정성 가시화

---

## 📊 Sentry 알림 룰 (사장님 권장)

### 현재 (Sentry default)
- 모든 issue = email 알림

### 권장 변경 (Sentry → Alerts → New Alert Rule)

#### Critical (즉시 대응 필요)
- **조건**: 오류율 > 5% (1분 윈도우) OR 신규 critical issue
- **알림**: Telegram (즉시) — Slack/Discord integration 또는 webhook
- **예**: API 서버 다운, DB 연결 실패, Binance API ban

#### Warning (일 1회 summary)
- **조건**: Slow query (P95 > 1초) OR N+1 발견 OR worker crash
- **알림**: Email daily digest

#### Info (주 1회 summary)
- **조건**: 모든 새 issue, transaction trend
- **알림**: Email weekly summary

---

## 🎯 Performance Baseline 설정 (1주일 모니터링)

### Week 1 측정 후 결정
1. **`/api/v1/strategies` 폴링 P95** = ? ms
2. **`/api/v1/exchange-accounts/{id}/balance` P95** = ? ms
3. **`/api/v1/exchange-accounts/{id}/binance-positions` P95** = ? ms
4. **`/api/v1/admin/recent-activity` P95** = ? ms (N+1 fix 후)

### 목표 (CODE_OPTIMIZATION_PLAN.md)
- 사장님 대시보드 응답 시간 = P95 < 300ms
- DB query / API = 평균 < 5

### Baseline 보다 느린 endpoint = 다음 최적화 우선순위

---

## 📋 사장님 매일 1분 routine

1. https://binance-auto-trader.sentry.io/issues/ 접속
2. **Issues** 탭 — 신규 issue 0건 ✅ 확인
3. **Performance** 탭 — P95 그래프 정상 ✅ 확인
4. 빨강 알림 있으면 = 즉시 조치 (보통 = 우리 분석 + fix PR)

---

## 🔧 Sentry 비용 관리

### 무료 한도 (Developer plan, 14일 trial 후)
- **5,000 errors / month** (사장님 운영 충분)
- 30일 이벤트 보관

### 한도 초과 시
- `SENTRY_TRACES_SAMPLE_RATE` = 0.1 → 0.05 (절반)
- `before_send` 에서 추가 noisy event 필터링
- 또는 Team plan ($26/mo, 50K errors)

### 절약 팁
- Health check / metrics endpoint = `before_send` 에서 skip (이미 PR #9 적용)
- 401/403/404 = skip (이미 적용)
- BinanceAPIError "Idempotency-Key reused" = skip (이미 적용)

---

## 🚨 사장님 직접 작업 (오늘 6-05 완수 후)

### 1. Sentry 대시보드 첫 방문
- URL: https://binance-auto-trader.sentry.io/issues/
- 이미 자동 캡쳐된 N+1 + 사장님 테스트 메시지 확인

### 2. Alert Rule 설정 (10분)
- Settings → Alerts → New Alert Rule
- Critical 룰 = 위 권장 사항 적용

### 3. DSN 회전 (5분, 대화 노출)
- Settings → Projects → binance-auto-trader → Client Keys (DSN)
- Generate New Key → 옛 키 Disable
- VPS `.env` 의 `SENTRY_DSN` 새 키로 교체

---

## 📋 다음 세션 우선순위 (Step 3, 4, 5)

### Step 3 — `/strategies` Redis 캐싱 (1시간)
- TTL 3초 (사장님 5초 폴링)
- invalidation: strategy 변경 시
- 효과: DB query 90% 감소

### Step 4 — DB 인덱스 (Sentry P95 측정 후)
- Sentry slow query 발견
- alembic migration

### Step 5 — Multi-Sub 병렬 (사장님 Sub 증가 시)
- asyncio.gather
- 계정별 병렬 fetch

### Worker Custom Transaction (선택)
- reconcile_worker, sync_health_monitor, tp_sl_orchestrator
- Sentry Performance 에 worker 가시화

---

> 이 가이드 = 6-05 Sentry 적용 후 사장님 활용 + 다음 단계 안내.
> FastApiIntegration + SqlalchemyIntegration 이미 적용 — **사장님 대시보드 매일 1분 확인** 만으로 silent error 즉시 인지!
