# HANDOFF — 2026-04-30 (집 → 사무실)

집에서 저녁 작업한 내용을 사무실에서 이어받기 위한 인계서입니다.

---

## 📌 한 줄 요약

옵션 C 적용 완료 — **마지막 단계도 사용자 입력 % (예: 20%) 로 진입**, **트레일링 익절 = 피크 대비 -5% 회귀**, **알림 중복 dedup 강화**, UI 안내 문구 정리.

---

## 🎯 사용자 기획 변경 (확정)

### 1. 마지막 단계 진입 로직
- **이전**: SHORT 마지막 단계는 청산가 -5% 위치에 자동 진입 (LIQUIDATION_BUFFER)
- **이후**: 사용자가 입력한 % 만큼 상승/하락 시 진입 (PRICE_UP_PCT/PRICE_DOWN_PCT)
- **사용자 발언**: "마지막까지 금액이 있으면 정한 20% 상승에 진입"

### 2. 트레일링 익절 (-5%)
- **이전**: 절대 임계 (피크 ≥ 20% AND 현재 ≤ 20%)
- **이후**: **피크 대비 -5% 회귀 시** 전량 청산
- **활성 조건**: 피크 ≥ +5% (TP1 임계 도달) AND 현재 ≤ 피크 - 5%
- **사용자 발언**: "익절을 단계별로 진행하는 중에 -5% 하락하면 모두 청산익절"

### 3. -50% 손절 (변경 없음)
- 모든 단계 진입 완료 후 PnL ≤ -50% 시 전량 손절 (이미 구현됨)

---

## 🔧 코드 변경

| 파일 | 변경 |
|---|---|
| `services/strategy_calculator.py` | `DEFAULT_LAST_TRIGGER_MODE_SHORT`: LIQUIDATION_BUFFER → **PRICE_UP_PCT**<br>`DEFAULT_LAST_SHORT_TRIGGER_PCT`: 5 → **20** |
| `services/risk_service.py` | `TRAILING_TP_RETRACE_TRIGGER` (절대 20) → `TRAILING_TP_RETRACE_AMOUNT` (**피크 대비 -5**)<br>`TRAILING_TP_PEAK_THRESHOLD`: 20 → **5** (TP1 직후부터 활성)<br>활성 status 에 `TP1_DONE_PARTIAL` 추가 |
| `services/notification_service.py` | **`_is_recent_duplicate()` 추가** — 최근 60초 내 동일 (strategy + title) 알림이 SENT/PENDING 이면 skip |
| `static/index.html` | `_collectDirectInputs` 가 마지막 단계 사용자 입력을 `last_stage_trigger_percent` 로 분리 전달<br>10단계 input 의 disabled 풀고 placeholder "청산가 직전 -5%" 제거<br>안내 문구 "마지막 단계는 청산가 -5%" → "사용자가 입력한 % 상승/하락 시 진입" |
| `models/strategy_template.py` | 문서 업데이트 (default 변경 반영) |
| `api/v1/admin.py` | `last_stage_trigger_mode/percent` 필드 description 업데이트 |
| `tests/unit/test_strategy_calculator_v2.py` | `test_10_stage_short_default_pct` 신규 default 에 맞춰 갱신 |
| `CHANGELOG.md` | 2026-04-30 항목 추가 |

---

## 🐛 발견 + 진단된 외부 이슈

### A. Binance Testnet TradFi-Perps 약관 미동의
- 증상: `status=400, code=-4411, msg=Please sign TradFi-Perps agreement contract fapi.`
- 원인: 신규 상장 심볼 (ALGOUSDT, NAORISUSDT 등) 은 사용자가 testnet 웹사이트에서 한 번 약관 동의 필요
- 해결: https://testnet.binancefuture.com/ 에서 해당 심볼로 수동 거래 1회 → 약관 모달 동의 → 즉시 close
- **사무실에서 할 일**: ALGOUSDT 약관 동의 처리

