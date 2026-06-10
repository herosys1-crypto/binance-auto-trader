# 📐 CURRENT PRICE ACTION SPEC v1 — 2026-06-11

> 사장님 「현재가」 버튼 클릭 = 영구 사상 (= v40, v43!)

---

## 🌟 1. 사장님 사상 (= 헌법 14번!)

```
🌟 「현재가」 클릭 = 시작가 = 신 현재가!
🛡 1단계 = 옛 평단 (= 사장님 진입 보존!)
🌟 2단계 = 시작가 × (1 + trigger_2%)
🌟 3단계 = 2단계 진입가 × (1 + trigger_3%)
🌟 4단계 부터 = 누적!
```

---

## 🎯 2. 동작 흐름 (= 정확!)

### 2.1 사용자 클릭 → fillStartPrice('current')

```javascript
function fillStartPrice('current') {
  // 1. 시작가 = 신 현재가
  document.getElementById('cm-start-price').value = formatted_current_price;
  
  // 2. _refreshLiveCalc() 호출
  _refreshLiveCalc();
  
  // 3. (v39) toast 알림
  if (수정 모드) {
    toast('1단계 = 옛 평단 보존, 2단계+ = 신 시작가!')
  }
}
```

### 2.2 _refreshLiveCalc() 동작

```javascript
let prevPrice = startPrice;  // 초기

for (let i = 1; i <= 10; i++) {
  const cap = capital[i];
  const tNum = trigger[i];
  
  if (compressedStageNo === 1) {
    // 1단계 = 첫 채워진 단계
    if (수정 모드 + 시작가 변경 감지) {
      entryPrice = oldAvg;  // 옛 평단 보존!
    } else {
      entryPrice = startPrice;  // 신 strategy
    }
    pendingTriggerPct = 0;
  } else {
    // 2단계 이상 = 누적 (= 사장님 사상!)
    const effectiveTrgPct = tNum + pendingTriggerPct;
    pendingTriggerPct = 0;
    if (side === 'SHORT') {
      entryPrice = prevPrice × (1 + effectiveTrgPct / 100);
    } else {
      entryPrice = prevPrice × (1 - effectiveTrgPct / 100);
    }
  }
  
  // 다음 단계 기준
  if (compressedStageNo === 1 && 수정 모드 + 시작가 변경) {
    prevPrice = startPrice;  // 2단계 기준 = startPrice!
  } else {
    prevPrice = entryPrice;
  }
}
```

---

## 📊 3. 사장님 BEATUSDT 시나리오

### 입력:
```
startPrice = 7.94 (= 신 현재가)
oldAvg = 6.31 (= 사장님 평단)
capitals = [100, 200, 500, 700, 1200, 1500]
triggers = [0, 10, 20, 20, 20, 20]
side = SHORT
editing = true
```

### 기대 결과:
```
1단계: entryPrice = 6.31 (= 옛 평단!) 🛡
       prevPrice = 7.94 (= startPrice!)

2단계: entryPrice = 7.94 × 1.10 = 8.734
       prevPrice = 8.734

3단계: entryPrice = 8.734 × 1.20 = 10.481
       prevPrice = 10.481

4단계: entryPrice = 10.481 × 1.20 = 12.577
       prevPrice = 12.577

5단계: entryPrice = 12.577 × 1.20 = 15.092
       prevPrice = 15.092

6단계: entryPrice = 15.092 × 1.20 = 18.111
```

= **사장님 사상 100% 정확!** 🌟

---

## 🚨 4. silent bug 차단 (= 영구!)

### ❌ **금지 1: 1단계 = startPrice 강제 사용**
- 사장님 수정 모드 = 1단계 = oldAvg 필수!

### ❌ **금지 2: 옛 v100 분기 = startPrice × (1 + trigger%)**
- 첫 미진입 단계 만 = 다른 logic = silent bug!
- 모든 단계 = 같은 누적 logic!

### ❌ **금지 3: prevPrice 잘못 설정**
- 1단계 = oldAvg 일 때 = prevPrice = oldAvg 면 silent bug!
- = prevPrice = startPrice 필수 (= 2단계 기준!)

---

## ✅ 5. 검증 (= 자동 테스트!)

```python
def test_current_price_click_edit_mode():
    """사장님 BEATUSDT 「현재가」 클릭 시나리오"""
    result = calculate_stages(
        startPrice=7.94,
        oldAvg=6.31,
        capitals=[100, 200, 500, 700, 1200, 1500],
        triggers=[0, 10, 20, 20, 20, 20],
        side='SHORT',
        editing=True,
        currentPriceClicked=True,
    )
    expected = [6.31, 8.734, 10.481, 12.577, 15.092, 18.111]
    for i, exp in enumerate(expected):
        assert abs(result[i] - exp) < 0.01, f"단계 {i+1}: {result[i]} != {exp}"
```

---

## 📌 6. 영구 보존

> 「현재가」 클릭 = 사장님 사상!
> 1단계 = 옛 평단 (= 진입 보존!)
> 2단계+ = 이전 단계 × (1 + trigger%) (= 누적!)
> 절대 다른 logic X!
