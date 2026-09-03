# Handoff — 2026-05-21 안전망 5종 + 외부 포지션 가시성

## 🎯 한 문장 요약

**#77 PHB / #78 RONIN ~$384 손실 사례 후속 — 거래소가 한 일 ≠ 시스템 상태 라는 빈틈을 5단계 안전망으로 채움. + 도구 밖 수동 진입 포지션 가시성 추가.** 5 PR 모두 main 머지 + VPS 배포 완료, smoke 14/14 통과.

---

## ✅ 머지된 PR (5개, main 의 3438240 + 외부 포지션 머지 commit)

| PR | 머지 commit | 핵심 |
|---|---|---|
| **Phase 1** (#26/#27/#29) | `20f9b72` | STOPPING 가시성 + 5분 갇힘 텔레그램 알림 + UI 배지 |
| **Phase 2 + 2B** (#30) | `047385d` | `MANUAL_CLEANUP_REQUIRED` 신규 상태 + emergency_close 3초 검증 + 자동 재시도 1회 + TP/SL/ENTRY 검증 |
| **Phase 3** (#31) | `3438240` | ENTRY MARKET 사전 마진 검증 (-2027 거래소 거절 사전 차단) |
| **외부 포지션** (#32?) | `f346fee` ish | 도구 밖 수동 진입 포지션 대시보드 표시 |

---

## 🔑 신규 코드 가이드

### 1. `MANUAL_CLEANUP_REQUIRED` 신규 status

`backend/app/core/strategy_status.py`
- `ACTIVE_LIKE` 포함 → 신규 진입 차단, TP/SL 평가 차단
- `TERMINAL_STATUSES` **미포함** → reconcile 의 자동 STOPPED 차단
- 사장님이 「✅ 처리 완료」 클릭 (`POST /strategies/{id}/acknowledge-manual-cleanup`) 해야만 STOPPED 전환

### 2. emergency_close 흐름 (Phase 2 + 2B)

`backend/app/services/execution_service.py:_verify_emergency_close_applied`

```
MARKET 발송 → 3초 검증 →
  ├─ 성공 (≥90% 감소): 정상 → status STOPPING 유지
  └─ 실패 → 10초 sleep → 잔량 재청산 → 3초 재검증 →
      ├─ 성공: RETRY_SUCCEEDED RiskEvent (INFO)
      └─ 실패 →
          ├─ 전량 청산 (is_full_close=True): MANUAL_CLEANUP_REQUIRED + 텔레그램 CRITICAL
          └─ 부분 청산 (TP, is_full_close=False): 알림만 (status 변경 X, race 방지)
```

### 3. ENTRY MARKET 검증 (Phase 2B)

`backend/app/services/execution_service.py:_verify_entry_applied`

- 1초 후 qty 증가 확인
- **자동 재시도 안 함** (중복 진입 risk — 사장님 자본 2x 들어가는 위험)
- 실패 시 ENTRY_VERIFY_FAILED 알림만

### 4. Preflight 마진 검증 (Phase 3)

`backend/app/services/execution_service.py:_preflight_entry_market_check`

- `enter_stage_at_market` + `add_position_now` MARKET 경로에서 호출
- 가용 USDT vs 필요 마진 × 1.05 (5% 버퍼) 비교
- 부족 시 `PreflightCheckFailed` 예외 → 400 친절 에러 + PREFLIGHT_BLOCKED RiskEvent
- 거래소 호출 자체 실패 시 skip — 거래소가 직접 -2027 던지면 그때 받음

### 5. 외부 포지션 가시성

`backend/app/api/v1/positions.py:list_external_positions` — `GET /positions/external`

- 본인 active 계정의 거래소 포지션 bulk fetch
- ACTIVE_LIKE strategy 매칭 차감 → 추적 안 되는 것만
- 수동 새로고침 (rate limit 부담 X)
- 자동 관리 X — 단순 가시성

---

## 📡 신규 RiskEvent type (텔레그램 알림 + UI)

| event_type | severity | 발생 조건 |
|---|---|---|
| `STOPPING_STUCK_DETECTED` | CRITICAL | STOPPING 5분 초과 (reconcile 가 자동 전환) |
| `EMERGENCY_CLOSE_RETRY_ATTEMPTED` | WARN | 1차 검증 실패 후 재시도 시작 |
| `EMERGENCY_CLOSE_RETRY_SUCCEEDED` | INFO | 재시도 후 검증 성공 |
| `EMERGENCY_CLOSE_VERIFY_FAILED` | CRITICAL | 재시도 후에도 전량 청산 실패 → MANUAL_CLEANUP_REQUIRED |
| `PARTIAL_CLOSE_VERIFY_FAILED` | WARN | TP 부분 청산 검증 실패 (status 변경 X) |
| `ENTRY_VERIFY_FAILED` | WARN | ENTRY MARKET 후 qty 증가 안 됨 |
| `PREFLIGHT_BLOCKED` | WARN | 사전 마진 검증으로 진입 차단 |
| `MANUAL_CLEANUP_ACKNOWLEDGED` | INFO | 사장님이 「✅ 처리 완료」 클릭한 trail |

---

## 📊 테스트

- **전체 765 passed** (이전 720 + 신규 45)
  - Phase 1: 11건 (`test_stopping_stuck_alert.py`)
  - Phase 2: 13건 (`test_manual_cleanup_required.py`)
  - Phase 2B: 7건 (`test_verify_tp_sl_entry.py`)
  - Phase 3: 4건 (`test_preflight_checks.py`)
  - 외부 포지션: 7건 (`test_external_positions.py`)
  - 정적자산 가드: +3건 (`test_static_assets_integrity.py`)

---

## 🚨 사장님 운영 검증 (다음 1~2일)

배포 후 자연스럽게 확인할 것:

1. **대시보드 「📊 외부 포지션」 카드 노출** 확인 → 「🔄 새로고침」 클릭 → 결과 정상
2. **「💼 계정」 / 「💉 포지션 추가」 시 마진 부족이면 즉시 친절 에러** (거래소 응답 1~2초 기다림 없음)
3. **「🛑 긴급 종료」 클릭 후 응답이 16초 안에 옴** (3초 검증 + 10초 재시도 + 3초 검증)
4. **STOPPING 인스턴스가 종료 숨김 토글 켜져도 보임** (5분 초과 시 빨간 배지)
5. **텔레그램 알림에 새 type 들 자연 발생** — 운영 중 발생 시 정상

### 발견 시 보고 케이스

- 🔴 MANUAL_CLEANUP_REQUIRED 가 떴는데 해소 안 됨
- 🔴 사전 마진 검증 false-positive (가용 충분한데 차단)
- 🔴 외부 포지션 표시 안 됨 (거래소엔 있는데 카드 빈 채로)
- 🟡 자동 재시도가 의도와 다르게 동작
- 🟢 알림 너무 많음 (cooldown 조정 필요)

---

## 🗺️ 미해결 / 다음 작업 후보

운영 검증 후 우선순위:

1. **Commission 처리** (2~3h) — realized_pnl 에서 거래수수료 차감 (손익 정확성)
2. **Ops 툴** (1~2h) — `make diagnose-stuck`, 머지/배포 진행상황 자동 추적
3. **Prometheus 모니터링** (3~4h) — 새 RiskEvent type 발생 시 alert 자동화
4. **fix/pnl-display-and-loss-alert-clarity** VPS 옛 브랜치 정리 (1분, optional)
5. **PR #26/27/28 닫기** (GitHub 웹, 5분, optional)

---

## 📝 환경/경로 (메모)

- VPS: `~/binance-auto-trader/backend` (NOT `/opt/...`)
- main 으로 명시적 checkout 필요: `git checkout main` 후 `git pull origin main`
- smoke: `bash ../deploy/smoke-test.sh` (14/14 통과 기준)
- VPS IP: `152.42.232.195`
- ENCRYPTION_KEY = 운영 .env 에 설정됨 (smoke 환경변수 검사 통과)

---

## 🔧 한 줄 재배포 (다음 변경 머지 후)

```bash
ssh root@152.42.232.195 && cd ~/binance-auto-trader/backend && git checkout main && git pull origin main && docker compose up -d --build api scheduler mark-price-stream && sleep 60 && bash ../deploy/smoke-test.sh
```

---

## 운영 효과 요약 (#77/#78 사례 기준)

| 시점 | 이전 | 5 PR 적용 후 |
|---|---|---|
| 거래 발송 전 | 거래소가 -2027 받고 알게됨 (1~2초 지연) | 즉시 친절 400 에러 (거래소 호출 0) |
| 거래 발송 직후 | 응답 받고 끝 | 3초/1초 자동 검증 |
| 검증 실패 시 | reconcile 2분/Kill-Switch 10분 후 인지 | 10초 후 자동 재시도 1회 |
| 재시도도 실패 | 사장님 며칠 인지 못 함 (#77/#78 패턴) | 즉시 텔레그램 + UI 빨간 강조 + MANUAL_CLEANUP_REQUIRED |
| 자동 STOPPED | 묻혀버림 (책임 추적 X) | 사장님 명시적 ack 전까지 보존 + 감사 trail |
| 외부 포지션 | 도구 안 보임 (PHB/RONIN 며칠간 미인지) | 「📊 외부 포지션」 카드에 표시 |
