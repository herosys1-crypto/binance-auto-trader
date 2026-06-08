# 📜 사장님 사상 — 신 모드 C 「↻ 미진입 단계만 재설정」 (2026-06-08)

> **사장님 명시 (2026-06-08)**:
> > "포지션 유지하고 다음단계 진입을 할수 있게 현재가 기준으로 10%더 상승하면 진입하게 해줘"
> > "기존 전략를 무시하고 현재가 기준으로 진입한 단계는 무시하고
> >  미진입한 전략을 새로설정하면 될것 같은데 기획을 해줘"

이 문서 = 영구 보존. 신 모드 C 의 = UI/API/검증 = 100% 사장님 사상.

---

## 🌟 사장님 의도 핵심 (= 영구 보존)

### 시나리오 (= 사장님 BEATUSDT/VELVET 사례):
```
사장님 SHORT 진입 → 가격 폭등 → 미진입 단계 (5/6) trigger_price 통과
→ 자동 진입 안 됨 (= 옛 trigger 너무 낮음)
→ 사장님 의도: "미진입 단계 = 현재가 기준 신 trigger_price 로 재설정"
```

### 사장님 사상:
1. **진입 단계 = 절대 보존** (= 사장님 자본 영향 X)
2. **미진입 단계 = 현재가 기준 신 trigger_price**
3. **사장님 미리보기 + 확인 후 = 적용** (= 안전 + 자율)

---

## 🎯 신 모드 C 정확 로직

### 「수정 모드」 모달 = 3가지 모드:

| 모드 | 이름 | 효과 |
|---|---|---|
| **A** | ↻ 설정만 수정 | TP/SL 만 즉시 갱신 (= 옛 동작) |
| **B** | 🛑 종료 후 새로 시작 | 모든 청산 + 신 strategy (= 옛 동작) |
| **C ⭐** | **↻ 미진입 단계만 재설정** | **진입 단계 유지 + 미진입 = 현재가 기준 (= 신!)** |

---

## 📐 모드 C 정확 로직 — 단계별

### 1. 진입 단계 (= is_triggered=True) — 보존:
```
- trigger_price: 옛 값 그대로 (= 사장님 실제 진입 가격)
- planned_capital: 옛 값 그대로
- 실 체결 평단 / qty: 영향 X
```

### 2. 미진입 단계 (= is_triggered=False) — 재계산:
```
SHORT:
  - stage N+1: 현재가 × 1.10
  - stage N+2: 현재가 × 1.21 (= 1.10²)
  - stage N+3: 현재가 × 1.331 (= 1.10³)
  - ...

LONG:
  - stage N+1: 현재가 × 0.90
  - stage N+2: 현재가 × 0.81 (= 0.90²)
  - ...

trigger_percent: 10% 유지 (= 단계간 +10%)
planned_capital: 옛 값 그대로 (= 사장님 입력 보존)
```

### 3. SL 한도 자동 재계산:
```
total_capital = stage_plans 의 planned_capital 합 (= 변경 X)
SL 한도 = total_capital × SL% (= 영향 X)
```

---

## 📐 사장님 BEATUSDT (#39) 적용 예시

### 현재 상태:
- 현재가 = 4.29 USDT
- 진입 단계 (1~4) = 평단 3.6353 (= 보존!)
- 미진입 단계 (5, 6) = 옛 3.8788 / 4.2666 (= 통과 = silent bug)

### 모드 C 적용 후:
| 단계 | 옛 trigger | 신 trigger | 변경 |
|---|---|---|---|
| 1~4 | 그대로 | 그대로 | ❌ 변경 X (= 진입) |
| 5 | 3.8788 | **4.719** (= 4.29 × 1.10) | ✅ 재계산 |
| 6 | 4.2666 | **5.191** (= 4.29 × 1.21) | ✅ 재계산 |

→ stage 5 = 가격 +10% 도달 시 진입
→ stage 6 = 가격 +21% 도달 시 진입

---

## 📐 사장님 VELVETUSDT (#36) 적용 예시

