# 🛡 개발 교훈 영구 spec (2026-06-13)

> **사장님 critical 사건 = 영구 기록 + 다음 개발 시 = 절대 재발 X!**
>
> 작성: 2026-06-13 (사장님 BEATUSDT #110 청산 + 옛 캐시 + branch 문제 등 누적!)

---

## 🚨 사장님 critical 사건 누적 (= 영구!)

### **1️⃣ BEATUSDT #110 청산 = -3,143 USDT 손실!**
- **원인**: SL = `total_capital × 80% / lev` = USDT 절대 한도
- **silent bug**: 사장님 6단계 취소 → total_capital 6100 → 2700 → SL 한도 -2440 → -1080 → 청산!
- **재발 X 방법**: SL = **평단 기준 ROI** = 자본 무관!

### **2️⃣ Self-Check false positive = 매 시간 시끄러움!**
- **원인**: STOPPED/COMPLETED strategy 도 검사 + dedup X
- **silent bug**: 옛 종료된 strategy = 매 시간 반복 알림!
- **재발 X 방법**: ACTIVE 만 검사 + 24h dedup!

### **3️⃣ feat branch != main branch = 사장님 git pull 무효!**
- **원인**: 우리 작업 = feat branch / 사장님 운영 = main
- **silent bug**: PR 머지 X → main 옛 코드 → 사장님 신 fix 적용 X!
- **재발 X 방법**: **모든 작업 후 PR 머지!**

### **4️⃣ 브라우저 캐시 = 신 JS 로드 X!**
- **원인**: JS version 갱신 X → 브라우저 옛 JS 사용
- **silent bug**: 사장님 = "왜 안되지?" = 캐시 문제!
- **재발 X 방법**: **모든 JS 변경 = version 강제 갱신!**

### **5️⃣ HTML/JS col-span 불일치 = grid overflow!**
- **원인**: HTML 헤더 col-span-1 / JS 데이터 col-span-2
- **silent bug**: 청산가 컬럼 = 빈칸!
- **재발 X 방법**: **HTML/JS = col-span 일관성 검증!**

### **6️⃣ 사장님 사상 정확 파악 X = 잘못된 fix 반복!**
- **사건**: SL fix v1 (diff) → v2 (변경 X) → v3 (사전 차단) → v4 (ROI 기반!)
- **silent bug**: 잘못된 fix 반복 = 사장님 화남!
- **재발 X 방법**: **사장님 사상 = 명시 인용 + 즉시 정확 적용!**

---

## 🛡 영구 헌법 (= 다음 개발 절대 준수!)

### **헌법 23: 모든 작업 = PR 머지 = main 적용!**
```
1. feat branch 작업
2. commit + push
3. ⭐ PR 생성 + main 머지!
4. 사장님 git pull = 신 코드 적용!
```
= **PR 머지 안 하면 = 사장님 = 옛 코드!**

### **헌법 24: 모든 JS 변경 = version 강제 갱신!**
```python
# 모든 JS 변경 후:
sed -i 's/v=20260613vXX/v=20260613vYY/g' backend/app/static/index.html
```
= **사장님 브라우저 = 옛 캐시 = 신 JS 안 받음 = 영구 차단!**

### **헌법 25: HTML/JS col-span 일관성 검증!**
```javascript
// HTML 헤더 col-span 합 == 데이터 div col-span 합 == 12!
// JS code 갱신 시 col-span 절대 변경 X!
```
= **silent bug 영구 차단!**

### **헌법 26: 사장님 사상 = 명시 인용 우선!**
```
사장님 명시: "[사장님 인용]"
= 정확 사상 = 100% 이해 후 = fix!
= 추측 X = 잘못된 fix 반복 차단!
```

### **헌법 27: SL = 평단 기준 ROI = 영구!**
```python
# SL 사상 (= 사장님 명시 2026-06-13):
roi = (avg_entry vs mark_price) × leverage
if roi <= -sl_pct: SL!
# = total_capital 완전 무관!
# = 단계 capital 변경 = SL 영향 X!
```

### **헌법 28: 사장님 자율 청산 회피 = 100% 까지!**
```
사장님 사상:
"1단계 진입 후 청산가 직전 → 다음 단계 진입 → 청산가 멀어짐 → 반복!"
"손실 -100% 까지 자율 운영!"
= 증거금/포지션 추가 = 청산가 멀리 = 자율 안전!
```

---

## 📋 다음 개발 체크리스트 (= 영구 적용!)

### **A. 변경 사항 진행 시:**
- [ ] feat branch 작업
- [ ] 코드 변경 + 사장님 사상 명시 인용 주석
- [ ] HTML/JS col-span 일관성 검증 (= 같은 col-span!)
- [ ] commit + push
- [ ] **⭐ PR 생성 + main 머지!**
- [ ] **⭐ JS version 강제 갱신!** (= 캐시 차단!)

### **B. 사장님 검증 안내:**
- [ ] VPS = `git pull && docker compose restart`
- [ ] 브라우저 = **`Ctrl + Shift + R`** (= 강제 새로고침!)
- [ ] 사장님 = 신 모달 확인!

### **C. silent bug 발견 시:**
- [ ] 사장님 명시 인용
- [ ] 즉시 분석 + 정확 사상 파악
- [ ] **추측 X = 사장님 명시 인용으로 확인!**
- [ ] spec 작성 + 영구 보존
- [ ] 자동 worker 추가 (= 재발 자동 차단!)

### **D. 사장님 critical 사건 시:**
- [ ] 즉시 분석 + fix
- [ ] **사장님 자본 손실 = 시스템 책임 = 진심 사과!**
- [ ] 영구 spec 작성
- [ ] MEMORY 갱신
- [ ] 헌법 추가 (= 영구 보존!)

---

## 🚨 절대 금지 사항 (= 사장님 critical 위험!)

### **❌ 1. SL = USDT 절대값 계산!**
```python
# 절대 금지!
threshold = total_capital × sl_pct  # = USDT 절대값
```
= 단계 capital 변경 시 = SL 한도 변경 = 사장님 자본 손실!

### **❌ 2. 단계 capital 변경 시 = total_capital 자동 동기화!**
```python
# 절대 금지!
strategy.total_capital = sum(new_capitals)
```
= 사장님 옛 추가 자본 (증거금/포지션) = silent 삭제!

### **❌ 3. PR 머지 없이 = "fix 완료" 라고 보고!**
= 사장님 = 옛 코드 = 신 fix 미적용 = "왜 안되지?"!

### **❌ 4. JS version 갱신 없이 = 신 JS 푸시!**
= 사장님 브라우저 = 옛 캐시 = 신 JS 적용 X!

### **❌ 5. STOPPED/COMPLETED strategy 도 self-check 검사!**
= 옛 종료된 strategy = 매 시간 시끄러운 false positive!

### **❌ 6. 사장님 사상 = 추측 + 잘못된 fix!**
= 사장님 명시 인용 우선 = 정확 사상 파악 후 = fix!

---

## 🌟 사장님 자율 운영 시스템 = 영구 헌법!

### **헌법 19~28 (= 신 추가!):**
- 헌법 19: total_capital = 실제 투입 자본만!
- 헌법 20: 단계 capital 감소 시 = 청산 위험 사전 차단!
- 헌법 21: SL = 평단 기준 ROI -100%! (= 자본 무관!)
- 헌법 22: 단계별 청산 분석 = 명확 시각화!
- 헌법 23: 모든 작업 = PR 머지 = main 적용!
- 헌법 24: 모든 JS 변경 = version 강제 갱신!
- 헌법 25: HTML/JS col-span 일관성 검증!
- 헌법 26: 사장님 사상 = 명시 인용 우선!
- 헌법 27: SL = 평단 기준 ROI = 영구!
- 헌법 28: 사장님 자율 청산 회피 = 100% 까지!

= **총 28개 헌법 = 영구 보존!** 🛡

---

## 🙇 사장님 = 진심 죄송합니다!

옛 silent bug 누적 = 사장님 자본 -3,143 USDT 손실 + 시끄러운 알림 + 화남!

= **이제 = 영구 헌법 = 28개 = 재발 절대 X!** 🛡

= **사장님 critical 사고 = 시스템 진정한 영구 진화!** ✨🌟

---

## 📚 참고 spec 영구 보존:

- `docs/spec/total_capital_diff_spec_2026-06-11.md`
- `docs/spec/stage_calculation_spec_2026-06-11.md`
- `docs/spec/edit_mode_spec_2026-06-11.md`
- `docs/spec/current_price_action_spec_2026-06-11.md`
- `docs/spec/symbol_chart_orderbook_manual_trade_spec_2026-06-11.md`
- **`docs/DEVELOPMENT_LESSONS_LEARNED_2026-06-13.md`** (= 본 spec!)

= **사장님 시스템 = 진정한 자율 운영 = 영구!** 🛡✨🌟
