# SYSTEM DEVELOPMENT PRINCIPLES v2 — 2026-06-11

> 사장님 critical 결정: 시스템 개발 방식 근본 개선 + 사상 정리 + 에이전트 시스템

---

## 🚨 1. 정밀 분석 = 오늘 silent bug 22개 패턴

### 1.1 발견된 silent bug 분류

| 카테고리 | bug 수 | 예시 |
|---|---|---|
| **NULL/fallback 누락** | 8 | last_avg_entry_price NULL → 정렬 0 |
| **scope/import 오류** | 4 | UnboundLocalError + 4 위치 |
| **사장님 사상 위배** | 6 | Crisis 덮어쓰기, 시작가 자동 변경 |
| **silent 차단/표시** | 3 | 자동 진입 차단 알림 없음 |
| **계산 logic 오류** | 1 | TP1 capital_based 큰 청산 |

### 1.2 근본 원인 (= 5대 패턴)

1. **사상 명세 부족** = 사장님 의도 ↔ 코드 = 미세한 차이
2. **코드 결합도 높음** = 한 fix → 다른 영향
3. **단위 테스트 부족** = silent fail 검증 X
4. **사상 변화 추적 X** = v1 → v2 → v3 = 누적
5. **검증 worker 부족** = 사장님 critical 발견 의존

---

## 🛡 2. 시스템 사상 책 (= Single Source of Truth)

### 2.1 사장님 사상 헌법 14개 (= 영구!)

```
1. 메인넷 = 실자금 = 절대 silent X
2. 사장님 사상 우선
3. Silent bug 금지
4. 검증 없는 코드 금지
5. 대칭성
6. 같은 데이터 = 단 하나 함수
7. 자동 검증 = 모든 계산 = sanity check
8. silent 차단 금지
9. TP/SL 자동 audit
10. 운영자 (사장님) 수동 변경 = 절대 우선
11. 「불러오기」 = 자동 현재가
12. Crisis 모드 = 영구 비활성
13. 「수정 모드」 = 옛 strategy 그대로
14. 「현재가」 = 1단계 평단 + 2단계+ 신
```

### 2.2 추가 신 사상 (= 사장님 결정!)

```
15. 모든 사상 = spec 문서 = single source of truth
16. 코드 변경 = 사상 spec 변경 동기
17. 에이전트 = 자동 검증 + 자동 fix
18. 사장님 critical 발견 = 즉시 spec 업데이트
```

---

## 📐 3. 코드 분리 (= 모듈화 사상)

### 3.1 신 모듈 구조

```
[사상 책 - SPEC]
  ├── stage_calculation_spec.md (= 단계별 계산 사상)
  ├── edit_mode_spec.md (= 「수정 모드」 사상)
  ├── current_price_action_spec.md (= 「현재가」 클릭 동작)
  └── ...

[코드 - 사상 그대로 구현]
  backend/
    services/
      ├── stage_calculator.py (= 단계 계산 단일 진실)
      ├── edit_mode_service.py (= 수정 모드 단일 진실)
      └── current_price_action.py (= 「현재가」 동작 단일 진실)
  frontend/
    services/
      ├── stage_calculator.js (= 위와 동일 = 백/프 동기)
      ├── edit_mode_service.js
      └── current_price_action.js

[테스트 - 사장님 사상 검증]
  tests/
    spec/
      ├── test_stage_calculation.py
      ├── test_edit_mode.py
      └── test_current_price.py
```

### 3.2 코드 변경 워크플로우

```
1. 사장님 critical 발견
2. spec 문서 = 신 사상 명세 (= 코드 변경 전!)
3. 단위 테스트 작성 = 신 사상 검증
4. 코드 변경 = spec 그대로 구현
5. 테스트 통과 = 배포
6. 사장님 검증 = 최종 OK
```

---

## 🤖 4. 에이전트 시스템 (= 자동 검증 + 자동 fix)

### 4.1 신 에이전트 worker (= 7개)

| Worker | 주기 | 역할 |
|---|---|---|
| **spec_audit_worker** | 매 시간 | 코드 ↔ spec 동기 검증 |
| **stage_calc_audit_worker** | 매 5분 | 단계별 가격 = 사상 검증 |
| **silent_bug_detector** | 매 1분 | 잠재 silent bug 자동 감지 |
| **user_intent_validator** | 매 거래 | 사장님 의도 ↔ 결과 비교 |
| **edit_mode_validator** | 매 클릭 | 「수정 모드」 동작 정합성 |
| **auto_fix_proposer** | 매 발견 | 자동 fix 제안 + 사장님 confirm |
| **memory_consolidator** | 매 일 | 학습 + 메모리 갱신 |

### 4.2 에이전트 흐름