### B. Dockerfile uvicorn 에 `--reload` 없음
- 증상: 코드 수정해도 컨테이너 재시작 전엔 반영 X
- 원인: `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]` — reload 플래그 누락
- 해결: 코드 수정 시마다 `docker compose restart api scheduler user-stream`
- **추후 개선** (선택): dev 용으로 `--reload` 플래그 추가하면 편의성 ↑

---

## 🧪 검증 완료

```
=== 사용자 시나리오: SHORT 6단계 (마지막 20%) ===
stage 1: IMMEDIATE @ 98.23
stage 2: PRICE_UP_PCT 10% @ 108.05
stage 3: PRICE_UP_PCT 10% @ 118.86
stage 4: PRICE_UP_PCT 10% @ 130.74
stage 5: PRICE_UP_PCT 10% @ 143.82
stage 6: PRICE_UP_PCT 20% @ 172.58   ← 사용자 입력대로 +20% 진입 ✓

=== 트레일링 -5% 검증 ===
✓ 피크 25% → 20% (-5%): 발동
✗ 피크 25% → 21% (-4%): 미발동 (작은 흔들림은 통과)
✓ 피크 5%  → 0%  (-5%): 발동 (TP1 직후)
```

---

## 🚀 사무실 setup 절차

### 1. 코드 sync
```powershell
cd C:\Users\user\바이낸스\binance-auto-trader
git pull
```

### 2. 컨테이너 재시작 (Docker Desktop 켜진 상태에서)
```powershell
cd C:\Users\user\바이낸스\binance-auto-trader\backend
docker compose restart api scheduler user-stream
```

### 3. user-stream 컨테이너 다중 실행 여부 확인 (알림 중복 방지 차원)
```powershell
docker ps --filter "name=user-stream"
```
- `binance-auto-trader-user-stream` 1개만 보이는 게 정상
- 2개 이상이면 → `docker rm -f <컨테이너ID>` 로 정리 후 1개만 살리기

### 4. 브라우저 하드 리프레시
- Ctrl + Shift + R (또는 Ctrl + F5)

### 5. ALGOUSDT TradFi-Perps 약관 동의 (별도)
- https://testnet.binancefuture.com/ 로그인
- ALGOUSDT 차트 → 수동 LONG 10 USDT 시도 → 약관 모달 모두 동의 → 즉시 close

### 6. 신규 전략 생성 테스트 (dedup 검증 포함)
- 직접 입력 모드로 6단계 (200/300/500/700/900/1200) + 6단계 트리거 20%
- **확인 포인트**:
  - 6단계 미리보기에 **"+20% 도달 시"** 표시
  - 텔레그램 알림: 전략 시작 1번, 1단계 진입 **1번** (이전엔 2번)

---

## 📂 진행 중 / 보류 상태

- **#75 testnet 라이브 검증 — 5단계** : 진행 중 (옵션 C 적용 후 다시 검증)
- **#30 Sentry 연동** : DSN 입력만 남음 (선택)
- **현재 활성 전략 3개** (ALGOUSDT/UBUSDT/NAORISUSDT) : ALGOUSDT 는 약관 미동의로 stuck 상태
  - **사무실 작업 첫 단계**: 모두 정리 후 새로 시작 권장

---

## 🔖 참고

- 변경된 파일 8개:
  - `CHANGELOG.md`
  - `backend/app/api/v1/admin.py`
  - `backend/app/models/strategy_template.py`
  - `backend/app/services/notification_service.py`
  - `backend/app/services/risk_service.py`
  - `backend/app/services/strategy_calculator.py`
  - `backend/app/static/index.html`
  - `backend/tests/unit/test_strategy_calculator_v2.py`
- DB는 Neon 클라우드 동기화 — 별도 backup 불필요
- 다음 세션은 일반 cowork 모드로 시작하면 이 문서를 자동 인식
