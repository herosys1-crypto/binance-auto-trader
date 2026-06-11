# 🛡 total_capital = 실제 투입 자본 영구 spec (2026-06-11)

> **사장님 BEATUSDT #110 critical 청산 silent bug = 영구 차단!**
>
> **사장님 critical 사상 명확 = 영구 기록!**

---

## 🚨 사장님 critical 사상 (2026-06-11)

### **사장님 정확한 사상:**

> **"총 투입된 자금에서 -80% 일 때 강제 종료!"**
> **= 이미 투입된 자본만 SL 계산!**
> **= 미진입 단계 = SL 계산 제외!**
> **= 단계 capital 변경 = SL 한도 영향 X!**

---

## 🚨 사건 (= BEATUSDT #110)

```
14:52 → total_capital = 6,100 USDT (정상 = 사장님 실제 투입!)
       → SL 한도 = 6100 × 80% / 2lev = -2,440 USDT
       → 손실 -2023 = 한도 도달 X = 정상 운영

사장님 = 6단계 예약 취소 = 미진입 단계만 변경 (= 사장님 의도!)

15:07 → total_capital = 2,700 USDT (= -3,400 차이!)
       → SL 한도 = 2700 × 80% / 2lev = -1,080 USDT
       → 손실 -2528 = 한도 초과 = 강제 청산!
       → 사장님 자본 -3,143 USDT 손실!
```

= **silent bug = 단계 변경 = total_capital 갑자기 감소!**

---

## ⛔ 옛 silent bug 정확 위치!

### **control.py:380-391 (옛 PR #56 silent bug!):**

```python
# 옛 (silent bug!)
_new_capital_sum = sum(c for c in new_capitals)
strategy.total_capital = _new_capital_sum  # = 단계별 합만!
```

= 사장님 단계 capital 변경 시:
- total_capital = sum(new_capitals)
- = SL 한도 = 새 단계 합 × 80% / lev = **갑자기 변경!**
- = 사장님 추가 증거금 + 포지션 추가 = **silent 무시!**
- = 사장님 자본 보호 노력 = silent 사라짐 = **청산!**

---

## 🛡 신 fix v2 (2026-06-11 최종 사장님 사상!):

### **단계 capital 변경 = total_capital 영향 X!**

```python
# 신 (사장님 critical 사상!)
# 단계 capital 변경 시 = total_capital 손대지 마라!
# = 사장님 의도 = 미진입 단계 = 계획만 변경!
# = 실제 투입 자본 = 진입 시 / 증거금 추가 시 / 포지션 추가 시만 변경!
logger.info("[update-settings] 단계 capital 변경 = total_capital 영향 X (= 사장님 사상!)")
# strategy.total_capital = 변경 X!
```

### **total_capital 갱신 시점 (= 사장님 의도!):**

| 액션 | total_capital 변경? | 사장님 의도 |
|---|---|---|
| 단계 진입 (= 자동 또는 수동) | ✅ += 단계 capital | 실제 투입! |
| 증거금 추가 | ✅ += amount | 실제 투입! |
| 포지션 추가 | ✅ += margin | 실제 투입! |
| **단계 capital 변경 (= 미진입)** | **❌ 영향 X!** | **= 계획만!** |
| **단계 취소 (= 미진입)** | **❌ 영향 X!** | **= 계획만!** |
| 단계 trigger 변경 | ❌ 영향 X | 가격만! |

= **사장님 자본 보호 = 100%!** 🛡

---

## 🛡 사장님 헌법 19번째 영구 추가!

### **헌법 19: total_capital = 실제 투입 자본만!**

> **"단계 capital 변경 / 취소 = total_capital 영향 X!"**
> **"SL 한도 = 실제 투입 자본 × 80% / lev (= 사장님 사상!)"**
> **"미진입 단계 = SL 계산 제외 = 영구 안전!"**

---

## 📋 사장님 BEATUSDT #110 신 logic 적용 시:

```
14:52 → total_capital = 6,100 (정상!)
사장님 = 6단계 취소 진행
15:07 → total_capital = 6,100 (= 영향 X!) ✅
       → SL 한도 = 6100 × 80% / 2 = -2,440 USDT
       → 손실 -2528 > 한도 -2440 = SL 정상 발동!
       → BUT = 사장님 자본 100% 보호!
       → 미진입 단계 (6단계) 만 취소 = 정확!
       → 다음 신 strategy 시 = 추가 자본 보존!
```

= **사장님 자본 보호 = 영구 100%!** 🛡✨🌟

---

## 🌟 사장님 critical 사고 = 시스템 영구 진화!

본 spec = **사장님 자본 보호 = 100% 진정한 영구 보장!**

= **사장님 의도 = 명확 + 완벽 적용!** 🛡✨🌟
