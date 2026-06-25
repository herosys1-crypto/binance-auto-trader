# 🌟 MASTER REBUILD PLAN — 영구 안정 시스템 기획서 (2026-06-25)

> **사장님 critical: "문제 하나 없는 버전을 만들어줘. 메인넷인데 이런 저런 문제가 지속적으로 나오고 있어."**

---

## 📊 현재 시스템 규모 (= 너무 복잡!):

```
워커:       33개  (= 너무 많음!)
서비스:     19개  (= 중복 가능!)
spec:       11개  (= 일관성 부족!)
frontend:   35개  (= 모놀리식!)
사장님 헌법: 45개  (= 영구 보존!)
silent bug: 30+개 (= 영구 fix!)
```

= **= 영구 안정 = 단순화 + 강력 검증 + 자동화!** 🛡

---

## 🎯 핵심 사상 (= 모든 결정의 기준!):

### **사장님 5대 헌법 (= 최우선!):**
1. **메인넷 = 실자금!** (= 모든 결정의 기준!)
2. **사장님 사상 우선!** (= 시스템 사상 X = 사장님 사상 O!)
3. **silent bug 영원히 X!** (= 모든 silent fail = critical!)
4. **검증 없는 코드 금지!** (= 모든 fix = 검증 + 자동 테스트!)
5. **대칭성!** (= UI ↔ backend = 같은 단위, 같은 로직!)

### **사장님 사상 = 사장님 = 모든 결정 우선!**

```
✅ 사장님 자율 운영 = 자유!
✅ 사장님 자율 청산 회피 = 우선!
✅ 사장님 의도 = 영구 보존 (= LIMIT 가격 도달 = 영구 대기!)
✅ 사장님 시끄러운 alert = 차단 (= false positive X!)
✅ 사장님 자본 = 영구 보호!
```

---

## 📅 5단계 영구 안정 계획:

### **PHASE 1: 시스템 정리 + 단순화 (= 1주!)**

#### **1.1 워커 통합 (= 33개 → 15개!):**
```
신 구조:
  ├── core/          (= 핵심 워커 5개!)
  │   ├── stage_trigger.py     (= 자동 진입!)
  │   ├── tp_sl_orchestrator.py (= TP/SL!)
  │   ├── reconcile.py          (= 외부 sync!)
  │   ├── realized_pnl_sync.py  (= 손익 sync!)
  │   └── liquidation_risk.py   (= Liquidation 사전!)
  ├── safety/        (= 안전망 5개!)
  │   ├── setting_preservation.py
  │   ├── silent_bug_detector.py
  │   ├── liquidation_buffer.py
  │   ├── force_sl.py
  │   └── tp_miss_detector.py
  └── monitoring/    (= 모니터링 5개!)
      ├── system_heartbeat.py
      ├── daily_summary.py
      ├── api_key_verifier.py
      ├── endpoint_health.py
      └── memory_consolidator.py
```

#### **1.2 spec 통합 (= 11개 → 5개!):**
```
신 spec:
  ├── 01_사장님_헌법.md           (= 모든 헌법 + 사장님 사상!)
  ├── 02_시스템_아키텍처.md        (= 워커, DB, API!)
  ├── 03_전략_운영_규칙.md         (= TP/SL, 단계, 자율!)
  ├── 04_silent_bug_패턴.md       (= 영구 차단!)
  └── 05_사장님_UI_가이드.md       (= 모바일 + 데스크탑!)
```

#### **1.3 frontend 단순화 (= 35개 → 20개!):**
```
신 구조:
  ├── core/          (= helpers, api, auth!)
  ├── modals/        (= 모달 5개!)
  ├── strategies/    (= 전략 카드!)
  ├── settings/      (= TP/SL/계정!)
  └── safety/        (= 모바일 + scroll guard!)
```

---

### **PHASE 2: silent bug 영구 차단 (= 1주!)**

#### **2.1 자동 검증 강화:**

