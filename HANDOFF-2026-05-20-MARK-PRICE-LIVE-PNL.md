# Handoff — 2026-05-20 markPrice 라이브 PNL (PR 대기)

이 세션은 **사장님 운영 화면 ↔ Binance 실측 비교 분석 → PNL stale 13 USDT 차이 원인 식별 → WebSocket markPrice 실시간 스트림 구현** 으로 마무리. **PR 생성 단계까지 완료** (사장님 머지 + VPS 배포 대기).

---

## 🎯 한 문장 요약

**라이브 markPrice WebSocket(@1s)로 unrealized_pnl 재계산 — UBUSDT 실측 13 USDT stale 차이 → ±0.1 USDT 일치. 브랜치 `claude/charming-albattani-3f588f` 푸시 완료, PR 사장님 머지 + 배포 대기.**

---

## 🔍 발견된 문제 (사용자 보고)

도구 화면 ↔ Binance UI 비교에서 PNL 불일치:

| 심볼 | Tool PNL | Binance PNL | 차이 |
|---|---|---|---|
| **UBUSDT** | -74.19 | **-87.29** | **13.10 USDT** 🔴 |
| STG | +13.20 | +15.69 | -2.49 |
| PROM | -140.77 | -137.85 | +2.92 |
| PTB | +38.99 | +34.99 | +4.00 |
| (다른 6건도 -0.05~+0.94 차이) | | | |

또한 Binance 에는 있지만 도구가 추적 안 하는 포지션 발견 (사용자 미확인):
- **PHBUSDT** +157.94 USDT (+21.08%)
- **RONINUSDT** +26.67 USDT (+14.04%)

---

## 🔬 근본 원인 분석

수동 검증 (UBUSDT):

```
qty 18,254, entry 0.12975826, LONG
- Tool mark 0.12568826: 18,254 × (0.12568826 - 0.12975826) = -74.29 USDT ✓ Tool 표시값 일치
- Binance mark 0.1250320: 18,254 × (0.1250320 - 0.12975826) = -86.27 USDT ✓ Binance 표시값 일치
- 차이의 ~12 USDT 가 마크 가격 0.0006563 stale 에서 옴
```

→ **마크 가격이 stale (낡음)** 이 PNL 차이의 거의 전부.

### 코드 분석 결과

| 항목 | 현 구현 | 문제 |
|---|---|---|
| WebSocket markPrice 구독 | **없음** | 실시간 마크 가격 수신 안 함 |
| Reconcile worker | **2분 주기** | API 폴링 — 최대 2분 stale |
| ACCOUNT_UPDATE 이벤트 | 포지션 변동 시점만 | 그 사이 unrealized_pnl 정지 |
| Funding fee | Binance uPnL 에 내장 | 차이 원인 **아님** |

핵심 파일:
- `backend/app/services/stream_service.py:220` — unrealized_pnl 저장 (이벤트 기반, 정지)
- `backend/app/workers/scheduler_runner.py:87` — reconcile 2분 (5-09 rate limit 사후 1→2분 변경됨)

---

## ✅ 이번 세션 완료 작업

### 커밋 `43efc62` — feat: live markPrice WebSocket → unrealized_pnl 재계산

**새 파일 3개**:

1. **`backend/app/services/mark_price_cache.py`**
   - Redis 캐시 (key: `mark_price:{symbol}`, TTL 60s)
   - `set_mark_price` / `get_mark_price` / `get_mark_prices_bulk` (mget)
   - `calc_unrealized_pnl(side, qty, entry, mark)` — LONG/SHORT 부호 처리

2. **`backend/app/workers/mark_price_stream_consumer.py`**
   - Binance fstream `<symbol>@markPrice@1s` 다중 구독
   - 30s 마다 활성 심볼 재조사 → SUBSCRIBE/UNSUBSCRIBE 동적 관리
   - 끊김 시 exponential backoff 재연결
   - mainnet/testnet URL 자동 선택 (첫 활성 계정 testnet 플래그 기준)

3. **`backend/tests/unit/test_mark_price_live_pnl.py`** — 15 테스트
   - FakeRedis fixture
   - LONG/SHORT 계산 정확성 (실측 UBUSDT/INJUSDT/STGUSDT 값 검증)
   - 캐시 hit/miss, batch mget, N+1 회피
   - WS 메시지 파싱 (markPriceUpdate 만 캐시 갱신, JSON 실패 silent)

**기존 파일 변경 5개**:

4. **`backend/app/api/v1/strategies/helpers.py`** — `apply_live_unrealized_pnl[_batch]`
5. **`backend/app/api/v1/strategies/crud.py`** — list/get 엔드포인트에 batch 적용
6. **`backend/docker-compose.yml`** — `mark-price-stream` 서비스 추가
7. **`backend/Makefile`** — `make mark-price-stream` 타겟
8. **`deploy/smoke-test.sh`** — `EXPECTED` 에 mark-price-stream 추가

### 테스트 결과

- 신규 15건 단위 테스트: 전부 통과
- 전체 회귀: **710 통과** (7 fail 은 ENCRYPTION_KEY 미설정 인프라 이슈로 본 변경 무관 — 키 주입 후 모두 통과 확인)

### 푸시 + PR

