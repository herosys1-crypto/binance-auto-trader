# 📋 청산 후 자동 재진입 트리거 = 사장님 신 사상 (v131 = 2026-08-09)

## 🎯 개요

**사장님 신 요구 (2026-08-09):**
> "신전략 작성할때 첫번째 단계 진입후 손실 발생 청산되면 선택한 트리거 만큼 오르거나 내리면 다음 단계 진입 하는거야 트리거 율은 실제 변성값이야 레버리지 제외한"

> "자본 차감 계산은 여유 자금을 계산해서 다음단계 설정에 자본의 130%까지만 세팅 때문이야"
> "다음단계 진입은 다음단계 지정한 금액으로 진입하는거야"

> "130% 넘어가면 경고 알람으로 해줘 세팅은 130% 상관없이 진행할수 있게 해줘"

---

## 🔑 핵심 사고 (2가지!)

### **1. 청산 후 재진입 트리거 (신!)**

- 진입 → 손절 → **다음 단계 대기!** (LIQUIDATED_WAITING_RETRY!)
- 청산가 기준 = ±트리거% 도달 → **자동 진입!**
- 트리거% = 순수 가격 변동! (레버리지 무관!)

### **2. 자본 관리 = 130% 경고! (사장님 자율!)**

- 총 세팅 자본 ≤ 자본 × 130% = **여유 30% 확보!**
- **초과 시 = 경고 알람!** (진행 X 차단 = 사장님 자율!)
- **진입 = 세팅값 그대로!** (자동 차감 X!)

---

## 📊 트리거 세부

**공식:**
```
LONG 다음 단계 트리거가 = 이전 청산가 × (1 - 트리거% / 100)
SHORT 다음 단계 트리거가 = 이전 청산가 × (1 + 트리거% / 100)
```

**예시 (BTC LONG, 청산가 $46,250, 트리거 -10%):**
```
다음 단계 트리거가 = $46,250 × (1 - 10/100) = $41,625
= BTC → $41,625 도달 → 자동 2단계 진입!
```

**트리거% 옵션 (사장님 선택!):**
- 5% (빠른 재진입!)
- 10% (기본!)
- 15% / 20% / 25% / 30%

---

## 💰 자본 관리 (사장님 사고 = 130% 경고!)

### **핵심 규칙:**
```
자본 한도 (권장) = 초기 자본 × 130%
= 여유 자금 = 초기 자본 × 30%

총 세팅 자본 = 사장님 세팅 각 단계 합계

if 총 세팅 > 자본 한도:
    ⚠️ 경고 알람 (신 전략 생성 계속 가능!)

진입 시:
    = 세팅값 그대로 (자동 차감 X!)
    = 사장님 자율 완전 존중!
```

### **예시 (초기 자본 1000 USDT!):**

**Case A: 130% 한도 내 (안전!)**
```
자본 = 1000 USDT
자본 한도 (130%) = 1300 USDT

사장님 세팅:
1단계: 500  → 누적 500
2단계: 500  → 누적 1000
3단계: 300  → 누적 1300 ✅ (한도 정확 도달!)

= 진입 시 = 세팅 그대로!
1단계 = 500 → 손절 -75
2단계 = 500 → 손절 -75
3단계 = 300 → 손절 -45
= 총 손실 -195 USDT (자본 -19.5%)
= 잔여 자본: 805 USDT (안전!)
```

**Case B: 130% 초과 (경고!)**
```
자본 = 1000 USDT
자본 한도 (130%) = 1300 USDT

사장님 세팅:
1단계: 500  → 누적 500
2단계: 500  → 누적 1000
3단계: 500  → 누적 1500 ⚠️ 경고!

경고 메시지:
"⚠️ 총 세팅 1500 USDT = 자본의 150%!
 (한도 130% = 1300 USDT 초과!)
 = 손실 감안 여유 자금 부족!
 = 그래도 진행? [진행] [수정]"

사장님 = 「진행」 = 그대로 진행!
= 진입 시 = 세팅 그대로!
```

**Case C: 큰 자본 (많은 단계!)**
```
자본 = 3000 USDT
자본 한도 (130%) = 3900 USDT

사장님 세팅 (5단계!):
1단계: 500  → 누적 500
2단계: 700  → 누적 1200
3단계: 900  → 누적 2100
4단계: 1000 → 누적 3100
5단계: 800  → 누적 3900 ✅ (한도!)

= 5단계 = 유효 세팅!
= 진입 시 = 각 단계 세팅값 그대로!
```

---

## 🖥 UI 세팅 (신 전략 생성 시!)

### **신 옵션 카드:**