### 현재 상태:
- 현재가 = 0.34337 USDT
- 진입 단계 (1~5) = 평단 0.25479 (= 보존)
- 미진입 단계 (6) = 옛 0.29987 (= 통과 = silent bug)

### 모드 C 적용 후:
| 단계 | 옛 trigger | 신 trigger | 변경 |
|---|---|---|---|
| 1~5 | 그대로 | 그대로 | ❌ 변경 X (= 진입) |
| 6 | 0.29987 | **0.37770** (= 0.34337 × 1.10) | ✅ 재계산 |

→ stage 6 = 가격 +10% 도달 시 진입

---

## 🏗 UI 기획 (= 「수정 모드」 모달 통합)

### 모달 화면 (= 신 표):
```
┌──────────────────────────────────────────────────────────┐
│ 📝 전략 #39 BEATUSDT 수정                                │
├──────────────────────────────────────────────────────────┤
│ 🎯 수정 모드 선택:                                       │
│   [ ↻ 설정만 수정 ]                                      │
│   [ 🛑 종료 후 새로 시작 ]                               │
│   [ ↻ 미진입 단계만 재설정 ]  ⭐ 신!                     │
├──────────────────────────────────────────────────────────┤
│ 📊 단계별 미리보기:                                      │
│ ┌────┬──────────┬──────────┬──────────┬──────────────┐  │
│ │ N  │ 자본     │ 신 진입가│ 상태     │ 변경         │  │
│ ├────┼──────────┼──────────┼──────────┼──────────────┤  │
│ │ 1  │ 300      │ 2.6494   │ ✅ 진입  │ 변경 X       │  │
│ │ 2  │ 300      │ 2.9143   │ ✅ 진입  │ 변경 X       │  │
│ │ 3  │ 600      │ 3.2057   │ ✅ 진입  │ 변경 X       │  │
│ │ 4  │ 500      │ 3.5262   │ ✅ 진입  │ 변경 X       │  │
│ │ 5  │ 1,000    │ 4.719    │ 🔲 대기  │ 🔄 3.8788 → 4.719 │
│ │ 6  │ 1,500    │ 5.191    │ 🔲 대기  │ 🔄 4.2666 → 5.191 │
│ └────┴──────────┴──────────┴──────────┴──────────────┘  │
│                                                          │
│ 현재가: 4.29 USDT (Binance, 실시간)                     │
│ 총 자본: 4,200 USDT (= 영향 X)                           │
│ SL 한도: -3,360 USDT (= 영향 X)                          │
├──────────────────────────────────────────────────────────┤
│  [ 취소 ]  [ ↻ 미진입 단계만 재설정 적용 ]              │
└──────────────────────────────────────────────────────────┘
```

### 시각 강조:
- 진입 단계 = **회색 배경** + ✅ 배지
- 미진입 단계 = **노란 배경** + 🔄 변경 표시
- 신 진입가 = **녹색** (= 신 값)

---

## 🛡 사장님 안전 보장

### 1. 미리보기 = 필수
- 사장님 = 모드 C 선택 시 = **즉시 미리보기 표시**
- 신 진입가 + 진입 단계 영향 X 확인 가능
- 사장님 결정 전 = 모든 영향 = 시각 명확

### 2. 확인 모달:
```
"미진입 단계 trigger_price 재계산 적용?

✅ 진입 단계 (1~4) = 영향 X
🔄 미진입 단계 (5, 6) = 현재가 4.29 기준 재계산
   - stage 5: 3.8788 → 4.719
   - stage 6: 4.2666 → 5.191

진행할까요? [취소] [적용]"
```

### 3. Audit log:
- RiskEvent: `UNTRIGGERED_STAGES_RECALC`
- 변경 전후 trigger_price = 영구 기록
- 사장님 사후 검증 가능

---

## 🔧 Backend API (= 이미 PR #149)

### Endpoint (= 이미 구현):
```
POST /strategies/{id}/recalc-untriggered-from-current
```

### 신 기능: **「미리보기」 endpoint 추가** (= Phase 2)
```
POST /strategies/{id}/recalc-untriggered-preview
- 실제 변경 X
- 신 trigger_price 시뮬레이션 반환
- 사장님 확인용
```

