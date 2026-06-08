# 📜 사장님 사상 — 「💉 포지션 추가 + 단계 진행」 통합 (2026-06-09)

> **사장님 명시 (2026-06-09)**:
> > "수동으로 2단계가 진행되었는데 여기 2단계가 그냥 있는건 어떻게 적용해야 할지 기획해줘
> >  이럴 경우 포지션 추가와 한 단계 더 진행된 걸로 적용해서 3단계 익절에 영향을 줘야 해.
> >  다음 단계를 누르고 포지션 진입은 익절 3단계를 빠르게 적용 받을 수 있게 해야 할 것 같아"

---

## 🌟 사장님 사상 핵심

### 현재 문제 (= silent bug 가능):
```
신 strategy = 2단계 정의 (= 자본 1000/1000)
1단계 진입 완료 (= current_stage = 1)
사장님 「💉 포지션 추가」 = 마진 추가 (= stage_no = NULL)
   ↓
current_stage = 그대로 1 ← 🚨
stage_plans = 그대로 2개 ← 🚨
TP3 조건 (= stage >= 3) = 영원히 X
Trailing TP = 영원히 armed X
   ↓
사장님 자본 보호 = 약함! ⚠️
```

### 사장님 의도 (= 신 기능):
```
신 액션 = 「💉 포지션 추가 + 단계 진행」 통합!
   ↓
1. 마진 추가 (= 거래소 시장가/지정가)
2. stage_plan 신규 추가 (= stage_no = current_stage + 1)
3. current_stage += 1
4. 사장님 입력 자본 = 신 stage_plan.planned_capital
   ↓
효과:
- stage_plan 1, 2, 3 (= 신 추가) = 진입 완료
- current_stage = 3
- TP3 조건 (= stage >= 3) = 즉시 만족! ⭐
- Trailing TP = armed (= peak +5% 도달 시) = 빠른 자본 보호!
```

---

## 🎯 신 기능 정확 로직

### 신 endpoint:
```
POST /strategies/{id}/add-position-with-stage
```

### Payload:
```json
{
  "amount_usdt": 1000,
  "order_type": "MARKET" | "LIMIT",
  "limit_price": 4.5 (= LIMIT 시),
  "advance_stage": true  ← 신!
}
```

### 백엔드 동작 (= 트랜잭션):
```python
1. 「💉 포지션 추가」 (= 기존 add-position)
   - 거래소 시장가/지정가 진입
   - qty 늘림 + 평단 갱신
   - total_capital += amount

2. advance_stage = True 시:
   a. current_stage += 1 (= 신 단계 번호)
   b. 신 StrategyStagePlan 추가:
      - stage_no = current_stage
      - planned_capital = amount_usdt
      - trigger_mode = "IMMEDIATE" (= 즉시 진입, 추적 X)
      - trigger_price = 사장님 진입가
      - is_enabled = True
      - is_triggered = True
      - triggered_at = now
   c. RiskEvent audit (= STAGE_ADVANCED_MANUAL)

3. 응답 = 신 strategy 상태 + 신 stage_no
```

---

## 🌟 사장님 효과 (= TP3 빠른 활성화!)

### 사장님 사례 (= 신 strategy 2단계 정의):
```
신 strategy:
- 1단계: 자본 1000 (= 진입 완료)
- 2단계: 자본 1000 (= 미진입)

사장님 「💉 포지션 추가 + 단계 진행」 = 자본 1000:
   ↓
- 1단계: 진입 완료 (= 그대로)
- 2단계: 미진입 (= 그대로)
- 3단계 (신!): 진입 완료 (= 사장님 의도!)
- current_stage = 3 ⭐
   ↓
- TP3 조건 (= stage >= 3) = ✅ 만족!
- 가격 회복 + peak +5% → Trailing armed
- peak -X% 회귀 시 → 전량 청산 (= 사장님 자본 보호!)
```

### 신 strategy 의 = 「💉 + 단계 진행」 2회:
```
1단계 진입 → 「💉 + 단계 진행」 → 2단계 완료 → 「💉 + 단계 진행」 → 3단계 완료
   ↓
current_stage = 3 ⭐
TP3 조건 만족 = 빠른 trailing!
```

---

## 🎨 UI 통합 (= 「💉 포지션 추가」 모달 강화)

