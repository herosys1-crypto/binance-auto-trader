# 📐 EDIT MODE SPEC v1 — 2026-06-11

> 사장님 「수정 모드」 = 영구 사상 (= v38, v40, v41, v42, v43 통합!)

---

## 🌟 1. 사장님 사상 (= 헌법 13번!)

```
🌟 「수정 모드」 = 옛 strategy 모든 세팅 = 그대로 보존!
🌟 시작가 = 옛 시작가 (= 사장님 직접 「현재가」 클릭 시만 변경!)
🌟 단순 수정 = 자본 + 트리거 조정 = 사장님 자율
🌟 초기화 = 별도 옵션 = 사장님 자율 선택
```

---

## 📊 2. 「수정 모드」 모달 = 첫 화면

### 2.1 옛 strategy 데이터 로드

```
backend response (= bp):
  - source_strategy_id
  - symbol, side, leverage
  - start_price (= 옛 시작가)
  - avg_entry_price (= 옛 평단, v41 신!)
  - capitals = [100, 200, 500, 700, 1200, 1500]
  - trigger_percents = [0, 10, 20, 20, 20, 20]
  - ...
```

### 2.2 frontend 채움 logic

```javascript
// v38 + v41 fix:
const oldStartPrice = (
  bp.start_price        // 옛 시작가!
  || bp.avg_entry_price // NULL fallback = 평단!
  || ''
).toString();
document.getElementById('cm-start-price').value = oldStartPrice;

// 자본, 트리거 = 옛 그대로
for (let i = 0; i < bp.capitals.length; i++) {
  document.getElementById('cm-cap-' + (i+1)).value = bp.capitals[i];
}
for (let i = 0; i < bp.trigger_percents.length; i++) {
  document.getElementById('cm-trg-' + (i+1)).value = bp.trigger_percents[i];
}

// v42 fix: _refreshLiveCalc 강제 호출 = 단계별 진입가 표시!
_refreshLiveCalc();
```

---

## 🛡 3. 「현재가」 클릭 시 동작 (= v40, v43!)

### 3.1 사장님 사상

```
🛡 1단계 = 옛 평단 (= 사장님 진입 보존!)
🌟 2단계 = 시작가 × (1 + trigger_2%)
🌟 3단계 부터 = 이전 단계 누적
```

### 3.2 구현

```javascript
// cm-capitals-grid.js _refreshLiveCalc():
if (compressedStageNo === 1) {
  if (수정 모드 + 시작가 변경 감지) {
    entryPrice = oldAvg;  // 1단계 = 옛 평단!
  } else {
    entryPrice = startPrice;
  }
}

// 그 후 prevPrice 강제:
if (1단계 = 옛 평단) {
  prevPrice = startPrice;  // 2단계 기준 = startPrice!
} else {
  prevPrice = entryPrice;
}
```

### 3.3 v43: 옛 v100 분기 폐기

```
❌ 옛 silent bug:
  else if (수정 모드 + i === _editCurrentStage + 1):
    entryPrice = startPrice × (1 + trigger%)  // ← 폐기!

✅ 신 v43:
  모든 단계 = 누적 logic 만!
```

---

## 🎯 4. 사장님 옵션 4가지

| 옵션 | 동작 | 결과 |
|---|---|---|
| **A. 「취소」** | 모달 닫기 | 옛 strategy 그대로 |
| **B. 「✓ 설정만 수정」** | TP/SL만 즉시 갱신 | 거래소 호출 X |
| **C. 「✏️ 종료 후 새로 시작」** | 미체결 취소 + 1단계 새로 | 신 strategy |
| **D. 「↻ 미진입 단계만 재설정」** | 진입 단계 보존 + 미진입 재계산 | v100 신 기능 |

---

## 🚨 5. 절대 금지 (= silent bug 차단!)

### ❌ **금지 1: 자동 현재가 덮어쓰기 (v38 fix!)**
- 옛 v29 = 「수정 모드」 진입 시 = 자동 현재가
- = 사장님 사상 위배! = silent bug!

### ❌ **금지 2: bp.start_price NULL 빈값 표시 (v41 fix!)**
- 옛 silent bug = 모든 단계 빈값
- = avg_entry_price fallback 필수!

### ❌ **금지 3: _refreshLiveCalc 호출 누락 (v42 fix!)**
- 첫 화면 = 단계별 진입가 = 자동 표시 필수!

### ❌ **금지 4: 옛 v100 분기 silent bug (v43 fix!)**
- 첫 미진입 단계 = startPrice 사용 = 사장님 사상 위배!

---

## 📌 6. 영구 보존

> 「수정 모드」 = 옛 세팅 그대로!
> 「현재가」 클릭 = 1단계 평단 + 2단계+ 누적!
> 절대 silent X!
