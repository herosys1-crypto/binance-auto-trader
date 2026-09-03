---
name: 2026-08-26-ip-ban-spiral
description: 🚨 진짜 Binance IP ban(418) — 워커들이 ban 중에도 계속 호출해 ban 을 스스로 무한 연장. Fix 115/116/117. 헌법 94~96.
metadata: 
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
  modified: 2026-08-26T07:14:08.628Z
---

# 🚨 IP ban 자가 연장 스파이럴 (2026-08-26)

**증상 (사장님)**: 단계별 진입 X / 증거금 추가 X / 지정가 추가 X (수동 시장가만 잠깐 됨)
→ 나중엔 **UI 수동 진입까지** 같은 오류로 실패

```
status=418, code=-1003, msg=Way too many requests;
IP(159.65.137.250) banned until ...
```

## 핵심 = ban 이 계속 밀렸다 (시스템이 스스로 연장)

`06:08:43 → 06:28:43 → 06:30:44 → 06:34:47 → 06:45:29`

Binance 는 **ban 기간 중의 요청도 카운트**해서 ban 을 연장/승격한다.

**왜 기존 가드가 못 막았나**: 워커는 루프 **시작 전 1회만** `is_account_banned()` 를 본다.
루프 도중 ban 이 걸리면 33개 심볼을 끝까지 두드린다.
`peak_break_reversal_worker._get_15m_high` 가 418 예외를 **삼키고 None 반환** → 다음 심볼로 진행.
실측 로그: **2초에 18회 호출**.

## 🎯 Fix 116 (`f5a70e7`) — 클라이언트 전역 회로 차단기

워커 20개를 각각 고치는 대신 **네트워크 나가기 직전 한 곳**에서 차단 (헌법 6):
- `BinanceClient._request` 진입 시 IP ban 이면 **네트워크 없이** 즉시 `BinanceAPIError(418)`
- 418/429 응답에서 `banned until <ms>` 파싱 → 전역 마킹 (없으면 보수적 60s)
- **418 은 계정이 아니라 IP ban** → 전역 키. 1차 프로세스 메모리 / 2차 Redis(컨테이너 공유)
- Redis 조회는 ban 아닐 때만 5s 쓰로틀, 장애 시 60s 백오프
- 검증: ban 중 200회 조회 0.0000s (Redis·네트워크 접근 0)

**복구 절차** (요청을 0으로 만들고 기다리는 게 유일한 해법):
```bash
# ban_until 을 미리 심어 재시작 직후부터 요청 0
docker compose exec redis redis-cli SET "api_backoff:ip:ban_until_ms" <ban_until_ms> EX 1800
docker compose restart api scheduler
# 확인: suppressed locally > 0 이고 "Way too many requests" == 0 이면 정상
docker compose logs scheduler --since 3m | grep -c "suppressed locally"
docker compose logs scheduler --since 3m | grep -c "Way too many requests"
```

## 🎯 Fix 115 — 해제 수단이 아예 없었음

`reset_api_ban()` 함수는 존재하는데 **호출하는 곳이 어디에도 없었다.**
- `GET /admin/diagnostic/api-ban` — 계정/IP ban 상태 + 원인 + 남은 시간
- `POST /admin/diagnostic/api-ban/reset` — 강제 해제 (계정 ban + IP 차단기 동시)
- ban 원인을 `api_backoff:account:{id}:cause` 에 보존 (옛: 텔레그램으로만 = 놓치면 끝)
- ⚠️ reset 은 **오탐일 때만**. 실 418 중 해제하면 ban 이 다시 연장된다.

## 🎯 Fix 117 (`8fc11ce`) — 원인 제거: weight 40 티커 공유 캐시

실측: interval job **41개 / 시간당 2,276 실행**. (중복 등록은 없음)
`get_24hr_ticker()` **symbol 없는 전체 조회 = weight 40** 을 **12개 워커가 각자** 호출,
그중 30초 주기 3개(`unified_15m_entry`/`auto_long_at_bottom`/`realtime_reentry`)
→ 약 **240 weight/분** (한도 2,400/분).

fix = `BinanceClient.get_24hr_ticker(symbol=None)` 에 Redis 공유 캐시 TTL 30s.
symbol 지정 호출은 캐시 X (정확도 유지). → 티커 weight **240 → 최대 80/분**.

⚠️ 내 Fix 111b 가 `confirm_peak`(15m+4h kline)을 생산자 2곳에 추가해 부하를 **늘렸다**.
`ChartAnalyzer.analyze_timeframe` 이 Redis kline 캐시(15m 60s/4h 300s)를 쓰고
24h 급등락 필터 **뒤에** 배치돼 대상 심볼이 적은 게 완화 요인.

## 📊 실측 확정 (Fix 118 계측 + 15 에이전트 정적 분석)

| 시점 | 측정 | 해석 |
|---|---|---|
| ban 중 | 391 klines/분 | ❌ **과소평가** — 워커가 첫 호출 실패 후 조기 종료 |
| ban 해제 직후 | 1,390 klines/분 = "122%" | ❌ **과대평가** — klines weight 를 2로 잡음 (실제 limit≤100 = **1**) |
| 정확 계측 후 | **479 weight/분 = 20%** (한도 2400) | ✅ 확정 |
| 정적 분석 15 에이전트 | **606 weight/분 = 25%** | ✅ 실측과 일치 |

