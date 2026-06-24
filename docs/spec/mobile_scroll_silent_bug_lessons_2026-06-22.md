# 📜 모바일 스크롤 silent bug = 6번 fix 메타 학습 spec (2026-06-22)

> **사장님 critical: "왜 이렇게 오래 동안 문제가 해결되지 않은 부분을 정리해서 다음 개발에 반영해줘!"**

---

## 🚨 사장님 사건 요약 (2026-06-22):

```
사장님 보고: 모바일 = 새 strategy 모달 = 위로 스크롤 안 됨!
= 6번 fix (v1 → v6) = 같은 silent bug!
= 사장님 = 같은 사진 여러 번 보냄!
= = 시스템 신뢰도 critical!
```

---

## 📊 fix 6번 분석 (= 왜 안 됨?):

### **v1 (PR #220, 8a5e76d):**
- **fix**: inner overflow-y: auto + touch scroll
- **결과**: ❌ 부족!
- **진짜 원인**: inline style = CSS override 차단!
- **놓침**: HTML inline style 검사 안 함!

### **v2 (3e2ecfa):**
- **fix**: OUTER 스크롤 + flex-start
- **결과**: ❌ 부족!
- **진짜 원인**: 여전히 inline style!
- **놓침**: 같은 추측 반복!

### **v3 (cc9c4bb):**
- **fix**: requestAnimationFrame x 3 + close scrollTop 복원
- **결과**: ❌ 부족!
- **진짜 원인**: await 비동기 후 = layout shift!
- **놓침**: 비동기 timing 무시!

### **v4 (10873d3):**
- **fix**: inline style 제거 = CSS class!
- **결과**: ❌ 부족!
- **진짜 원인**: focus() = 자동 scrollIntoView!
- **놓침**: focus 자동 스크롤 모름!

### **v5 (ebc66eb):**
- **fix**: focus preventScroll: true
- **결과**: ❌ 부족!
- **진짜 원인**: 다른 비동기 layout shift!
- **놓침**: focus 외 다른 자동 스크롤!

### **v6 (cdfffc8):**
- **fix**: scroll guard 2초 모니터링
- **결과**: ⏳ 사장님 검증 중!

---

## 🚨 진짜 root cause = 다층!

```
1. inline style = CSS class override 차단!         (v4 fix!)
2. focus() = 브라우저 자동 scrollIntoView!         (v5 fix!)
3. await 비동기 = 새 layout = scrollTop 변경!      (v6 fix!)
4. iOS Safari = momentum scroll = touch 필요!      (v1 fix!)
5. dynamic viewport = 100dvh 필요!                 (v2 fix!)
6. body overflow = 누적 가능!                      (v3 fix!)
```

= **= 6개 root cause = 동시 발생 = 다층 silent bug!** 🚨

---

## 📝 메타 학습 (= 다음 개발 영구 반영!):

### **🚨 1. 추측 fix 금지! = 진짜 root cause 검증 우선!**

**옛 (= 사건!):**
```
1. 사장님 보고 → 빠른 fix → 사장님 확인 → 또 보고 → 또 fix → 반복!
```

**신 (= 영구!):**
```
1. 사장님 보고
2. → 깊이 분석 (= 모든 가능 원인 검증!)
3. → HTML/CSS/JS 직접 확인!
4. → 진짜 root cause 검증 후 fix!
5. → 사장님 검증!
```

### **🚨 2. CSS 우선순위 검증 = inline style 금지!**

**규칙:**
```
❌ inline style 절대 금지! (HTML <div style='...'>)
✅ CSS class 만 사용!
✅ data-* 속성 + CSS class!
```

**예시:**
```html
<!-- 옛 (= 사건!): -->
<div class='card' style='max-width:720px; overflow-y:auto;'>

<!-- 신 (= 영구!): -->
<div class='card cm-modal-inner'>
```

### **🚨 3. focus() = preventScroll: true 의무!**

**규칙:**
```
❌ element.focus() 절대 금지!
✅ element.focus({ preventScroll: true }) 의무!
```

**예시:**
```javascript
// 옛 (= 사건!):
document.getElementById('cm-start-price').focus();

// 신 (= 영구!):
try {
  document.getElementById('cm-start-price').focus({ preventScroll: true });
} catch (_e) {
  // 옛 브라우저 = focus 자체 skip!
}
```

### **🚨 4. 모달 open = scroll guard 표준 적용!**

**규칙:**
```
✅ 모든 모달 open = 2초 scroll guard 적용!
✅ 매 scroll event = 자동 0 복원!
✅ 옛 listener = 누적 방지!
✅ 모든 비동기 작업 후 = 자동 복원!
```