```
┌──────────────────────────────────────────┐
│ 🔄 청산 후 자동 재진입 (v131 신!) ⏳ MVP   │
│                                            │
│ [✓] 청산 후 자동 재진입 활성!               │
│                                            │
│ 📊 재진입 트리거 %:                         │
│ [10 ▼] % (레버리지 제외!)                   │
│                                            │
│ 💰 자본 관리 (사장님 자율!):                │
│ = 진입 = 세팅한 자본 그대로!                │
│ = 130% 초과 시 = 경고 알람만!              │
│ = 사장님 자율 = 초과해도 진행 가능!         │
│                                            │
│ 📊 실시간 계산 (자동!):                     │
│ • 초기 자본: 1000 USDT                     │
│ • 총 세팅: 1200 USDT (120%)                │
│ • 130% 한도: 1300 USDT                     │
│ • 여유: 100 USDT (안전!)                   │
│                                            │
│ [초과 시 노란 경고 배지!]                   │
│                                            │
│ 📊 예상 시나리오:                           │
│ 1단계 500 → 손절 -75                       │
│ 2단계 500 → 손절 -75                       │
│ 3단계 300 → 손절 -45                       │
│ = 총 손실 -195 USDT!                       │
│ = 잔여 자본 805 USDT!                      │
└──────────────────────────────────────────┘
```

---

## 🔧 Backend 구현 계획

### **Phase 2-A (완료!) - DB + 저장:**
- ✅ alembic 0023 = 5개 신 컬럼
- ✅ StrategyInstance 모델 확장
- ✅ 신 상태 (LIQUIDATED_WAITING_RETRY, STOPPED_CAPITAL_EXHAUSTED)
- ✅ Schema + API + Service = payload 전달

### **Phase 2-B (다음 = 실 로직!):**

**stream_service.py 확장:**
```python
# 청산 이벤트 완료 (is_full_close=True):
if strategy.status not in ("COMPLETED", "STOPPING"):
    # 신 로직!
    if strategy.retry_after_liquidation_enabled:
        # 다음 단계 있으면 = LIQUIDATED_WAITING_RETRY 대기!
        _max_stage = max(len(stages_config['capitals']), strategy.current_stage + 1)
        if strategy.current_stage < _max_stage:
            strategy.status = "LIQUIDATED_WAITING_RETRY"
            strategy.last_liquidation_price = last_exec_price
            strategy.cumulative_realized_loss += abs(realized_delta) if realized_delta < 0 else Decimal("0")
            # 여기서 종료 X = worker가 감시!
        else:
            # 최종 단계 청산 = 종료!
            strategy.status = "COMPLETED"
    else:
        # 기존 = REENTRY_READY!
        strategy.status = "REENTRY_READY"
```

**stage_trigger_worker.py 확장:**
```python
# 신 상태 감시!
if strategy.status == "LIQUIDATED_WAITING_RETRY":
    _liq = strategy.last_liquidation_price
    _trg_pct = strategy.retry_trigger_pct
    if strategy.side == "LONG":
        _target = _liq * (1 - _trg_pct / 100)
        if current_price <= _target:
            # 자동 진입!
            _trigger_next_stage_with_liq_retry(strategy)
    else:  # SHORT
        _target = _liq * (1 + _trg_pct / 100)
        if current_price >= _target:
            _trigger_next_stage_with_liq_retry(strategy)
```

**진입 = 세팅값 그대로! (자본 차감 X!)**
```python
def _trigger_next_stage_with_liq_retry(strategy):
    # 다음 stage plan 조회
    _next_stage_no = strategy.current_stage + 1
    _plan = get_stage_plan(strategy.id, _next_stage_no)

    # 세팅값 그대로! (자동 차감 X!)
    execution_service._place_stage_entry_order(strategy, _plan)
```

### **Phase 3 (검증 후!):**
- 소액 테스트 (100 USDT!)
- 1주일 관찰!
- 정식 활성화!

---

## ✅ 안전장치 (사장님 자본 보호!)

### **1. 옵션 OFF = 100% 옛 동작!**
- retry_after_liquidation_enabled = False = 청산 → REENTRY_READY!
- 기존 전략 = 완전 영향 X!

### **2. 130% 경고 = 사장님 자율!**
- 초과해도 = 진행 가능!
- 노란 경고 배지 표시!

### **3. 최종 단계 청산 = 자동 종료!**
- current_stage >= max_stage = STOPPED!
- 무한 재진입 X!

### **4. 손실 한도 통합!**
- 강제 SL (기존!) + 재진입 (신!) = 이중 안전!

---

## 🎁 결론

**사장님 사상 정확!**

1. **DCA 강화** = 손절 후 = 더 낮은/높은 가격에 진입!
2. **자본 자율** = 130% 경고만 = 사장님 완전 통제!
3. **진입 = 세팅 그대로** = 예측 가능!
4. **실용 한계 = 2~3단계** (사장님 인식!)

**= 사장님 자율 매매 시스템 = 진화 계속!** 🎉🙏