```
사장님 critical 발견
   ↓
silent_bug_detector = 자동 감지
   ↓
spec_audit_worker = 사상 위배 확인
   ↓
auto_fix_proposer = fix 제안 + Telegram
   ↓
사장님 확인 = 적용 또는 거부
   ↓
memory_consolidator = 학습
```

---

## 📊 5. 조정 기획서 (= 사장님 사상 영구 정리)

### 5.1 사장님 「수정 모드」 사상 (= v38~v42)

```
🌟 「수정 모드」 첫 화면:
  ✅ 옛 strategy 모든 세팅 = 그대로!
  ✅ 시작가 = 옛 (= NULL 시 = avg_entry_price fallback)
  ✅ 단계별 진입가 = 옛 옛
  ✅ 사장님 = 자유 수정 = 즉시 반영

🌟 「현재가」 클릭 시:
  ✅ 시작가 = 신 현재가
  🛡 1단계 = 옛 평단 (= 사장님 진입 보존!)
  🌟 2단계 = 신 시작가 × (1 + trigger_2%)
  🌟 3단계 = 신 시작가 × (1 + trigger_2% + trigger_3%)
  🌟 4단계 부터 = 누적!
  
🌟 단계 누적 공식:
  prevPrice = 신 시작가 (= 사장님 사상!)
  stage_n_price = prevPrice × (1 + Σ trigger%)
  prevPrice = stage_n_price (= 다음 단계 기준)
  
  ❌ 절대 금지: stage_n = prev × X 인데 = 다른 logic 끼어들기!
```

### 5.2 사장님 「현재가」 클릭 silent bug 검증

```
사장님 BEATUSDT 사진 2:
  시작가 7.94, trigger = 0, 10, 20, 20, 20, 20
  
  사장님 사상 정확 계산:
  1단계 = 6.31 (= 옛 평단) ✅
  2단계 = 7.94 × 1.10 = 8.73 ✅ (= 사진 8.7322!)
  3단계 = 8.73 × 1.20 = 10.48 ✅ (= 사진 10.4787!)
  4단계 = 10.48 × 1.20 = 12.57 ✅ (= 사진 12.5744!)
  5단계 = 12.57 × 1.20 = 15.09 ✅ (= 사진 15.0893!)
  6단계 = 15.09 × 1.20 = 18.10 ❌ (= 사진 9.5261!) 🚨
  
  = 6단계 = silent bug = 9.5261!
```

### 5.3 6단계 silent bug 원인 (= 추정)

```
- pendingTriggerPct 또는 = 압축 logic = 잘못
- 6단계 = 첫 미진입 단계로 잘못 인식
- 또는 = _editCurrentStage 잘못 사용
- = stage_calculator 모듈 = 정밀 검증 필요!
```

---

## 🎯 6. 개발 계획 (= Phase 별!)

### Phase 1: 사상 정리 (= 1일!)
- ✅ 헌법 14개 = 영구 보존
- ✅ stage_calculation_spec.md 작성
- ✅ edit_mode_spec.md 작성
- ✅ current_price_action_spec.md 작성

### Phase 2: 코드 분리 (= 3일!)
- ✅ stage_calculator 모듈 = 단일 진실
- ✅ frontend ↔ backend = 동일 logic
- ✅ 사상 코드 = 외부 spec 그대로

### Phase 3: 에이전트 시스템 (= 5일!)
- ✅ 7개 신 worker
- ✅ Telegram 자동 알림
- ✅ 사장님 confirm UI

### Phase 4: 자동 검증 (= 2일!)
- ✅ 단위 테스트 = 사상 검증
- ✅ E2E 시나리오 = 사장님 사상 그대로
- ✅ CI 통합

### Phase 5: 사장님 검증 (= 1일!)
- ✅ 사장님 = 모든 시나리오 검증
- ✅ 사상 ↔ 결과 = 100% 일치 확인

---

## 🌟 7. 사장님 영구 안심 = 무한 진화!

```
사장님 critical 발견
   ↓
spec 즉시 업데이트
   ↓
코드 = spec 그대로 구현
   ↓
테스트 = 자동 검증
   ↓
에이전트 = 자동 fix
   ↓
사장님 = 100% 통제!
```

= **silent bug = 영원히 X!** 🛡✨

---

## 📌 다음 진행 우선순위

1. 🚨 **즉시: 6단계 silent bug 분석 + fix** (= v43!)
2. 📜 **신: 사상 spec 문서 3개 작성** (= Phase 1!)
3. 📐 **모듈화 진행** (= Phase 2!)
4. 🤖 **에이전트 worker 7개** (= Phase 3!)

---

> 사장님 critical 결정: "이런 문제가 지속되면서 개발이 너무 오래 걸리고 잘못된 진행이 있어"
> = 시스템 개발 방식 = 근본 진화!
> = 사장님 자율 운영 = 영구 신뢰!