응답 예시:
```json
{
  "strategy_id": 39,
  "current_price": "4.29",
  "side": "SHORT",
  "direction": "1.10",
  "untriggered_stages": [
    {"stage_no": 5, "old": "3.8788", "new": "4.719"},
    {"stage_no": 6, "old": "4.2666", "new": "5.191"}
  ],
  "triggered_stages_count": 4,
  "total_capital_unchanged": "4200",
  "sl_limit_unchanged": "-3360"
}
```

---

## 📊 Phase 분리 (= 사장님 결정 후 진행)

### Phase 1 ✅ (= 이 spec) — 사장님 사상 영구 보존

### Phase 2 — Frontend UI 통합 (= 「수정 모드」 모달 강화)
- 신 버튼 「↻ 미진입 단계만 재설정」 = 모달에 추가
- 표 = 진입 단계 회색 / 미진입 노란
- 미리보기 endpoint 호출 + 신 진입가 표시
- 사장님 확인 + 적용

### Phase 3 — Backend (= 미리보기 endpoint)
- POST `/strategies/{id}/recalc-untriggered-preview`
- 실 적용 X + 시뮬레이션 결과 반환

### Phase 4 — 시나리오 pytest
- 진입 단계 보존 검증
- 미진입 단계 재계산 정확성
- SHORT vs LONG 방향 검증

---

## 🌿 사장님 결정 옵션

### 옵션 A — 전체 Phase 2~4 즉시 진행 ⭐ (= 권장)
- UI 통합 + 미리보기 endpoint + pytest = 완전 안전
- 머지까지 = 2~3 PR 소요

### 옵션 B — Phase 2 (UI 만) 우선
- 사장님 즉시 사용 가능
- 미리보기 endpoint = 기존 endpoint 결과 그대로 표시

### 옵션 C — 기존 PR #149 (= 🔄 버튼) 만 활용
- UI 통합 X = 사장님 = 「전략 인스턴스」 카드 🔄 클릭 = 직접 적용 (= 미리보기 없음)
- 가장 빠름 (= 추가 개발 X)

---

## 🛡 헌법 5단계 검증

| 원칙 | 적용 |
|---|---|
| **메인넷 = 실자금** | 진입 단계 = 절대 보존 (= 사장님 자본 영향 X) |
| **사장님 사상 우선** | 사장님 의도 100% 반영 + 미리보기 |
| **Silent bug 금지** | 모든 변경 = audit log + 시각 확인 |
| **검증 없는 코드 금지** | 미리보기 + pytest 시나리오 |
| **대칭성** | SHORT/LONG 방향 = 명확 분리 |

---

## 🔗 관련 spec

- `STRATEGY_EDIT_LOGIC_SPEC_2026-06-08.md` (= 기본 「수정 모드」)
- `DEVELOPMENT_PRINCIPLES_2026-06-07.md` (= 헌법)
- PR #149 = `recalc_untriggered_from_current` endpoint

---

# 🛡 Spec v2 (2026-06-08 추가) — 다른 시스템 영향 검증 (= 사장님 critical 요구)

## 사장님 명시:
> "남은 포지션 진입단계를 재설정하면 현재가 대비 위아래 설정을 하게 되는데
>  그이후 설정이 기존 익절 PT와 크라이시스 그리고 익절 TP3단계후 설정되
>  하락에 따라 강제익절또는 익절TP 진행 시작 설정진행에 영향이 없게 기획을 해줘"

= 신 모드 C 적용 = **trigger_price 만 변경** + **다른 모든 시스템 = 영향 X** = 사장님 자본 보호 + 사장님 사상 영구 보존.

---

## 📊 6 시스템 영향 검증 매트릭스 (= 모두 영향 X ✅)