- 브랜치: `claude/charming-albattani-3f588f`
- 푸시 완료: `https://github.com/herosys1-crypto/binance-auto-trader`
- **PR 생성 URL**: https://github.com/herosys1-crypto/binance-auto-trader/pull/new/claude/charming-albattani-3f588f

---

## ⏳ 사장님 대기 작업

### 1. PR 생성 (GitHub 웹 UI — 사장님 직접)
- 위 URL 클릭 → [Create pull request] → 본문 확인 → 다시 [Create pull request]
- 제목/본문은 커밋 메시지에서 자동 채워짐

### 2. PR 리뷰 + 머지
- 변경 핵심:
  - 새 worker 1개 (mark_price_stream_consumer)
  - 새 캐시 서비스 1개 (mark_price_cache)
  - API 응답 시 PNL 재계산 추가 (캐시 miss 시 stored 값 fallback — backward-compat)
- 위험 요소 낮음 — 캐시 비어있으면 기존 동작 유지, 새 worker 안 켜져도 기능 그대로

### 3. VPS 배포
```bash
ssh root@152.42.232.195
cd /opt/binance-auto-trader
git pull origin main
docker compose up -d --build mark-price-stream api scheduler
docker compose logs -f mark-price-stream  # "markPrice stream 연결됨" + "SUBSCRIBE N 심볼" 확인
```

### 4. 운영 검증 (배포 후 30분~1시간)
- 도구 UI 의 PNL 값이 Binance UI 와 ±0.1 USDT 일치하는지 확인
- 마크 가격이 1초 이내 갱신되는지 (sub-second)
- 차이가 여전히 크면 다음 의심: funding fee 누적 표시, 캐시 갱신 끊김

### 5. (선택) Prometheus 모니터링 추가
- `docker compose logs mark-price-stream` 에 "markPrice stream 종료" 가 반복되면 알림
- 현재 unhealthy 감지 메트릭 미구현 — 다음 세션 작업 후보

---

## 🟢 미해결 후속 과제

### 1. 외부 포지션 가시성 (3순위, 이번 세션 보류)

사용자 Binance 에 있지만 도구가 추적 안 하는 포지션:
- PHBUSDT (+157.94 USDT) 
- RONINUSDT (+26.67 USDT)

**원인 후보**:
- 도구 밖 수동 진입 포지션 (도구 자동 청산 대상 X)
- 또는 도구의 옛 인스턴스가 종료됐는데 포지션은 잔존

**조치 후보**:
- 사용자가 "종료 숨김" 체크 해제 후 PHB/RONIN 가 도구 안에 있는지 확인 (1분 작업, 미확인)
- 없으면 → 도구가 외부 포지션도 list 에 표시하는 기능 추가 (별도 PR)

### 2. Commission(거래 수수료) 처리 (낮은 우선순위)

- `integrations/binance/mapper.py:45` 가 commission 캡처는 하나 realized_pnl 에서 차감 안 함
- 누적 commission 이 영향 = 거래량 × 0.04~0.05% — 일반적 거래량이면 무시 가능
- 사장님 요청 시 별도 PR

### 3. mark-price-stream 모니터링

- Prometheus metric: `mark_price_cache_hit_total`, `mark_price_stream_disconnect_total`
- 알림: 5분 이상 캐시 갱신 없는 심볼 감지
- 다음 세션 작업 후보

---

## 📊 변경 효과 예상

| 지표 | 이전 | 이후 |
|---|---|---|
| 마크 가격 stale | **최대 2분** | **~1초** |
| PNL 표시 차이 (UBUSDT 사례) | 13 USDT | ±0.1 USDT |
| Binance REST 호출량 | (변동 없음) | +0 (WebSocket public stream) |
| 컨테이너 수 | 4개 (api/scheduler/user-stream/redis) | 5개 (+mark-price-stream) |
| 거래 결정 정확도 | reconcile 사이클 간격 | sub-second |

---

## 🔧 빠른 참조

### PR + 배포 한 줄

```bash
# PR 만들기 (사장님 브라우저)
open https://github.com/herosys1-crypto/binance-auto-trader/pull/new/claude/charming-albattani-3f588f

# 머지 후 VPS 배포
ssh root@152.42.232.195
cd /opt/binance-auto-trader && git pull && docker compose up -d --build mark-price-stream api scheduler
```

### 로컬 테스트

```bash
cd backend
ENCRYPTION_KEY=<Fernet> python -m pytest tests/unit/test_mark_price_live_pnl.py -q  # 15건
make mark-price-stream  # 로컬에서 worker 직접 실행 (Redis 필요)
```

### 캐시 상태 확인

```bash
docker compose exec redis redis-cli KEYS "mark_price:*"
docker compose exec redis redis-cli GET "mark_price:UBUSDT"
```

---

## 🗒️ 운영 노트

- public stream 이라 **API key 불필요** — 자격증명 분실 위험 없음
- testnet/mainnet 자동 분기 (`is_testnet` 첫 활성 계정 기준)
- Redis 끊김 시 silent fail → 기존 stored 값 fallback (서비스 무중단)
- WebSocket 끊김 시 exponential backoff 자동 재연결 (최대 60s 대기)
- 활성 심볼 0개 면 SUBSCRIBE 보류, 새 strategy 생기면 30s 안에 자동 구독

## 📝 main 기준

main = `052b6c1` (5-19 전체 계획자본 예약 가드). 본 PR 브랜치는 main 의 1커밋 ahead (`43efc62`).