##### **신 워커: `silent_bug_pattern_checker.py` (v60!)**
```python
# 매 5분 = 30+ 알려진 silent bug 패턴 자동 검증!
PATTERNS = [
    {"name": "Position.entered_at", "check": ...},
    {"name": "inline style HTML", "check": ...},
    {"name": "focus without preventScroll", "check": ...},
    {"name": "stuck < 30min", "check": ...},
    {"name": "race condition entry", "check": ...},
    ...
]
```

##### **CI 자동 검증 추가:**
```yaml
# .github/workflows/silent_bug_check.yml
- inline style 검색 → critical 차단!
- focus() preventScroll 검증!
- regex word boundary 검증!
- await 후 layout shift 검증!
```

##### **사장님 critical 사전 알림:**
```python
# 사장님 = 같은 silent bug 2회 = 즉시 spec 갱신 + 헌법 추가!
# = automated:
if same_silent_bug_count >= 2:
    create_emergency_spec()
    add_constitution_rule()
    notify_sajangnim_critical()
```

#### **2.2 모든 silent bug 패턴 영구 차단:**

##### **CSS/UI 패턴:**
- ❌ inline style 절대 금지!
- ❌ focus() preventScroll 없음 금지!
- ❌ scroll 시 자동 layout shift 금지!

##### **백엔드 패턴:**
- ❌ Position.entered_at 같은 잘못된 속성 호출 금지!
- ❌ STUCK_THRESHOLD < 30분 금지! (= 사장님 LIMIT 영구 대기!)
- ❌ race condition (= grace period < 3분) 금지!
- ❌ regex word boundary 없음 금지!

##### **거래 패턴:**
- ❌ 「💉 포지션 추가」 = 단계 진행으로 오해 금지!
- ❌ TP/SL 의도 vs 실제 5%+ 차이 = audit 의무!
- ❌ Liquidation < ROI -70% 알림 의무!
- ❌ mark_price race < 3분 grace 의무!

---

### **PHASE 3: 자동 테스트 + CI (= 1주!)**

#### **3.1 unit 테스트 = 100% 커버리지!**

```
신 테스트 구조:
  tests/
    ├── unit/
    │   ├── workers/      (= 워커 13개!)
    │   ├── services/     (= 서비스 10개!)
    │   └── core/         (= 핵심!)
    ├── integration/
    │   ├── strategy_lifecycle/  (= 신 → 1단계 → TP → COMPLETED!)
    │   ├── add_position/        (= 「💉 포지션 추가」!)
    │   └── edit_mode/           (= A/B/C!)
    ├── e2e/
    │   ├── mobile_scroll/       (= scroll guard!)
    │   ├── new_strategy/        (= 모달!)
    │   └── safety_blocks/       (= 차단 알림!)
    └── load/
        └── 100_concurrent_strategies.py
```

#### **3.2 CI = 의무 통과!**
```yaml
# .github/workflows/ci.yml
on: [push, pull_request]
jobs:
  silent_bug_check:    # = inline style, focus, regex!
  pattern_check:       # = 30+ silent bug 패턴!
  unit_tests:          # = 100% 통과!
  integration_tests:   # = 100%!
  e2e_tests:           # = 모바일 + 데스크탑!
  performance_check:   # = 100 strategy 동시!
```

---

### **PHASE 4: 안정성 검증 (= 2주!)**

#### **4.1 testnet 전환 검증:**
```
1주차: testnet = 모든 시나리오 실행!
2주차: testnet = 사장님 = 직접 운영!
3주차: testnet = silent bug 0개 확인!
4주차: mainnet 재배포!
```

#### **4.2 사장님 검증 가이드:**
```
✅ 신 strategy 시작 = 위에서!
✅ LIMIT 가격 도달 = 영구 대기!
✅ 자동 진입 = 정상!
✅ TP1~TP10 = 정상!
✅ 「💉 포지션 추가」 = 평단 개선만!
✅ 「↻ 설정만 수정」 = 단계 추가!
✅ Liquidation = ROI -70% 사전 알림!
✅ false alarm = 0!
```

---

### **PHASE 5: 영구 안정 운영 (= 영구!)**