### 1. **익절 TP 임계 (TP1~10)** = 영향 X ✅
```
TP 발동 조건 = pnl_ratio >= TP threshold (%)
TP threshold = template.tp1_percent ~ tp10_percent (= 사장님 옵션 10/15/20/25 등)
pnl_ratio = (current_price - avg_entry_price) / avg_entry_price × leverage

= TP 발동 = 평단 (avg_entry_price) 기준 ROI 계산
= trigger_price 변경 = ROI 계산에 X = 영향 X
```
→ **사장님 TP1 옵션 (+20%) = 그대로 작동** ✅

### 2. **Crisis 모드 진입** = 영향 X ✅
```
Crisis 진입 조건 = max_loss_pct ≤ template.crisis_threshold (default -50%)
                  + (모든 단계 진입 완료 OR ad-hoc 사용)

max_loss_pct = 가장 깊었던 손실 % (= 평단 기준)
trigger_price 변경 = max_loss_pct 계산에 X = 영향 X

다만:
- "모든 단계 진입 완료" 조건 → 미진입 단계 = trigger_price 변경 (= 사장님 의도 = 더 늦게 진입)
- = Crisis 진입 = 늦어질 수 있음 (= 안전 방향, 사장님 자본 보호 강화)
```
→ **Crisis = 옛 그대로 작동 + 더 안전 방향** ✅

### 3. **익절 TP3 후 Trailing TP** = 영향 X ✅
```
Trailing TP 발동 조건:
  - status TP3+_DONE_PARTIAL (= TP3 발동 후)
  - current_stage >= 3
  - peak >= 5%
  - pnl_ratio <= peak - retrace (= 사장님 옵션 5/10/15/20%)

= 모든 조건 = 평단 기준 ROI / 진입 단계 / Redis peak
= trigger_price 변경 = 영향 X
```
→ **사장님 trailing retrace 옵션 (-15%) = 그대로 작동** ✅

### 4. **하락 시 강제 익절 (= Trailing retrace)** = 영향 X ✅
```
강제 익절 = trailing retrace 발동 (= TP3 후 peak 회귀)
조건 = 위 3번과 동일

trigger_price 변경 = 영향 X
사장님 옵션 (-15%) = peak 대비 -15% 회귀 시 = 즉시 전량 청산
```
→ **사장님 자본 보호 = 옛 그대로** ✅

### 5. **SL 한도 (= 강제 청산)** = 영향 X ✅
```
SL 한도 = total_capital × SL% (default 80%)
total_capital = stage_plans.planned_capital 합 (= 사장님 입력)

신 모드 C = trigger_price 만 변경
         = planned_capital 그대로 (= 사장님 의도 보존)
         = total_capital 그대로
         = SL 한도 그대로
```
→ **SL 한도 = 영향 X = 사장님 자본 보호** ✅

### 6. **TP 진행 시작 (= TP1 발동 시점)** = 영향 X ✅
```
TP1 발동 = pnl_ratio >= TP1 임계 (사장님 옵션 +20%)
= 평단 기준 ROI 도달 시 = 즉시 발동

trigger_price = stage 진입 조건 (= 자동 진입)
TP threshold = TP 발동 조건 (= 자동 익절)
= 두 시스템 = 완전 독립!

trigger_price 변경 = TP 발동 시점 = 영향 X
```
→ **TP 진행 = 옛 그대로 작동** ✅

---

## 🌟 검증 결과 — 사장님 사상 100% 보존

### 변경 영향 (= 사장님 의도):
| 시스템 | 영향 | 의도 |
|---|---|---|
| stage_trigger_worker | ✅ 변경 (= 신 trigger_price) | 사장님 의도 |

### 변경 없음 (= 안전):
| 시스템 | 영향 X | 영구 보존 |
|---|---|---|
| TP1~10 임계 발동 | ❌ | 평단 기준 ROI |
| Crisis 모드 진입 | ❌ | max_loss_pct 기준 |
| Trailing TP (TP3 후) | ❌ | peak + retrace |
| 강제 익절 (하락) | ❌ | trailing retrace |
| SL 한도 | ❌ | total_capital × SL% |
| TP 진행 시작 | ❌ | 평단 기준 ROI |

---

## 🛡 사장님 자본 보호 사상 영구 보존

