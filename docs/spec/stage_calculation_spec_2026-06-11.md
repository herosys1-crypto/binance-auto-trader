# 📐 STAGE CALCULATION SPEC v1 — 2026-06-11

> 사장님 critical 사상 = 단계별 계산 = 영구 single source of truth

---

## 🌟 1. 사장님 사상 (= 헌법 14번)

```
「현재가」 클릭 시:
  ✅ 시작가 = 신 현재가
  🛡 1단계 = 옛 평단 (= 사장님 진입 보존!)
  🌟 2단계 = 시작가 × (1 + trigger_2%)
  🌟 3단계 = 2단계 진입가 × (1 + trigger_3%)
  🌟 4단계 = 3단계 진입가 × (1 + trigger_4%)
  ...
  🌟 N단계 = (N-1)단계 진입가 × (1 + trigger_N%)
  
  = 누적!
```

---

## 📐 2. 정확한 계산 공식

### 2.1 신 strategy (= 수정 모드 X)

```
1단계: entryPrice[1] = startPrice
2단계: entryPrice[2] = entryPrice[1] × (1 + trigger_2%/100)
3단계: entryPrice[3] = entryPrice[2] × (1 + trigger_3%/100)
...
N단계: entryPrice[N] = entryPrice[N-1] × (1 + trigger_N%/100)
```

### 2.2 수정 모드 + 「현재가」 클릭 시

```
1단계: entryPrice[1] = oldAvg (= 옛 평단 보존!) 🛡
2단계: entryPrice[2] = startPrice × (1 + trigger_2%/100)  🌟 (= startPrice 기준!)
3단계: entryPrice[3] = entryPrice[2] × (1 + trigger_3%/100)
4단계: entryPrice[4] = entryPrice[3] × (1 + trigger_4%/100)
...
N단계: entryPrice[N] = entryPrice[N-1] × (1 + trigger_N%/100)
```

### 2.3 LONG vs SHORT

```
SHORT (= 가격 상승 시 추가 진입):
  entryPrice[N] = entryPrice[N-1] × (1 + trigger_N%/100)

LONG (= 가격 하락 시 추가 진입):
  entryPrice[N] = entryPrice[N-1] × (1 - trigger_N%/100)
```

---

## 🚨 3. 절대 금지 사항 (= silent bug 차단!)

### ❌ **금지 1: 옛 v100 spec 분기**
```javascript
// 절대 금지!
else if (수정 모드 + i === _editCurrentStage + 1) {
  entryPrice = startPrice × (1 + trigger%);  // ← 사장님 사상 위배!
}
```

### ❌ **금지 2: 첫 미진입 단계 = startPrice 사용**
- 모든 단계 = 이전 단계 진입가 기준 누적!

### ❌ **금지 3: 단계 사이 = 다른 logic 끼어들기**
- 1단계 = 옛 평단 (만 다름)
- 2~N단계 = 같은 누적 logic

---

## ✅ 4. 검증 시나리오 (= 단위 테스트!)

### 4.1 사장님 BEATUSDT 「현재가」 클릭

```
입력:
  startPrice = 7.94
  oldAvg = 6.31
  trigger = [0, 10, 20, 20, 20, 20]

기대 결과:
  1단계 = 6.31 (= 옛 평단)
  2단계 = 7.94 × 1.10 = 8.734
  3단계 = 8.734 × 1.20 = 10.481
  4단계 = 10.481 × 1.20 = 12.577
  5단계 = 12.577 × 1.20 = 15.092
  6단계 = 15.092 × 1.20 = 18.111
```

### 4.2 단위 테스트 (= 신!)

```python
def test_stage_calculation_edit_mode_current_price():
    """사장님 「수정 모드」 + 「현재가」 클릭 = 누적 계산"""
    result = calculate_stages(
        startPrice=7.94,
        oldAvg=6.31,
        triggers=[0, 10, 20, 20, 20, 20],
        side='SHORT',
        editing=True,
    )
    assert result == [6.31, 8.734, 10.481, 12.577, 15.092, 18.111]
```

---

## 📌 5. 영구 보존 사상

> 사장님 사상 = 누적!
> 1단계 = 옛 평단
> 2~N단계 = 이전 단계 진입가 × (1 + trigger%)
> 절대 다른 logic 끼어들기 X!