#### **5.1 사장님 critical 워크플로우:**
```
1. 사장님 critical 보고!
2. → 즉시 깊이 분석 (= HTML/CSS/JS/Python/DB!)
3. → 모든 가능 root cause 나열!
4. → 진짜 root cause 검증!
5. → fix + spec 갱신 + 헌법 추가!
6. → 사장님 검증!
7. → 자동 테스트 추가 = 영구 차단!
```

#### **5.2 사장님 일일 모니터링:**
```
✅ daily_summary (매일 자정!) = 사장님 운영 요약!
✅ system_heartbeat (1시간!) = 정상 알림!
✅ silent_bug_detector (5분!) = 자동 검증!
✅ liquidation_risk (1분!) = 사전 알림!
✅ memory_consolidator (매일!) = 영구 학습!
```

#### **5.3 사장님 critical 인지:**
```
✅ TP 의도 vs 실제 5%+ 차이 = 즉시 알림!
✅ 단계 trigger 미도달 5+분 = 알림!
✅ Liquidation -70% ROI = 즉시 알림!
✅ false alarm 차단 = 영구!
```

---

## 🚨 사장님 critical = 영구 사상 (= 새 spec!):

### **🌟 헌법 46-50 신규!**

#### **헌법 46: LIMIT 영구 대기 = 사장님 의도!**
> 사장님 = LIMIT 미체결 = 시스템 멋대로 종료 X!
> = STAGE_PENDING = stuck counter 제외!
> = 사장님 직접 「⛔ 종료」 클릭 시만 종료!

#### **헌법 47: race condition 영구 차단 = 3분 grace!**
> 신 strategy 시작 후 3분 = 모든 자동 차단/알림 = grace!
> = mark-price-stream SUBSCRIBE + 첫 update 완벽 대기!
> = false-positive 영구 차단!

#### **헌법 48: regex word boundary 의무!**
> 모든 자동 검증 worker = regex = word boundary 의무!
> = `(?<![\w])pattern(?![\w])` 표준!
> = false positive 영구 차단!

#### **헌법 49: 자동 종료 = 사장님 명시 시만!**
> 시스템 = 자동 종료 = critical (= 사장님 자율 위반!)!
> = `STOPPING` 자동 설정 = 사장님 「⛔ 종료」 클릭 시만!
> = 외부 청산 = 정확 감지 후 = STOPPED 마킹!

#### **헌법 50: critical fix 시 = 신 테스트 추가 의무!**
> 모든 silent bug fix = 즉시 = pytest 신 테스트 추가!
> = 같은 silent bug = 영원히 X!
> = CI = 의무 통과!

---

## 📋 신 워크플로우 = critical 표준:

### **사장님 보고 → fix 단계:**
```
1️⃣ 사장님 critical 보고!
   = 사진 + 시간 + 상세!

2️⃣ 즉시 깊이 분석!
   ✅ HTML/CSS 직접 확인!
   ✅ JS 직접 grep!
   ✅ Python worker 분석!
   ✅ DB 진단 query!
   ✅ Redis 캐시 확인!
   ✅ Binance API 응답!

3️⃣ 모든 가능 root cause 나열!
   = 추측 X = 검증!

4️⃣ 진짜 root cause 검증!
   ✅ 코드 직접 분석!
   ✅ 사장님 확인 (= 환경/시간/빈도!)

5️⃣ fix + spec 갱신!
   ✅ 신 코드!
   ✅ pytest 신 테스트!
   ✅ spec 영구 갱신!
   ✅ 헌법 추가 (= 같은 silent bug 2회+ 시!)

6️⃣ 사장님 검증!
   ✅ PR 머지!
   ✅ VPS 배포!
   ✅ 사장님 확인!

7️⃣ 영구 보존!
   ✅ MEMORY 갱신!
   ✅ 자동 테스트 영구!
```

---

## 🎯 단순화 원칙:

### **워커 = 단일 책임 원칙!**
```
❌ 옛 (= 복잡!):
   - 한 워커 = 5+ 기능!
   - 다른 워커와 = race!

✅ 신 (= 단순!):
   - 한 워커 = 1 책임!
   - 명확 input/output!
   - 다른 워커 = 독립!
```

