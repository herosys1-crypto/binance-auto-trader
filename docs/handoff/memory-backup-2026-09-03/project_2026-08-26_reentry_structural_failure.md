---
name: 2026-08-26-reentry-structural-failure
description: "🚨 재진입이 '구조적으로' 불가능했던 3겹 결함 발견 (Fix 103/104/105) — 워커 침묵 → 카운터 공유 → mark_price 결손. 관측성 없으면 fix도 검증 불가!"
metadata:
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
  modified: 2026-08-26T00:32:37.382Z
---

# 🚨 재진입 워커 = 배포됐지만 한 번도 작동한 적 없었음

**날짜**: 2026-08-26
**발단**: 사장님 "손절후 2단계 진입이 없는것 같이"

## 문제의 3겹 (하나 풀면 다음이 드러남)

### 1겹: 신규 진입 카운터 공유 (Fix 103 C)
- `remaining = daily_limit - _count_used_slots(db)`
- `_count_used_slots` = **신규 진입 워커 3종 공유** (bb4h/top_short/bottom_long)
- 오늘 신규 86건 - limit 30 = **음수** → 무로그 return
- = 신규 진입이 한도 채우면 **마틴게일 2단계도 동반 사망**
- ⚠️ `auto_bb_breakdown_worker.py:827` 주석엔 이미 "손절 재진입 = 별도 카운트!"
  라고 **선언**돼 있었으나 코드는 공유 카운터 사용 = **선언↔구현 불일치**
- **fix**: 재진입 전용 키 `sajangnim_reentry_daily_limit` + 전용 카운터

### 2겹: 조기 return 무로그 (Fix 103 A/B)
- 첫 logger 호출이 happy path 한참 뒤 → 그 전 모든 분기가 **침묵**
- **미실행과 조기종료를 구별할 수 없었음**
- 형제 워커(auto_short_at_top)는 매 tick "완료: entered=0 skipped=4" 로그 → 대칭 붕괴
- **fix**: `_finish()` 단일 종료 경로 + `_bump()` skip 사유 집계 → 완료 로그 1줄로 원인 판정

### 3겹: mark_price 결손 66% (Fix 104) ★설계 모순★
```
mark_price_stream_consumer: ACTIVE_STATUS_NOT_IN 에 STOPPED/CLOSED_BY_SL/REENTRY_READY
  → _refresh_loop 30초마다 UNSUBSCRIBE → TTL 60초 만료 → 키 소멸
realtime_reentry_worker:    청산된 심볼을 재진입 후보로 스캔
  → 그 심볼의 mark_price 가 없음!
```
- **두 워커가 정반대 전제로 설계됨** → 재진입 구조적 불가능
- **fix Layer A**: 스트림 구독 = 활성 ∪ 재진입후보(TERMINAL + 24h), 상한 200
- **fix Layer B**: `get_24hr_ticker()` 전 심볼 1회 배치 fallback (43 calls → 1)
- 실측 결과: `no_mark_price 42 → 0`, `fallback_px=0` (Layer A만으로 해결, API 0회)

## ⚠️ 절대 하지 말 것
`get_24hr_ticker().lastPrice` 를 `mark_price:{SYM}` 키에 **쓰지 말 것**.
`risk_service` / `stage_trigger_worker` / `tp_sl_orchestrator` 가 그 키를
**SL/ROI 판정 단일 진실**로 읽으므로 → 캐시 오염 = 잘못된 손절.
fallback 값은 **해당 사이클 인메모리 dict 로만** 사용.

## 교훈 (헌법 후보)

**헌법 80: 스케줄 워커는 로그 없이 return 금지!**
- 모든 조기 return = 사유 로그 필수
- 함수 끝 = 항상 완료 로그 (살아있음 증명)
- 근거: 관측성 없으면 **fix를 배포해도 검증 자체가 불가능**.
  Fix 99(강화)/Fix 102(완화) 둘 다 무의미했음 — 실행조차 안 됐으니까.

**헌법 81: 재진입/마틴게일 ≠ 신규 진입 → 한도 분리!**
- 재진입은 이미 열었던 포지션의 후속 관리
- 신규 진입 슬롯을 공유하면 하루 한도 소진 시 회복 로직 전체가 마비

**헌법 82: 워커 간 전제 일치 검증!**
- A워커가 만드는 데이터를 B워커가 소비할 때
- A의 "제외 조건"과 B의 "대상 조건"이 **교집합 0**이 되면 B는 영구 사망
- 신 워커 추가 시 = 소비하는 데이터의 **생산자 조건**을 반드시 확인

## 검증 흐름 (다음에도 이렇게)
1. 로그 0건이면 → **먼저 관측성부터** (Fix 103)
2. 로그 나오면 skip 사유 분포로 병목 특정 (`reasons={...}`)
3. 병목 제거 → 다음 병목 드러남 → 반복
4. 각 단계마다 **실 로그로 검증** (코드 배포 = 검증 아님!)

## 실측 진행 (2026-08-26 00:29)
```
reasons={'already_active': 28, 'no_stop_price': 21, 'entry_exception': 5,
         'rebound_too_small': 5, 'indicator_gate_need2': 6}  fallback_px=0
```
- `indicator_gate_need2` 등장 = **Fix 99/102 지표 게이트가 처음으로 실제 평가됨**
- 남은 blocker: `no_stop_price` 32%, `entry_exception` 8% → Fix 105 진행

## 관련
- [[2026-08-25-session-final-30fixes-ultra-productive]]
- [[feedback-verify-before-complete]] (헌법 69/70/71 = 실 검증 후 완료!)
- [[feedback-no-ask-full-auto-dev]]
