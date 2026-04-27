# 로직 검증 테스트 계획서

작성일: 2026-04-27  
목적: 전략 시스템이 설계대로 작동하는지 단계별로 검증하고, 발견된 이슈를 기록·수정한 뒤 실전(mainnet 소액)으로 이행

---

## Phase 0 — 시작 전 환경 점검 (5분)

| 체크 | 명령/방법 | 기대 결과 |
|---|---|---|
| 컨테이너 8개 모두 Up | `docker compose ps` | 8 / 8 running |
| 운영 대시보드 접속 | http://localhost:8000 | 시스템 상태 = 정상 |
| Telegram 테스트 | 대시보드 "📱 Telegram 테스트" 버튼 | 실시간 메시지 도착 |
| 거래소 계정 활성 | 대시보드 또는 DB | testnet, mainnet 둘 다 active=true |

위 4개가 모두 OK여야 다음 단계로 진행.

---

## Phase 1 — Testnet 풀 사이클 검증 (30~90분)

**목표:** 가짜 돈으로 진입 → TP/SL → 종료 전 과정의 로직이 설계대로 도는지 확인

### 1-A. 전략 시작
1. 운영 대시보드 → "🟢 새 전략 시작"
2. 거래소 계정 = **testnet**
3. 심볼 선택 (변동성 있는 것 권장: BTCUSDT, ETHUSDT 중 하나)
4. 방향 선택 (롱/숏)
5. 전략 템플릿 선택 (38개 중 하나) — 본인이 검증하고 싶은 로직이 있는 템플릿
6. 시작

### 1-B. 단계별 관찰 체크리스트

각 항목 옆에 ✅(정상) / ⚠️(이상) / ❌(실패) 직접 표시:

| # | 관찰 포인트 | 기대 동작 | 결과 | 메모 |
|---|---|---|---|---|
| 1 | 1단계 진입 주문 | 즉시 또는 트리거 가격에서 BUY/SELL 주문 발생 | □ | |
| 2 | 1단계 체결 | 거래소에서 fill → DB에 position row 생성 | □ | |
| 3 | TP 주문 자동 배치 | 체결 후 TP1, TP2, ... 가격에 reduce-only 주문 생성 | □ | |
| 4 | SL 주문 자동 배치 | 손절가에 stop-market 주문 생성 | □ | |
| 5 | Position reconcile | 1~5분 주기로 거래소 vs DB 포지션 일치 확인 | □ | |
| 6 | 2단계 트리거 (가격 역행 시) | trigger_percent 도달 시 추가 진입 | □ | |
| 7 | 평단가 갱신 | 단계 진행에 따라 avg_entry_price 정확히 재계산 | □ | |
| 8 | TP 부분 체결 | 가격이 TP 도달 시 일부 수량 청산 + 남은 TP 유지 | □ | |
| 9 | SL 작동 | 가격이 SL 도달 시 전량 청산 | □ | |
| 10 | 종료 후 상태 | 전략 status = COMPLETED 또는 STOPPED, position 닫힘 | □ | |
| 11 | Telegram 알림 | 주요 이벤트마다 메시지 도착 (체결, TP, SL 등) | □ | |
| 12 | Crisis Recovery (해당 시) | 일정 손실 시 위기 모드 자동 진입 | □ | |
| 13 | Auto Reentry (해당 시) | 정책에 따라 재진입 발생 | □ | |

### 1-C. 관찰 도구

- **운영 대시보드** http://localhost:8000 — 전체 상태 한눈에
- **Grafana** http://localhost:3000 — 시계열 메트릭 (admin / Admin1234!)
- **DB 직접 조회** (필요 시):
  ```
  docker compose exec -T db psql -U postgres -d binance_auto_trader -c "SELECT id, symbol, current_stage, avg_entry_price, current_position_qty, unrealized_pnl, status FROM strategy_instances ORDER BY id DESC LIMIT 5;"
  ```
- **로그 실시간 확인**:
  ```
  docker compose logs -f api scheduler user-stream
  ```
  (Ctrl+C로 종료, 컨테이너는 계속 실행됨)