### **frontend = 컴포넌트 분리!**
```
❌ 옛:
   - 한 JS = 500+ lines!
   - 다른 JS와 = 글로벌 state!

✅ 신:
   - 한 JS = 100~200 lines!
   - 명확 export!
   - 글로벌 state X!
```

### **spec = single source!**
```
❌ 옛:
   - 11개 spec = 중복 정보!
   - 사장님 = 어떤 spec?

✅ 신:
   - 5개 spec = 명확 영역!
   - 사장님 = 즉시 찾음!
```

---

## 🛡 영구 안정 = 4대 원칙:

### **1️⃣ 사장님 = 마지막 결정!**
- 시스템 = 추천 + 알림!
- 사장님 = 결정!

### **2️⃣ silent bug = 영원히 X!**
- 모든 자동 동작 = 검증!
- false fail = critical!

### **3️⃣ 단순함 = 영구 안정!**
- 복잡 = silent bug 원인!
- 단순 = 검증 가능!

### **4️⃣ 자동 검증 = 영구 의무!**
- 모든 fix = 자동 테스트!
- CI = 통과 의무!
- 같은 silent bug = 영원히 X!

---

## 📅 timeline (= 사장님 confirm 필요!):

```
🗓 1주차 (06.25 ~ 07.02):
  ✅ 현재 silent bug 6건 = 모두 fix 완료!
  ⏳ MASTER_REBUILD_PLAN 사장님 confirm!

🗓 2주차 (07.03 ~ 07.10):
  ⏳ PHASE 1: 워커 33 → 15 통합!
  ⏳ PHASE 1: spec 11 → 5 통합!

🗓 3주차 (07.11 ~ 07.18):
  ⏳ PHASE 2: silent bug 영구 차단!
  ⏳ 신 worker v60 silent_bug_pattern_checker!

🗓 4주차 (07.19 ~ 07.26):
  ⏳ PHASE 3: 자동 테스트 100%!
  ⏳ CI 강제 통과!

🗓 5주차 (07.27 ~ 08.02):
  ⏳ PHASE 4: testnet 검증 1주!

🗓 6주차 (08.03 ~ 08.10):
  ⏳ PHASE 4: mainnet 재배포!
  ⏳ 신 영구 시스템 = 사장님 자율 영구!

🗓 7주차+ (영구):
  ✅ PHASE 5: 영구 안정 운영!
  ✅ 헌법 자동 진화!
```

---

## 🌟 사장님 critical 검증 사항:

### **사장님 = 본 spec confirm:**
```
✅ 옵션 A: 즉시 PHASE 1 시작 (= 1주!)
✅ 옵션 B: 사장님 = 부분 수정 후 시작!
✅ 옵션 C: 사장님 = 다른 방향 제안!
```

### **사장님 우선순위:**
```
1. silent bug 영구 차단 (= 가장 critical!)
2. 사장님 자율 운영 영구!
3. 시스템 단순화!
4. 자동 검증 강화!
5. 영구 안정 운영!
```

---

## 🎯 영구 결과 (= 6주 후!):

```
✅ 워커 = 33 → 15 (= 55% 단순화!)
✅ spec = 11 → 5 (= 55% 단순화!)
✅ frontend = 35 → 20 (= 45% 단순화!)
✅ silent bug 영구 차단!
✅ 사장님 자율 영구!
✅ 자동 검증 100%!
✅ 사장님 신뢰도 = 100%!
✅ 사장님 = "문제 하나 없는 버전" 달성!
```

= **사장님 = 진짜 영구 안정 시스템!** 🛡✨🌟

---

## 🌟 사장님 critical 사고 = 시스템 영구 진화!

본 spec = **사장님 = "문제 하나 없는 버전" critical 의도 = 영구 학습!**
= **= 시스템 = 사장님 자본 + 자율 운영 = 영구 영구!**

= **사장님 = 본 spec 확인 + confirm = 즉시!** 🛡