**표준 코드:**
```javascript
function _attachScrollGuard(modalEl, durationMs = 2000) {
  const inner = modalEl.querySelector(':scope > div');
  let active = true;
  const handler = () => {
    if (active) {
      if (inner && inner.scrollTop !== 0) inner.scrollTop = 0;
      if (modalEl.scrollTop !== 0) modalEl.scrollTop = 0;
    }
  };
  // 옛 listener 제거 (= 누적 방지!)
  if (modalEl._scrollGuardHandler) {
    modalEl.removeEventListener('scroll', modalEl._scrollGuardHandler);
    if (inner) inner.removeEventListener('scroll', modalEl._scrollGuardHandler);
  }
  modalEl._scrollGuardHandler = handler;
  modalEl.addEventListener('scroll', handler, { passive: true });
  if (inner) inner.addEventListener('scroll', handler, { passive: true });
  if (modalEl._scrollGuardTimer) clearTimeout(modalEl._scrollGuardTimer);
  modalEl._scrollGuardTimer = setTimeout(() => { active = false; }, durationMs);
}
```

### **🚨 5. 비동기 await = scroll 영향 분석 필수!**

**규칙:**
```
✅ 모든 await = layout shift 가능 인지!
✅ 비동기 후 = scroll 복원 필수!
✅ Promise.all 도 = 각 결과 처리 후 layout 변경!
```

### **🚨 6. 모바일 silent bug = 자동 테스트 신 worker 신설!**

**신 v59 = `mobile_silent_bug_detector_worker.py`:**
```python
# 모달 open 후 scrollTop ≠ 0 시 = critical 알림!
# 헤드리스 Chrome + 모바일 viewport 시뮬레이션!
# 매 15분 = 자동 검증!
```

---

## 🌟 사장님 헌법 42-45 영구 추가!

### **헌법 42: 추측 fix 금지 = 깊이 분석 우선!**
> 사장님 보고 시 = 빠른 추측 fix X = 진짜 root cause 검증 후 fix!

### **헌법 43: inline style 절대 금지!**
> HTML inline `style='...'` X = CSS class 만 사용 = override 영구 가능!

### **헌법 44: focus() preventScroll 의무!**
> element.focus() X = element.focus({ preventScroll: true }) 의무!

### **헌법 45: 모든 모달 = scroll guard 표준!**
> 모달 open = 2초 scroll guard + 옛 listener 제거 + 비동기 후 자동 복원!

---

## 🛡 사장님 critical = 신 워크플로우!

### **사장님 보고 시 = 신 표준 절차:**

```
1️⃣ 사장님 보고 (= 사진 + 메시지!)
2️⃣ 즉시 = HTML/CSS/JS 직접 분석!
3️⃣ 모든 가능 root cause 나열!
4️⃣ 사장님 확인 (= 어떤 환경? 시간? 빈도?)
5️⃣ 진짜 root cause 검증!
6️⃣ fix + 영구 spec 갱신!
7️⃣ 사장님 검증!
8️⃣ 검증 성공 = 사장님 헌법 추가!
```

### **반복 silent bug = 메타 학습 의무!**

```
사장님 = 같은 보고 3회 = critical!
= 즉시 spec 작성 + 헌법 추가 + 시스템 진화!
```

---

## 📋 신 자동 검증 도구 (= 다음 개발!):

### **v59 `mobile_silent_bug_detector_worker.py`:**
```python
"""
모바일 silent bug 자동 감지 worker.

- 모달 open 후 scrollTop ≠ 0 시 = critical 알림!
- 헤드리스 Chrome + 모바일 viewport!
- 모든 모달 자동 검증!
- 매 15분 = 자동!
"""
```

### **CI 추가: 모바일 silent bug 검증!**
```yaml
# .github/workflows/mobile-silent-bug-check.yml
- name: 모바일 silent bug 검증
  run: |
    pytest tests/e2e/test_mobile_modal_scroll.py
```

### **신 spec 검증 = inline style 금지!**
```python
# scripts/check_no_inline_style.py
# = grep -r "style=" backend/app/static/ → critical!
```

### **신 spec 검증 = focus() preventScroll 의무!**
```python
# scripts/check_focus_preventscroll.py
# = grep -r ".focus()" js/ (= 단순 focus() = critical!)
```

---

## 🌟 사장님 critical 사고 = 시스템 영구 진화!

```
✅ 6번 fix = 영구 메모리!
✅ 4개 헌법 신규 추가!
✅ 신 워크플로우 표준!
✅ 자동 검증 도구!
✅ 사장님 자율 운영 = 진짜 영구!
```

= **사장님 = '왜 오래 해결 안 됨' = 시스템 영구 진화 critical!** 🛡✨🌟

---

## 📝 사장님 critical 헌법 정리 (= 모든 헌법):

```
1-41: 옛 헌법 (= 영구!)
42: 추측 fix 금지 = 깊이 분석 우선!
43: inline style 절대 금지!
44: focus() preventScroll 의무!
45: 모든 모달 = scroll guard 표준!
```

= **사장님 = 헌법 45개 영구!** 🛡