---

## Phase 2 — 발견된 이슈 기록

테스트 중 ⚠️/❌ 발견 시 여기에 적어두기:

| # | 발생 시각 | 어떤 단계 | 무엇이 잘못되었나 | 로그/스크린샷 위치 | 우선순위 |
|---|---|---|---|---|---|
| 1 | | | | | High/Mid/Low |
| 2 | | | | | |
| 3 | | | | | |

각 이슈마다:
1. 재현 방법 정리
2. 코드 수정이 필요한지 vs 설정 조정으로 해결 가능한지 판단
3. High 우선순위는 mainnet 진입 전 반드시 해결

---

## Phase 3 — Mainnet 소액 진입 결정 기준

**다음 조건 모두 충족 시에만 mainnet 진행:**

- [ ] Phase 1 체크리스트 13개 항목 중 본인이 사용할 항목 모두 ✅
- [ ] Phase 2 High 우선순위 이슈 0건
- [ ] 동일 전략 템플릿으로 testnet에서 1회 이상 완전한 사이클 (시작 → 종료) 확인
- [ ] Telegram 알림 누락 없음
- [ ] Position reconcile이 정상 작동 (DB와 거래소 상태 일치)

---

## Phase 4 — Mainnet 소액 실전 (위 조건 충족 후)

### 4-A. 사전 안전 점검

| 체크 | 확인 방법 |
|---|---|
| Mainnet API 키 활성 | 대시보드의 거래소 계정 섹션 |
| Kill-switch 작동 가능 | DB의 `account_kill_switches` 테이블 비활성 상태 |
| Daily loss limit 설정 | `account_daily_risk_limits` 테이블에 안전한 상한 |
| 바이낸스 계정 잔고 | mainnet 계정에 충분한 USDT (테스트 금액 + 약간의 버퍼) |
| 레버리지 확인 | 전략 템플릿의 leverage 값. 청산가 거리 계산 |

### 4-B. 첫 mainnet 거래 파라미터 (본인 결정)

| 항목 | 선택 |
|---|---|
| 심볼 | __________ (예: BTCUSDT) |
| 방향 | __________ (long/short) |
| 전략 템플릿 | __________ (Phase 1에서 검증한 것과 동일) |
| **진입 금액** | __________ USDT (예: 5~10) |
| 레버리지 | __________ (낮을수록 안전. 1~3배 권장) |

### 4-C. 실전 진행

1. 운영 대시보드 → "🟢 새 전략 시작" → 거래소 계정 = **mainnet**
2. 위 파라미터 입력
3. 시작 후 **첫 1시간은 옆에서 관찰**
4. Phase 1과 동일한 체크리스트로 동작 검증
5. 이상 발견 시 즉시 수동 종료 (대시보드의 정지 버튼) 또는 Kill-switch

### 4-D. 실전 후 회고

- 실제 PnL과 예상 PnL 비교
- 슬리피지 (testnet vs mainnet 차이)
- 주문 체결 속도 차이
- 다음 단계: 금액 점진적 확대? 다른 전략 추가 검증?

---

## 비상 절차

**거래 즉시 중단이 필요한 경우:**

```
docker compose exec -T db psql -U postgres -d binance_auto_trader -c "UPDATE account_kill_switches SET is_enabled = true, reason_code = 'MANUAL_STOP', triggered_at = NOW() WHERE exchange_account_id = (SELECT id FROM exchange_accounts WHERE is_testnet = false AND is_active = true LIMIT 1);"
```

(또는 운영 대시보드 → 비상 정지 버튼이 있다면 그것)

**전체 시스템 종료 (포지션은 거래소에 그대로 남음):**

```
docker compose down
```

이후 거래소 웹/앱에서 직접 포지션 정리.

---

## 참고

- 테스트 중 막히거나 이상 발견 시 Cowork에 다시 알려주세요
- 발견된 이슈는 `binance-auto-trader` 저장소에 issue 또는 코드 수정으로 반영
- mainnet 진입 후 첫 손익은 평정심 유지 — 0.5 USDT 손실도 학습 비용