### 기존 모달 (= add-position-modal.js):
```
┌─────────────────────────────────────┐
│ 💉 포지션 추가 — VELVETUSDT SHORT   │
├─────────────────────────────────────┤
│ 마진 금액 (USDT): [____]            │
│ 주문 유형: ◉ MARKET  ◯ LIMIT       │
│ (LIMIT 시) 가격: [____]             │
├─────────────────────────────────────┤
│ [취소]  [💉 진입]                   │
└─────────────────────────────────────┘
```

### 신 모달 (= 체크박스 추가):
```
┌─────────────────────────────────────────┐
│ 💉 포지션 추가 — VELVETUSDT SHORT       │
├─────────────────────────────────────────┤
│ 마진 금액 (USDT): [____]                │
│ 주문 유형: ◉ MARKET  ◯ LIMIT           │
│ (LIMIT 시) 가격: [____]                 │
│                                          │
│ ☐ 📈 단계 진행 적용 (= TP3 빠른 활성화) │ ← 신!
│   (= current_stage +1, stage_plan 추가) │
├─────────────────────────────────────────┤
│ [취소]  [💉 진입]                       │
└─────────────────────────────────────────┘
```

### 사장님 사용:
- 체크 X (= 옛 그대로): 마진만 추가
- 체크 O (= 신!): 마진 추가 + 단계 진행 + TP3 활성화

---

## 🛡 검증 (= 헌법 5단계)

### 1. 사장님 사상 ✅
- 사장님 자율 (= 체크박스)
- TP3 빠른 활성화 = 자본 보호

### 2. 기존 코드 분석
- `add_position_to_strategy` (= lifecycle.py) = 기존 endpoint
- `trigger_next_stage_manually` (= control.py) = 기존 「▶」
- 신 endpoint = 두 함수 통합

### 3. 영향 분석
- 옛 「💉 포지션 추가」 = 영향 X (= 옛 동작)
- 신 옵션 (= advance_stage=True) = 사장님 명시 시만
- TP3 발동 = stage >= 3 조건 = 빠른 만족 가능

### 4. 검증
- 본인 소유 + 활성 strategy
- 트랜잭션 (= add-position + stage_plan 추가 = 모두 OR 모두 X)
- audit log

### 5. grep + python ast.parse

---

## 📊 시나리오 매트릭스

### S1: 1단계 진입 + 「💉 + 단계 진행」 = stage 2
- 옛: 1단계 + 마진 추가 = stage 1
- 신: 1단계 + 2단계 (신 추가) = stage 2

### S2: 2단계 진입 + 「💉 + 단계 진행」 = stage 3 (= TP3 활성!)
- 옛: 2단계 + 마진 추가 = stage 2
- 신: 2단계 + 3단계 (신 추가) = stage 3 ⭐ TP3 활성!

### S3: stage 10 + 「💉 + 단계 진행」 = 거부 (= 상한)
- stage 11 = 시스템 한도 초과 = 거부

### S4: Crisis 모드 + 「💉 + 단계 진행」 = OK
- Crisis = TP override (= 5/10/15/20)
- 사장님 신 stage = Crisis 진입 후 = TP1 +5% 즉시 발동 가능

### S5: 사장님 옛 strategy = 「💉」 (옛 그대로) + 신 옵션 둘 다 가능
- 사장님 자율 = 매번 선택

---

## 📋 Phase 분리

### Phase 1 ✅ (= 이 spec)

### Phase 2 — Backend
- POST `/strategies/{id}/add-position-with-stage`
- 트랜잭션 보호
- audit log (= STAGE_ADVANCED_MANUAL)

### Phase 3 — Frontend
- 「💉 포지션 추가」 모달 = 체크박스 추가
- 사장님 선택 → 신 endpoint 호출

### Phase 4 — 시나리오 pytest (= 선택)

---

## 🌿 사장님 결정

### 옵션 A: 즉시 Phase 2 + 3 진행 ⭐ (= 권장!)
- 1 PR = backend + frontend 통합
- 사장님 매일 운영 = 즉시 사용 가능

### 옵션 B: Phase 2 만 + 사장님 F12 fetch
- 빠른 = 다만 = UI 없음

---

> **Spec 작성**: 2026-06-09
> **위치**: `binance-auto-trader/ADD_POSITION_WITH_STAGE_SPEC_2026-06-09.md`
> **상태**: 영구 보존
> **다음**: Phase 2 + 3 통합 PR