→ **워커 주기·심볼 수를 줄일 필요 없음.** 캐시(117/122)로 충분.
   가장 무거운 워커 순: `auto_long_at_bottom` 194 / `realtime_reentry` 88 / `unified_15m` 82 w/분

## ⚠️ 내가 만든 안전장치가 오히려 해가 된 사례 3건 (전부 감사가 발견)

1. **Fix 119** — 차단기 합성 예외에 `status=418 code=-1003` 이 들어 있어
   `parse_rate_limit_error` 가 새 rate limit 으로 오인 → 계정 ban 을 60s 씩 자가 갱신.
   → `BinanceAPIError.locally_suppressed` 플래그로 「거래소 신호만 신뢰」.
2. **Fix 127** — 거버너가 `_add_weight` 를 판정 **앞**에서 호출 → **차단된 요청까지 누적** →
   부풀고 → 더 차단하고 → 더 부푸는 악순환. 실사용 19%인데 **스캔 18%(274건)를 오차단**.
   → 차단 시 weight 되돌림 (`sign=-1`). 검증: 누적값 == 실제 전송 건수.
3. **Fix 126** — `get_redis_client()` 가 **호출마다 새 연결 풀** 생성.
   Fix 118/122/124 를 요청당 경로에 넣어 요청 1건당 Redis 연결 3~4개 →
   분당 수천 TCP 연결. → 프로세스 싱글턴 + 1.5s 타임아웃.

## ⚠️ Fix 128 — Fix 113 청산가 산출의 즉시발주 위험 2건

- `last_liquidation_price` 는 **과거에 청산된 가격** (`stream_service:253`).
  활성 포지션의 현재 청산가가 아님 → `Position.liquidation_price` 만 신뢰,
  과거값은 `LIQUIDATED_WAITING_RETRY` 일 때만.
- buffer 로 쓴 `trigger_percent` 기본값이 **20** (원래 `PRICE_UP_PCT` 용!).
  SHORT 에서 `청산가 × 0.8` 이 현재가 아래로 떨어지면 **즉시 발주**.
  → buffer 1~10% clamp + **방향 sanity**(SHORT 는 trigger > 현재가) 2중 방어.

## 🚨 헌법 신설

**헌법 94: rate-limit 가드는 「루프 앞」이 아니라 「네트워크 나가기 직전」에!**
- 루프 시작 전 1회 체크는 루프 도중 걸린 ban 을 못 막는다
- 예외를 삼키고 다음 항목으로 넘어가는 코드가 있으면 가드가 무의미

**헌법 95: 418 은 IP ban — 계정 단위로 관리하지 말 것!**
- 컨테이너·계정이 여러 개여도 IP 는 하나 → 전역(프로세스+Redis) 상태로

**헌법 96: 무거운 공용 조회(weight 40+)는 클라이언트에서 공유 캐시할 것!**
- 워커마다 각자 호출하면 워커를 늘릴수록 선형으로 ban 에 가까워진다
- 새 워커 추가 시 「이 호출의 weight × 주기 × 워커수」를 반드시 계산

**헌법 97: 스로틀/차단 장치는 「차단한 것」을 사용량에 세지 말 것!**
- 세면 부풀고 → 더 차단하고 → 더 부푸는 악순환 (Fix 127 실사고)
- 카운터는 「실제 나간 요청」만. 단위 테스트로 `누적 == 전송건수` 를 검증할 것

**헌법 98: 안전장치는 「필수 경로」를 절대 막지 않도록 분류할 것!**
- 스캔(klines/ticker) = 버려도 됨 / 주문·포지션·마진 = 항상 통과
- 임계는 한도보다 낮게 잡아 필수 호출이 쓸 여유를 남긴다
- 그리고 임계 계산이 **과대평가**면 정상 매매를 해친다 → weight 는 실제 규칙대로
  (klines 는 limit 에 따라 1/2/5/10, ticker·openOrders 는 symbol 있으면 1)

**헌법 99: 요청당 실행되는 코드에 무거운 리소스 생성을 넣지 말 것!**
- `get_redis_client()` 가 매번 새 풀을 만드는데 그걸 hot path 에 넣어 연결 폭증 (Fix 126)
- 계측·캐시는 반드시 싱글턴 + 짧은 타임아웃 (거래 경로를 붙잡으면 안 됨)

**헌법 100: 다른 모드용 기본값을 그대로 빌려 쓰지 말 것!**
- `trigger_percent` 기본 20 은 `PRICE_UP_PCT` 용인데 `LIQUIDATION_BUFFER` 가 빌려 씀
  → 즉시 발주 위험 (Fix 128)
- 계산 결과에 **방향 sanity 검사**를 붙일 것: 「아직 도달하지 않은 가격」이어야 정상

## 관련
- [[2026-08-26-fix113-fix114-stage-progression]] (같은 증상으로 보였지만 별개 원인)
- [[2026-08-26-fix111-fix112-concurrent-cap]] (Fix 111b 가 부하를 늘린 쪽)