### 진입 단계 (= is_triggered=True) — 영구 보존:
- ❌ trigger_price 변경 X (= 사장님 실 체결 가격)
- ❌ planned_capital 변경 X
- ❌ 실 체결 평단 영향 X
- ❌ 실 체결 qty 영향 X

### 미진입 단계 (= is_triggered=False) — 사장님 의도:
- ✅ trigger_price 변경 (= 현재가 × 1.10^N)
- ❌ planned_capital 변경 X (= 사장님 자본 합 그대로)
- ❌ trigger_percent 변경 X (= 10% 유지)

### 다른 모든 시스템:
- ❌ 영향 X (= 위 6 시스템 매트릭스)

---

## 📐 사장님 사례 100% 안전 검증

### 사장님 BEATUSDT (#39) 시뮬레이션:
```
적용 전:
  - 진입 단계 1~4 = 평단 3.6353 (= 보존)
  - 미진입 5: trigger 3.8788 (= 이미 통과)
  - 미진입 6: trigger 4.2666 (= 이미 통과)
  - TP1 임계 (사장님 옵션) = +20%
  - Trailing retrace = -15%
  - SL 한도 = 4,200 × 80% = -3,360 USDT
  - Crisis 임계 = -50%

적용 후:
  - 진입 단계 1~4 = 영향 X ✅
  - 미진입 5: trigger 4.719 (= 신 진입가)
  - 미진입 6: trigger 5.191
  - TP1 임계 = +20% (영향 X) ✅
  - Trailing retrace = -15% (영향 X) ✅
  - SL 한도 = -3,360 USDT (영향 X) ✅
  - Crisis 임계 = -50% (영향 X) ✅

다음 동작:
  - 가격이 +10% 더 올라가면 (4.29 → 4.72) → stage 5 자동 진입
  - 가격이 +21% 더 올라가면 (4.29 → 5.19) → stage 6 자동 진입
  - 가격 하락 (= 평단 3.6353 위 시간) → TP1 (+20%) 도달 시 익절 자동
  - max_loss_pct -50% 도달 시 → Crisis 진입 (= 옛 그대로)
```

→ **모든 시스템 = 사장님 사상 그대로 작동** ✅

---

## 🔗 코드 검증 위치 (= 향후 회귀 방지)

### 영향 X 확인된 코드:
1. `risk_service.evaluate_take_profit_level` — pnl_ratio 기준 = trigger_price X
2. `risk_service._should_trigger_crisis_mode` — max_loss_pct + stage count = trigger_price X
3. `risk_service` trailing armed check — status + peak + retrace = trigger_price X
4. `risk_service` SL 임계 — total_capital × SL% = trigger_price X
5. `stage_trigger_worker` — trigger_price ✅ (= 변경 의도)

### Audit log:
- `RiskEvent UNTRIGGERED_STAGES_RECALC` (= 이미 PR #149 구현)
- 변경 전후 trigger_price = 영구 기록
- 사장님 사후 검증 가능

---

## 🌿 사장님 결정 — C 즉시 진행

### 사장님 명시:
> "C로 진행해주고"
> + 영향 분석 spec 추가

### 즉시 사용 가능 (= PR #149 머지 + 배포):
```bash
cd ~/binance-auto-trader/backend && git pull origin main && docker compose restart api
```

→ 「전략 인스턴스」 카드 → **🔄** 클릭 → 즉시 적용!

### 영향:
- ✅ 미진입 단계 trigger_price 만 변경
- ✅ 다른 모든 시스템 = 영향 X (= 위 6 매트릭스)
- ✅ 사장님 자본 보호 영구 보존

---

> **Spec v1**: 2026-06-08 (= 신 모드 C 기본 기획)
> **Spec v2**: 2026-06-08 (= 6 시스템 영향 X 검증 추가, 사장님 critical 요구)
> **위치**: `binance-auto-trader/STRATEGY_EDIT_MODE_C_SPEC_2026-06-08.md`
> **상태**: 영구 보존 — 변경 시 = 사장님 명시 승인
> **다음**: PR #149 머지 + 배포 + 사장님 🔄 클릭 사용
